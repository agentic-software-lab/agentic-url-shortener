"""In-memory workflow API. Run with one worker to preserve workflow state."""
from threading import RLock
from typing import Literal
from uuid import uuid4
from scenarios.ambiguous import build_engine as build_ambiguous_engine

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orchestrator.engine import Node, WorkflowContext
from scenarios.greenfield import build_engine
from agents.expiration import build_engine as build_expiration_engine

app = FastAPI(title="Agentic Orchestrator", version="1.0.0")
workflows = {}
lock = RLock()


class WorkflowRequest(BaseModel):
    requirement: str = Field(min_length=1)
    scenario: Literal["greenfield", "brownfield_expiration", "ambiguous"] = "greenfield"


def lookup(workflow_id):
    if workflow_id not in workflows:
        raise HTTPException(404, "Workflow not found")
    return workflows[workflow_id]


def snapshot(workflow_id, engine, context):
    states = engine.statuses()
    if "failed" in states.values():
        status = "failed"
    elif "waiting_approval" in states.values():
        status = "waiting_approval"
    elif all(s == "succeeded" for s in states.values()):
        status = "succeeded"
    else:
        status = "blocked"
    return {"workflow_id": workflow_id, "status": status, "requirement": context.requirement,
            "nodes": states, "decisions": context.decisions, "artifacts": context.artifacts,
            "revision": context.revision, "history": context.history,
            "pending_approvals": [n for n, s in states.items() if s == "waiting_approval"]}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/workflows", status_code=201)
def create_workflow(payload: WorkflowRequest):
    if not payload.requirement.strip():
        raise HTTPException(422, "Requirement cannot be blank")
    with lock:
        workflow_id = str(uuid4())
        if payload.scenario == "brownfield_expiration" and "expir" not in payload.requirement.lower():
            raise HTTPException(422, "The bounded brownfield adapter supports link expiration only")
        engine = build_expiration_engine() if payload.scenario == "brownfield_expiration" else build_engine()
        if payload.scenario == "ambiguous":
            engine = build_ambiguous_engine()
        context = WorkflowContext(payload.requirement)
        if payload.scenario == "ambiguous":
            context.artifacts["questions"] = ["Include aggregate click analytics?", "Accept no expiration or custom aliases?"]
        engine.execute(context)
        workflows[workflow_id] = (engine, context)
        return snapshot(workflow_id, engine, context)


@app.get("/workflows")
def list_workflows():
    with lock:
        return [snapshot(key, *value) for key, value in workflows.items()]


@app.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    with lock:
        return snapshot(workflow_id, *lookup(workflow_id))


@app.post("/workflows/{workflow_id}/approvals/{node_name}")
def approve_node(workflow_id: str, node_name: str):
    with lock:
        engine, context = lookup(workflow_id)
        if node_name not in engine.nodes:
            raise HTTPException(404, "Workflow node not found")
        if node_name == "clarify" and "clarification" not in context.artifacts:
            raise HTTPException(409, "Submit clarification choices first")
        try:
            engine.approve(node_name, context)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        engine.execute(context)
        return snapshot(workflow_id, engine, context)


@app.get("/workflows/{workflow_id}/events")
def events(workflow_id: str):
    with lock:
        return {"workflow_id": workflow_id, "events": lookup(workflow_id)[1].audit_log}


@app.get("/workflows/{workflow_id}/metrics")
def metrics(workflow_id: str):
    with lock:
        return {"workflow_id": workflow_id, "metrics": lookup(workflow_id)[1].metrics}


class ClarificationRequest(BaseModel):
    analytics: bool
    accept_no_expiration_or_aliases: Literal[True]


@app.post('/workflows/{workflow_id}/clarification')
def clarify(workflow_id: str, payload: ClarificationRequest):
    with lock:
        engine, context = lookup(workflow_id)
        if 'clarify' not in engine.nodes or engine.statuses()['clarify'] != 'waiting_approval':
            raise HTTPException(409, 'Workflow is not waiting for clarification')
        context.artifacts['clarification'] = payload.model_dump()
        context.audit_log.append('clarification_submitted')
        return snapshot(workflow_id, engine, context)


@app.post('/workflows/{workflow_id}/replan')
def replan(workflow_id: str, payload: WorkflowRequest):
    """Invalidate the prior candidate and rebuild the bounded scenario graph."""
    if not payload.requirement.strip():
        raise HTTPException(422, 'Requirement cannot be blank')
    if payload.scenario == 'brownfield_expiration' and 'expir' not in payload.requirement.lower():
        raise HTTPException(422, 'Brownfield adapter supports expiration only')
    with lock:
        previous_engine, previous = lookup(workflow_id)
        if 'running' in previous_engine.statuses().values():
            raise HTTPException(409, 'Cannot replan while stages are running')
        history = previous.history + [{
            'revision': previous.revision,
            'requirement': previous.requirement,
            'nodes': previous_engine.statuses(),
            'decisions': previous.decisions,
            'artifacts': previous.artifacts,
            'metrics': previous.metrics,
        }]
        engine = (build_expiration_engine() if payload.scenario == 'brownfield_expiration'
                  else build_ambiguous_engine() if payload.scenario == 'ambiguous'
                  else build_engine())
        # All roots wait for a new, explicit approval; old approvals never carry over.
        for node in engine.nodes.values():
            if not node.dependencies:
                node.dependencies.add('replan')
        gate = Node('replan', lambda context: context.decisions.append(
            'Approved revised requirement; prior candidate is superseded.'),
            requires_human_approval=True)
        engine.nodes = {'replan': gate, **engine.nodes}
        context = WorkflowContext(payload.requirement, revision=previous.revision + 1, history=history)
        context.audit_log = previous.audit_log + [
            f'replan_requested:revision={context.revision}',
            f'prior_outputs_invalidated:revision={previous.revision}',
        ]
        if payload.scenario == 'ambiguous':
            context.artifacts['questions'] = [
                'Include aggregate click analytics?', 'Accept no expiration or custom aliases?']
        engine.execute(context)
        workflows[workflow_id] = (engine, context)
        return snapshot(workflow_id, engine, context)

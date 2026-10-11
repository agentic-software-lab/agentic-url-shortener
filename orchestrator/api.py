"""In-memory workflow API. Run with one worker to preserve workflow state."""
from threading import RLock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from orchestrator.engine import WorkflowContext
from scenarios.greenfield import build_engine

app = FastAPI(title="Agentic Orchestrator", version="1.0.0")
workflows = {}
lock = RLock()


class WorkflowRequest(BaseModel):
    requirement: str = Field(min_length=1)


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
        engine, context = build_engine(), WorkflowContext(payload.requirement)
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

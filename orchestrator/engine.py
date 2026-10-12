from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from orchestrator.observability import artifact_digest, utc_timestamp
from time import perf_counter
from typing import Callable, Dict, Iterable, List, Optional, Set


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class WorkflowContext:
    requirement: str
    decisions: List[str] = field(default_factory=list)
    artifacts: Dict[str, object] = field(default_factory=dict)
    audit_log: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    revision: int = 1
    history: List[Dict[str, object]] = field(default_factory=list)
    audit_events: List[Dict[str, object]] = field(default_factory=list)
    task_runs: List[Dict[str, object]] = field(default_factory=list)
    artifact_lineage: Dict[str, Dict[str, object]] = field(default_factory=dict)
    _active_task: Optional[str] = field(default=None, repr=False)
    _active_attempt: Optional[int] = field(default=None, repr=False)

    def record_event(self, message, *, task_id=None, attempt=None, actor="system", details=None):
        event = {"sequence": len(self.audit_events) + 1, "timestamp": utc_timestamp(),
                 "revision": self.revision, "event_type": message.split(":", 1)[0],
                 "task_id": task_id if task_id is not None else self._active_task,
                 "attempt": attempt if attempt is not None else self._active_attempt,
                 "actor": actor, "message": message, "details": deepcopy(details or {})}
        self.audit_log.append(message)
        self.audit_events.append(event)
        return event

    def merge_worker_events(self, worker, baseline):
        # Worker sequences are local; assign authoritative order on ingestion.
        # Preserve occurrence timestamps and source revision from each worker.
        events = iter(worker.audit_events[len(baseline.audit_events):])
        pending = next(events, None)
        for message in worker.audit_log[len(baseline.audit_log):]:
            if pending is not None and pending["message"] == message:
                event = deepcopy(pending)
                event["sequence"] = len(self.audit_events) + 1
                self.audit_events.append(event)
                self.audit_log.append(message)
                pending = next(events, None)
            else:
                # Backward-compatible adapters may still append plain strings.
                self.record_event(message, task_id=worker._active_task,
                                  attempt=worker._active_attempt)



@dataclass
class Node:
    name: str
    run: Callable[[WorkflowContext], Optional["ReplanRequest"]]
    dependencies: Set[str] = field(default_factory=set)
    requires_human_approval: bool = False
    max_retries: int = 1
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    fallback: Optional[Callable[[WorkflowContext], Optional["ReplanRequest"]]] = None
    rollback: Optional[Callable[[WorkflowContext], None]] = None
    fallback_used: bool = False
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    fallback_succeeded: bool = False
    failure_started: Optional[float] = None
    recovery_ms: Optional[float] = None
    output: str = ""
    acceptance: List[str] = field(default_factory=list)


@dataclass
class ReplanRequest:
    source: str
    reason: str
    add_tasks: List[Node] = field(default_factory=list)
    modify_tasks: List[Node] = field(default_factory=list)


class WorkflowEngine:
    def __init__(self, nodes: Iterable[Node], planner=None, planning_trigger="requirements", max_replans=4) -> None:
        items = list(nodes)
        self.nodes = {node.name: node for node in items}
        if len(self.nodes) != len(items):
            raise ValueError('Duplicate workflow node names')
        for node in items:
            if not node.name or node.max_retries < 0:
                raise ValueError('Node names must be non-empty and retries non-negative')
            missing = node.dependencies - self.nodes.keys()
            if missing:
                raise ValueError(f'Unknown dependencies for {node.name}: {sorted(missing)}')
        remaining = set(self.nodes)
        resolved = set()
        while remaining:
            ready = {name for name in remaining if self.nodes[name].dependencies <= resolved}
            if not ready:
                raise ValueError('Workflow dependency graph contains a cycle')
            resolved.update(ready)
            remaining -= ready
        if max_replans < 0:
            raise ValueError("Replanning budget must be non-negative")
        if planner is not None and planning_trigger not in self.nodes:
            raise ValueError("Planning trigger must exist in the graph")
        self.planner = planner
        self.planning_trigger = planning_trigger
        self._planned = False
        self.max_replans = max_replans
        self._replans = 0
        self.safe_stopped = False
        self._started: Optional[float] = None
        self._finished: Optional[float] = None
        self._active_ms = 0.0

    def plan(self):
        return [{"id": n.name, "dependencies": sorted(n.dependencies),
                 "output": n.output, "acceptance": list(n.acceptance),
                 "status": n.status.value} for n in self.nodes.values()]

    def apply_replan(self, request, context):
        """Validate a candidate graph before committing any runtime mutation."""
        context.record_event(f"replan_requested:{request.source}:{request.reason}",
            task_id=request.source, details={"reason": request.reason})
        try:
            if self.safe_stopped or self._replans >= self.max_replans:
                raise ValueError("Replanning budget exhausted or workflow stopped")
            if request.source not in self.nodes or self.nodes[request.source].status != NodeStatus.SUCCEEDED:
                raise ValueError("Replanning source must be a successful task")
            if not request.reason.strip() or not (request.add_tasks or request.modify_tasks):
                raise ValueError("Replanning requires a reason and changes")
            downstream = set()
            while True:
                expanded = downstream | {n.name for n in self.nodes.values()
                    if request.source in n.dependencies or n.dependencies & downstream}
                if expanded == downstream:
                    break
                downstream = expanded
            candidate = dict(self.nodes)
            changed = []
            for node in request.add_tasks:
                if node.name in candidate:
                    raise ValueError("Added task already exists: " + node.name)
                candidate[node.name] = node
                changed.append(node.name)
            for node in request.modify_tasks:
                if node.name not in downstream:
                    raise ValueError("Only downstream tasks may be modified: " + node.name)
                old = candidate[node.name]
                if old.status not in {NodeStatus.PENDING, NodeStatus.BLOCKED, NodeStatus.WAITING_APPROVAL} or old.attempts:
                    raise ValueError("Cannot modify already executed task: " + node.name)
                if old.requires_human_approval and not node.requires_human_approval:
                    raise ValueError("Cannot remove an approval gate")
                # Previously approved work must receive fresh approval after changes.
                if f"human_approved:{node.name}" in context.audit_log:
                    node.requires_human_approval = True
                candidate[node.name] = node
                changed.append(node.name)
            if len(changed) != len(set(changed)):
                raise ValueError("Duplicate task changes")
            for name in changed:
                node = candidate[name]
                if node.status != NodeStatus.PENDING or node.attempts:
                    raise ValueError("Replanned tasks must be fresh pending tasks")
            WorkflowEngine(candidate.values())  # Reuse initial DAG validation.
            reachable = {request.source}
            while True:
                expanded = reachable | {n.name for n in candidate.values() if n.dependencies & reachable}
                if expanded == reachable:
                    break
                reachable = expanded
            if not set(changed) <= reachable:
                raise ValueError("New work must be downstream of its source")
        except (ValueError, TypeError, AttributeError) as exc:
            self.safe_stopped = True
            context.record_event(f"replan_rejected:{exc}", task_id=request.source,
                details={"reason": request.reason, "error": str(exc)})
            context.record_event("safe_stop:replan", task_id=request.source)
            for node in self.nodes.values():
                if node.status != NodeStatus.SUCCEEDED and node.status != NodeStatus.FAILED:
                    node.status = NodeStatus.BLOCKED
            return False
        preserved = [n.name for n in self.nodes.values() if n.status == NodeStatus.SUCCEEDED]
        before = self.plan()
        self.nodes = candidate
        self._replans += 1
        context.revision += 1
        context.history.append({"revision": context.revision, "source": request.source,
            "reason": request.reason, "added": [n.name for n in request.add_tasks],
            "modified": [n.name for n in request.modify_tasks], "preserved": preserved,
            "before": before, "after": self.plan()})
        context.record_event(f"replan_completed:revision={context.revision}:changed={','.join(changed)}",
            task_id=request.source, details={"reason": request.reason, "added": [n.name for n in request.add_tasks],
                "modified": [n.name for n in request.modify_tasks], "preserved": preserved})
        return True

    def _dependencies_succeeded(self, node: Node) -> bool:
        return all(self.nodes[name].status == NodeStatus.SUCCEEDED for name in node.dependencies)

    def approve(self, node_name: str, context: WorkflowContext) -> None:
        node = self.nodes[node_name]
        if node.status != NodeStatus.WAITING_APPROVAL:
            raise ValueError(f"{node_name} is not waiting for approval")
        node.requires_human_approval = False
        node.status = NodeStatus.PENDING
        context.record_event(f"human_approved:{node_name}", task_id=node_name, actor="human")

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        started = perf_counter()
        if self._started is None:
            self._started = started
        with ThreadPoolExecutor(max_workers=4) as pool:
            while not self.safe_stopped:
                ready = []
                for node in self.nodes.values():
                    if node.status not in {NodeStatus.PENDING, NodeStatus.BLOCKED}:
                        continue
                    if not self._dependencies_succeeded(node):
                        node.status = NodeStatus.BLOCKED
                        continue
                    if node.requires_human_approval:
                        node.status = NodeStatus.WAITING_APPROVAL
                        context.record_event(f"approval_required:{node.name}", task_id=node.name)
                        continue
                    ready.append(node)
                if not ready:
                    break

                # Isolated snapshots avoid concurrent mutations of shared context.
                baseline = deepcopy(context)
                futures = []
                for node in ready:
                    node.status = NodeStatus.RUNNING
                    node.attempts += 1
                    start_event = context.record_event(f"start:{node.name}:attempt={node.attempts}",
                        task_id=node.name, attempt=node.attempts,
                        details={"dependencies": sorted(node.dependencies)})
                    worker_context = deepcopy(baseline)
                    worker_context._active_task = node.name
                    worker_context._active_attempt = node.attempts
                    worker_context._start_event = start_event
                    futures.append((node, worker_context, pool.submit(self._run_attempt, node, worker_context)))

                # Synchronize the whole wave before scheduling dependent stages.
                requests = []
                for node, worker_context, future in futures:
                    try:
                        result = future.result()
                        if isinstance(result, ReplanRequest) and result.source != node.name:
                            raise ValueError("Agent cannot impersonate another replan source")
                        updates = {
                            key: value for key, value in worker_context.artifacts.items()
                            if key not in baseline.artifacts or value != baseline.artifacts[key]
                        }
                        for key, value in updates.items():
                            if (key in context.artifacts
                                and (key not in baseline.artifacts
                                     or context.artifacts[key] != baseline.artifacts[key])
                                and context.artifacts[key] != value):
                                raise ValueError(f"Concurrent artifact conflict: {key}")
                        context.artifacts.update(updates)
                        context.decisions.extend(worker_context.decisions[len(baseline.decisions):])
                        context.merge_worker_events(worker_context, baseline)
                        if node.failure_started is not None and node.recovery_ms is None:
                            node.recovery_ms = (perf_counter() - node.failure_started) * 1000
                        node.status = NodeStatus.SUCCEEDED
                        event = context.record_event(f"success:{node.name}", task_id=node.name,
                            attempt=node.attempts, details={"artifact_keys": sorted(updates)})
                        self._record_task_run(context, baseline, worker_context, node, event, updates)
                        if isinstance(result, ReplanRequest):
                            requests.append(result)
                    except Exception as exc:
                        context.merge_worker_events(worker_context, baseline)
                        if node.failure_started is None:
                            node.failure_started = perf_counter()
                        event = context.record_event(f"failure:{node.name}:{type(exc).__name__}",
                            task_id=node.name, attempt=node.attempts,
                            details={"error_type": type(exc).__name__})
                        self._record_task_run(context, baseline, worker_context, node, event, {})
                        if node.attempts <= node.max_retries:
                            node.status = NodeStatus.PENDING
                            context.record_event(f"retry_scheduled:{node.name}", task_id=node.name, attempt=node.attempts)
                        else:
                            node.status = NodeStatus.FAILED
                            if node.rollback is not None and not node.rollback_attempted:
                                node.rollback_attempted = True
                                context.record_event(f"rollback_started:{node.name}", task_id=node.name, attempt=node.attempts)
                                compensation_baseline = deepcopy(worker_context)
                                try:
                                    node.rollback(worker_context)
                                    node.rollback_succeeded = True
                                except Exception as rollback_exc:
                                    context.merge_worker_events(worker_context, compensation_baseline)
                                    context.record_event(f"rollback_failed:{node.name}:{type(rollback_exc).__name__}", task_id=node.name, attempt=node.attempts)
                                else:
                                    context.merge_worker_events(worker_context, compensation_baseline)
                                    context.record_event(f"rollback_succeeded:{node.name}", task_id=node.name, attempt=node.attempts)
                            context.record_event(f"safe_stop:{node.name}", task_id=node.name, attempt=node.attempts)

                if self.planner and not self._planned and self.nodes[self.planning_trigger].status == NodeStatus.SUCCEEDED:
                    self._planned = True
                    try:
                        candidate = self.planner(context, self.nodes)
                        WorkflowEngine(candidate)
                        self.nodes = {n.name: n for n in candidate}
                        context.record_event("plan_generated:requirement",
                            details={"task_ids": list(self.nodes)})
                    except Exception as exc:
                        self.safe_stopped = True
                        context.record_event(f"safe_stop:planning:{exc}")
                        for n in self.nodes.values():
                            if n.status != NodeStatus.SUCCEEDED:
                                n.status = NodeStatus.BLOCKED
                for request in requests:
                    if not self.apply_replan(request, context):
                        break

        ended = perf_counter()
        self._active_ms += (ended - started) * 1000
        if self._finished is None and (self.safe_stopped or any(n.status == NodeStatus.FAILED for n in self.nodes.values()) or all(n.status == NodeStatus.SUCCEEDED for n in self.nodes.values())):
            self._finished = ended
        context.metrics["end_to_end_latency_ms"] = ((self._finished if self._finished is not None else ended) - self._started) * 1000
        context.metrics["active_execution_ms"] = self._active_ms
        context.metrics["last_execution_ms"] = (ended - started) * 1000
        context.metrics["success_rate"] = self._success_rate()
        context.metrics["retry_count"] = float(sum(max(0, n.attempts - 1) for n in self.nodes.values()))
        context.metrics["fallback_count"] = float(sum(n.fallback_used for n in self.nodes.values()))
        context.metrics["rollback_count"] = float(sum(n.rollback_attempted for n in self.nodes.values()))
        context.metrics["fallback_success_count"] = float(sum(n.fallback_succeeded for n in self.nodes.values()))
        context.metrics["rollback_success_count"] = float(sum(n.rollback_succeeded for n in self.nodes.values()))
        context.metrics["rollback_failure_count"] = float(sum(n.rollback_attempted and not n.rollback_succeeded for n in self.nodes.values()))
        recoveries = [n.recovery_ms for n in self.nodes.values() if n.recovery_ms is not None]
        context.metrics["recovered_node_count"] = float(len(recoveries))
        if recoveries:
            context.metrics["mttr_ms"] = sum(recoveries) / len(recoveries)
        context.metrics["completed_node_fraction"] = self._success_rate()
        context.metrics["workflow_succeeded"] = float(not self.safe_stopped and all(n.status == NodeStatus.SUCCEEDED for n in self.nodes.values()))
        return context

    def _record_task_run(self, context, baseline, worker, node, event, updates):
        start = worker._start_event
        run_id = f"run-{start['sequence']}"
        outputs = {key: {"digest": artifact_digest(value), "task_id": node.name,
                        "attempt": node.attempts, "revision": event["revision"],
                        "run_id": run_id, "event_sequence": event["sequence"]}
                   for key, value in updates.items()}
        context.task_runs.append({"run_id": run_id, "task_id": node.name,
            "attempt": node.attempts, "revision": start["revision"],
            "started_at": start["timestamp"], "finished_at": event["timestamp"],
            "start_event_sequence": start["sequence"], "end_event_sequence": event["sequence"],
            "outcome": event["event_type"], "dependencies": sorted(node.dependencies),
            "available_inputs": {key: {"digest": artifact_digest(value),
                "producer": deepcopy(baseline.artifact_lineage.get(key))}
                for key, value in baseline.artifacts.items()},
            "outputs": outputs,
            "decisions": worker.decisions[len(baseline.decisions):] if updates or event["event_type"] == "success" else [],
            "fallback_used": node.fallback_used})
        context.artifact_lineage.update(outputs)

    def _run_attempt(self, node: Node, context: WorkflowContext) -> Optional[ReplanRequest]:
        original = deepcopy(context)
        try:
            return node.run(context)
        except Exception as exc:
            if node.failure_started is None:
                node.failure_started = perf_counter()
            if node.attempts <= node.max_retries or node.fallback is None or node.fallback_used:
                raise
            node.fallback_used = True
            context.record_event(f"primary_exhausted:{node.name}:{type(exc).__name__}")
            context.record_event(f"fallback_started:{node.name}")
            context.artifacts = original.artifacts
            context.decisions = original.decisions
            try:
                result = node.fallback(context)
            except Exception as fallback_exc:
                context.record_event(f"fallback_failed:{node.name}:{type(fallback_exc).__name__}")
                raise
            node.fallback_succeeded = True
            context.record_event(f"fallback_succeeded:{node.name}")
            return result

    def _success_rate(self) -> float:
        if not self.nodes:
            return 1.0
        succeeded = sum(node.status == NodeStatus.SUCCEEDED for node in self.nodes.values())
        return succeeded / len(self.nodes)

    def statuses(self) -> Dict[str, str]:
        return {name: node.status.value for name, node in self.nodes.items()}

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
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


@dataclass
class Node:
    name: str
    run: Callable[[WorkflowContext], None]
    dependencies: Set[str] = field(default_factory=set)
    requires_human_approval: bool = False
    max_retries: int = 1
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    fallback: Optional[Callable[[WorkflowContext], None]] = None
    rollback: Optional[Callable[[WorkflowContext], None]] = None
    fallback_used: bool = False
    rollback_attempted: bool = False
    rollback_succeeded: bool = False
    fallback_succeeded: bool = False
    failure_started: Optional[float] = None
    recovery_ms: Optional[float] = None


class WorkflowEngine:
    def __init__(self, nodes: Iterable[Node]) -> None:
        self.nodes = {node.name: node for node in nodes}
        self._started: Optional[float] = None
        self._finished: Optional[float] = None
        self._active_ms = 0.0

    def _dependencies_succeeded(self, node: Node) -> bool:
        return all(self.nodes[name].status == NodeStatus.SUCCEEDED for name in node.dependencies)

    def approve(self, node_name: str, context: WorkflowContext) -> None:
        node = self.nodes[node_name]
        if node.status != NodeStatus.WAITING_APPROVAL:
            raise ValueError(f"{node_name} is not waiting for approval")
        node.requires_human_approval = False
        node.status = NodeStatus.PENDING
        context.audit_log.append(f"human_approved:{node_name}")

    def execute(self, context: WorkflowContext) -> WorkflowContext:
        started = perf_counter()
        if self._started is None:
            self._started = started
        with ThreadPoolExecutor(max_workers=4) as pool:
            while True:
                ready = []
                for node in self.nodes.values():
                    if node.status not in {NodeStatus.PENDING, NodeStatus.BLOCKED}:
                        continue
                    if not self._dependencies_succeeded(node):
                        node.status = NodeStatus.BLOCKED
                        continue
                    if node.requires_human_approval:
                        node.status = NodeStatus.WAITING_APPROVAL
                        context.audit_log.append(f"approval_required:{node.name}")
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
                    context.audit_log.append(f"start:{node.name}:attempt={node.attempts}")
                    worker_context = deepcopy(baseline)
                    futures.append((node, worker_context, pool.submit(self._run_attempt, node, worker_context)))

                # Synchronize the whole wave before scheduling dependent stages.
                for node, worker_context, future in futures:
                    try:
                        future.result()
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
                        context.audit_log.extend(worker_context.audit_log[len(baseline.audit_log):])
                        if node.failure_started is not None and node.recovery_ms is None:
                            node.recovery_ms = (perf_counter() - node.failure_started) * 1000
                        node.status = NodeStatus.SUCCEEDED
                        context.audit_log.append(f"success:{node.name}")
                    except Exception as exc:
                        context.audit_log.extend(worker_context.audit_log[len(baseline.audit_log):])
                        if node.failure_started is None:
                            node.failure_started = perf_counter()
                        context.audit_log.append(f"failure:{node.name}:{type(exc).__name__}")
                        if node.attempts <= node.max_retries:
                            node.status = NodeStatus.PENDING
                            context.audit_log.append(f"retry_scheduled:{node.name}")
                        else:
                            node.status = NodeStatus.FAILED
                            if node.rollback is not None and not node.rollback_attempted:
                                node.rollback_attempted = True
                                context.audit_log.append(f"rollback_started:{node.name}")
                                try:
                                    node.rollback(worker_context)
                                    node.rollback_succeeded = True
                                    context.audit_log.append(f"rollback_succeeded:{node.name}")
                                except Exception as rollback_exc:
                                    context.audit_log.append(f"rollback_failed:{node.name}:{type(rollback_exc).__name__}")
                            context.audit_log.append(f"safe_stop:{node.name}")

        ended = perf_counter()
        self._active_ms += (ended - started) * 1000
        if self._finished is None and (any(n.status == NodeStatus.FAILED for n in self.nodes.values()) or all(n.status == NodeStatus.SUCCEEDED for n in self.nodes.values())):
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
        context.metrics["workflow_succeeded"] = float(all(n.status == NodeStatus.SUCCEEDED for n in self.nodes.values()))
        return context

    def _run_attempt(self, node: Node, context: WorkflowContext) -> None:
        original = deepcopy(context)
        try:
            node.run(context)
        except Exception as exc:
            if node.failure_started is None:
                node.failure_started = perf_counter()
            if node.attempts <= node.max_retries or node.fallback is None or node.fallback_used:
                raise
            node.fallback_used = True
            context.audit_log.append(f"primary_exhausted:{node.name}:{type(exc).__name__}")
            context.audit_log.append(f"fallback_started:{node.name}")
            context.artifacts = original.artifacts
            context.decisions = original.decisions
            try:
                node.fallback(context)
            except Exception as fallback_exc:
                context.audit_log.append(f"fallback_failed:{node.name}:{type(fallback_exc).__name__}")
                raise
            node.fallback_succeeded = True
            context.audit_log.append(f"fallback_succeeded:{node.name}")

    def _success_rate(self) -> float:
        if not self.nodes:
            return 1.0
        succeeded = sum(node.status == NodeStatus.SUCCEEDED for node in self.nodes.values())
        return succeeded / len(self.nodes)

    def statuses(self) -> Dict[str, str]:
        return {name: node.status.value for name, node in self.nodes.items()}

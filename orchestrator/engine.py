from __future__ import annotations

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


@dataclass
class Node:
    name: str
    run: Callable[[WorkflowContext], None]
    dependencies: Set[str] = field(default_factory=set)
    requires_human_approval: bool = False
    max_retries: int = 1
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0


class WorkflowEngine:
    def __init__(self, nodes: Iterable[Node]) -> None:
        self.nodes = {node.name: node for node in nodes}

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
        progress = True

        while progress:
            progress = False
            for node in self.nodes.values():
                if node.status not in {NodeStatus.PENDING, NodeStatus.BLOCKED}:
                    continue
                if not self._dependencies_succeeded(node):
                    node.status = NodeStatus.BLOCKED
                    continue
                if node.requires_human_approval:
                    node.status = NodeStatus.WAITING_APPROVAL
                    context.audit_log.append(f"approval_required:{node.name}")
                    progress = True
                    continue

                node.status = NodeStatus.RUNNING
                node.attempts += 1
                context.audit_log.append(f"start:{node.name}:attempt={node.attempts}")

                try:
                    node.run(context)
                    node.status = NodeStatus.SUCCEEDED
                    context.audit_log.append(f"success:{node.name}")
                except Exception as exc:  # bounded retry is intentional here
                    context.audit_log.append(f"failure:{node.name}:{type(exc).__name__}")
                    if node.attempts <= node.max_retries:
                        node.status = NodeStatus.PENDING
                        context.audit_log.append(f"retry_scheduled:{node.name}")
                    else:
                        node.status = NodeStatus.FAILED
                        context.audit_log.append(f"safe_stop:{node.name}")
                progress = True

        context.metrics["end_to_end_latency_ms"] = (perf_counter() - started) * 1000
        context.metrics["success_rate"] = self._success_rate()
        context.metrics["retry_count"] = float(sum(max(0, n.attempts - 1) for n in self.nodes.values()))
        return context

    def _success_rate(self) -> float:
        if not self.nodes:
            return 1.0
        succeeded = sum(node.status == NodeStatus.SUCCEEDED for node in self.nodes.values())
        return succeeded / len(self.nodes)

    def statuses(self) -> Dict[str, str]:
        return {name: node.status.value for name, node in self.nodes.items()}

from orchestrator.engine import Node, NodeStatus, WorkflowContext, WorkflowEngine


def test_human_approval_gate_blocks_then_resumes() -> None:
    ran = []

    def work(context: WorkflowContext) -> None:
        ran.append("done")

    engine = WorkflowEngine([Node("work", work, requires_human_approval=True)])
    context = WorkflowContext("test")

    engine.execute(context)
    assert engine.nodes["work"].status == NodeStatus.WAITING_APPROVAL
    assert ran == []

    engine.approve("work", context)
    engine.execute(context)
    assert engine.nodes["work"].status == NodeStatus.SUCCEEDED
    assert ran == ["done"]


def test_bounded_retry_then_success() -> None:
    attempts = {"count": 0}

    def flaky(context: WorkflowContext) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("transient")

    engine = WorkflowEngine([Node("flaky", flaky, max_retries=1)])
    context = WorkflowContext("test")

    engine.execute(context)

    assert engine.nodes["flaky"].status == NodeStatus.SUCCEEDED
    assert attempts["count"] == 2
    assert context.metrics["retry_count"] == 1.0

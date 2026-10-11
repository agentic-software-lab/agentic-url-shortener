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


def test_parallel_branches_synchronize_before_approval():
    from threading import Barrier
    barrier = Barrier(2)
    def branch(name):
        def run(context):
            barrier.wait(timeout=3)
            context.artifacts[name] = 'complete'
            context.decisions.append(name)
        return run
    def join(context):
        assert context.artifacts == {'architecture': 'complete', 'security': 'complete'}
    engine = WorkflowEngine([Node('architecture', branch('architecture')), Node('security', branch('security')),
        Node('implementation', join, {'architecture', 'security'}, requires_human_approval=True)])
    context = WorkflowContext('parallel')
    engine.execute(context)
    assert engine.statuses() == {'architecture':'succeeded', 'security':'succeeded', 'implementation':'waiting_approval'}
    assert set(context.decisions) == {'architecture', 'security'}
    engine.approve('implementation', context)
    engine.execute(context)
    assert engine.nodes['implementation'].status == NodeStatus.SUCCEEDED


def test_failed_parallel_branch_blocks_join_and_discards_partial_artifacts():
    def failing(context):
        context.artifacts['partial'] = True
        raise RuntimeError('failure')
    def healthy(context): context.artifacts['healthy'] = True
    def join(context): raise AssertionError('Must not run')
    engine = WorkflowEngine([Node('bad', failing, max_retries=1), Node('good', healthy), Node('join', join, {'bad', 'good'})])
    context = WorkflowContext('failure')
    engine.execute(context)
    assert engine.statuses() == {'bad':'failed', 'good':'succeeded', 'join':'blocked'}
    assert context.artifacts == {'healthy':True}
    assert context.metrics['retry_count'] == 1


def test_conflicting_parallel_artifacts_block_join():
    def write(value):
        def run(context): context.artifacts['shared'] = value
        return run
    engine = WorkflowEngine([Node('a', write(1)), Node('b', write(2), max_retries=0), Node('join', write(3), {'a', 'b'})])
    context = WorkflowContext('conflict')
    engine.execute(context)
    assert engine.statuses() == {'a':'succeeded', 'b':'failed', 'join':'blocked'}
    assert context.artifacts['shared'] == 1

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


def test_fallback_after_retry_budget_then_join():
    def fail(context):
        context.artifacts['partial'] = True
        raise RuntimeError('primary failed')
    def fallback(context):
        assert 'partial' not in context.artifacts
        context.artifacts['result'] = 'fallback'
    def join(context): assert context.artifacts['result'] == 'fallback'
    engine = WorkflowEngine([Node('work', fail, max_retries=1, fallback=fallback), Node('join', join, {'work'})])
    context = WorkflowContext('fallback')
    engine.execute(context)
    assert engine.nodes['work'].attempts == 2
    assert engine.statuses() == {'work':'succeeded', 'join':'succeeded'}
    assert context.metrics['fallback_count'] == 1
    assert 'fallback_succeeded:work' in context.audit_log


def test_rollback_cleans_partial_side_effect_once(tmp_path):
    candidate = tmp_path / 'candidate'
    def fail(context):
        candidate.write_text('partial')
        raise RuntimeError('failed')
    def rollback(context): candidate.unlink()
    engine = WorkflowEngine([Node('work', fail, max_retries=0, rollback=rollback),
        Node('release', lambda context: None, {'work'}, requires_human_approval=True)])
    context = WorkflowContext('rollback')
    engine.execute(context)
    engine.execute(context)
    assert not candidate.exists()
    assert engine.statuses() == {'work':'failed', 'release':'blocked'}
    assert context.metrics['rollback_count'] == 1
    assert context.audit_log.count('rollback_succeeded:work') == 1


def test_failed_fallback_and_rollback_safe_stop():
    def fail(context): raise RuntimeError('failed')
    engine = WorkflowEngine([Node('work', fail, max_retries=0, fallback=fail, rollback=fail),
        Node('release', lambda context: None, {'work'})])
    context = WorkflowContext('failure')
    engine.execute(context)
    assert engine.statuses() == {'work':'failed', 'release':'blocked'}
    assert 'fallback_failed:work:RuntimeError' in context.audit_log
    assert 'rollback_failed:work:RuntimeError' in context.audit_log
    assert context.metrics['fallback_count'] == context.metrics['rollback_count'] == 1


def test_latency_includes_approval_wait_and_freezes(monkeypatch):
    clock = {'now':0.0}
    monkeypatch.setattr('orchestrator.engine.perf_counter', lambda: clock['now'])
    engine = WorkflowEngine([Node('work',lambda context: None,requires_human_approval=True)])
    context = WorkflowContext('timing')
    engine.execute(context)
    clock['now'] = 10.0
    engine.approve('work',context)
    engine.execute(context)
    assert context.metrics['end_to_end_latency_ms'] == 10000
    assert context.metrics['active_execution_ms'] == 0
    clock['now'] = 20.0
    engine.execute(context)
    assert context.metrics['end_to_end_latency_ms'] == 10000


def test_mttr_records_recovered_nodes_only(monkeypatch):
    clock = {'now':0.0}
    monkeypatch.setattr('orchestrator.engine.perf_counter', lambda: clock['now'])
    attempts = {'count':0}
    def work(context):
        attempts['count'] += 1
        if attempts['count'] == 1: raise RuntimeError('transient')
        clock['now'] = 2.0
    context = WorkflowContext('recovery timing')
    WorkflowEngine([Node('work',work,max_retries=1)]).execute(context)
    assert context.metrics['mttr_ms'] == 2000
    assert context.metrics['recovered_node_count'] == 1
    assert context.metrics['workflow_succeeded'] == 1
    clean = WorkflowContext('no failures')
    WorkflowEngine([Node('clean',lambda context: None)]).execute(clean)
    assert 'mttr_ms' not in clean.metrics

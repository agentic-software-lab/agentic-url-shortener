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


def test_requirements_produce_different_executable_plans():
    from scenarios.greenfield import build_engine
    graphs = []
    for scope in ['with analytics', 'without analytics']:
        engine = build_engine()
        context = WorkflowContext('Build URL shortener ' + scope)
        engine.execute(context)
        graphs.append({task['id']: task for task in engine.plan()})
        assert all(t['output'] for t in engine.plan())
        assert graphs[-1]['implementation']['status'] == 'waiting_approval'
    assert 'analytics' in graphs[0] and 'analytics' not in graphs[1]
    assert 'analytics' in graphs[0]['testing']['dependencies']
    assert 'analytics' not in graphs[1]['testing']['dependencies']


def test_security_replan_preserves_completed_tasks_and_release_gate():
    from scenarios.greenfield import build_engine
    engine = build_engine()
    context = WorkflowContext('Build URL shortener with analytics and abuse protection')
    engine.execute(context)
    assert context.revision == 2
    assert engine.nodes['testing'].dependencies == {'implementation', 'redirect_guard', 'analytics'}
    assert context.history[0]['added'] == ['redirect_guard']
    assert context.history[0]['modified'] == ['testing']
    for name in ['requirements', 'architecture', 'security']:
        assert name in context.history[0]['preserved']
        assert engine.nodes[name].attempts == 1
    assert engine.nodes['implementation'].status == NodeStatus.WAITING_APPROVAL
    engine.approve('implementation', context)
    engine.execute(context)
    assert engine.nodes['redirect_guard'].status == NodeStatus.SUCCEEDED
    assert context.artifacts['validation']['exit_code'] == 0
    assert engine.nodes['release'].status == NodeStatus.WAITING_APPROVAL
    engine.approve('release', context)
    engine.execute(context)
    assert context.metrics['workflow_succeeded'] == 1
    assert all(engine.nodes[n].attempts == 1 for n in ['requirements', 'architecture', 'security'])


def test_invalid_replans_are_atomic_and_safe_stop():
    from orchestrator.engine import ReplanRequest
    for kind in ['cycle', 'missing', 'completed', 'gate', 'duplicate', 'budget']:
        engine = WorkflowEngine([Node('source', lambda c: None),
            Node('work', lambda c: None, {'source'}, requires_human_approval=True)],
            max_replans=0 if kind == 'budget' else 4)
        context = WorkflowContext('test')
        engine.execute(context)
        old = engine.nodes['work']
        if kind == 'cycle':
            request = ReplanRequest('source', kind, [Node('extra', lambda c: None, {'work'})],
                [Node('work', lambda c: None, {'extra'}, requires_human_approval=True)])
        elif kind == 'missing':
            request = ReplanRequest('source', kind, [Node('extra', lambda c: None, {'absent'})])
        elif kind == 'completed':
            request = ReplanRequest('source', kind, modify_tasks=[Node('source', lambda c: None)])
        elif kind == 'gate':
            request = ReplanRequest('source', kind, modify_tasks=[Node('work', lambda c: None, {'source'})])
        elif kind == 'duplicate':
            request = ReplanRequest('source', kind, [Node('work', lambda c: None, {'source'})])
        else:
            request = ReplanRequest('source', kind, [Node('extra', lambda c: None, {'source'})])
        assert not engine.apply_replan(request, context)
        assert engine.nodes['work'] is old
        assert 'extra' not in engine.nodes
        engine.execute(context)
        assert engine.nodes['work'].attempts == 0
        assert engine.nodes['source'].attempts == 1
        assert context.revision == 1
        assert 'safe_stop:replan' in context.audit_log
        assert context.metrics['workflow_succeeded'] == 0


def test_validation_agent_can_replan_after_success_without_rerunning():
    from orchestrator.engine import ReplanRequest
    def validate(context):
        return ReplanRequest('validation', 'Add final evidence review',
            [Node('evidence', lambda c: c.artifacts.update({'evidence': True}), {'validation'})],
            [Node('release', lambda c: None, {'evidence'}, requires_human_approval=True)])
    engine = WorkflowEngine([Node('validation', validate),
        Node('release', lambda c: None, {'validation'}, requires_human_approval=True)])
    context = WorkflowContext('test')
    engine.execute(context)
    assert engine.nodes['validation'].attempts == 1
    assert context.artifacts['evidence'] is True
    assert engine.statuses()['release'] == 'waiting_approval'
    assert context.history[0]['source'] == 'validation'


def test_agent_invalid_replan_blocks_all_future_execution():
    from orchestrator.engine import ReplanRequest
    def architecture(context):
        return ReplanRequest('architecture', 'Invalid dependency',
                             [Node('new', lambda c: None, {'missing'})])
    engine = WorkflowEngine([Node('architecture', architecture),
        Node('implementation', lambda c: None, {'architecture'})])
    context = WorkflowContext('test')
    engine.execute(context)
    engine.execute(context)
    assert engine.safe_stopped
    assert engine.nodes['implementation'].attempts == 0
    assert engine.nodes['architecture'].attempts == 1
    assert 'new' not in engine.nodes


def test_replanning_restores_approval_for_changed_previously_approved_task():
    from orchestrator.engine import ReplanRequest
    engine = WorkflowEngine([Node('source', lambda c: None),
        Node('work', lambda c: None, {'source'}, requires_human_approval=True)])
    context = WorkflowContext('test')
    engine.execute(context)
    engine.approve('work', context)
    request = ReplanRequest('source', 'Revise work acceptance', modify_tasks=[
        Node('work', lambda c: None, {'source'}, output='Revised output')])
    assert engine.apply_replan(request, context)
    engine.execute(context)
    assert engine.nodes['work'].status == NodeStatus.WAITING_APPROVAL
    assert engine.nodes['work'].attempts == 0

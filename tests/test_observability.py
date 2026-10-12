from datetime import datetime
from threading import Barrier

from orchestrator.engine import Node, NodeStatus, ReplanRequest, WorkflowContext, WorkflowEngine
from orchestrator.observability import artifact_digest


def assert_trace_consistent(context):
    events = context.audit_events
    assert [e['sequence'] for e in events] == list(range(1, len(events) + 1))
    assert [e['message'] for e in events] == context.audit_log
    for event in events:
        assert datetime.fromisoformat(event['timestamp']).utcoffset().total_seconds() == 0
        assert event['revision'] >= 1
    by_sequence = {e['sequence']: e for e in events}
    for run in context.task_runs:
        start = by_sequence[run['start_event_sequence']]
        end = by_sequence[run['end_event_sequence']]
        assert start['event_type'] == 'start'
        assert start['task_id'] == end['task_id'] == run['task_id']
        assert start['attempt'] == end['attempt'] == run['attempt']
        assert end['event_type'] == run['outcome']
        assert run['start_event_sequence'] < run['end_event_sequence']


def test_parallel_trace_preserves_task_sources_and_input_lineage():
    barrier = Barrier(2)
    def branch(name):
        def run(context):
            barrier.wait(timeout=3)
            context.record_event('review_note:ready', details={'branch': name})
            context.artifacts[name] = {'approved': True}
            context.decisions.append('Reviewed ' + name)
        return run
    def join(context):
        context.artifacts['candidate'] = 'ready'
    engine = WorkflowEngine([Node('architecture', branch('architecture')),
        Node('security', branch('security')),
        Node('implementation', join, {'architecture', 'security'}, requires_human_approval=True)])
    context = WorkflowContext('test')
    engine.execute(context)
    engine.approve('implementation', context)
    engine.execute(context)
    assert_trace_consistent(context)
    notes = [e for e in context.audit_events if e['event_type'] == 'review_note']
    assert {e['task_id'] for e in notes} == {'architecture', 'security'}
    assert all(e['attempt'] == 1 for e in notes)
    assert len(context.task_runs) == 3
    joined = context.task_runs[-1]
    assert joined['available_inputs']['architecture']['producer']['task_id'] == 'architecture'
    assert joined['available_inputs']['security']['producer']['task_id'] == 'security'
    assert context.artifact_lineage['candidate']['digest'] == artifact_digest('ready')
    approvals = [e for e in context.audit_events if e['event_type'] == 'human_approved']
    assert approvals[0]['actor'] == 'human'
    assert approvals[0]['task_id'] == 'implementation'
    assert any(r['decisions'] == ['Reviewed architecture'] for r in context.task_runs)


def test_failed_retry_and_fallback_trace_only_committed_outputs():
    def fail(context):
        context.artifacts['discarded'] = 'partial'
        context.decisions.append('Discarded decision')
        context.record_event('diagnostic:primary failed')
        raise RuntimeError('transient')
    def fallback(context):
        assert 'discarded' not in context.artifacts
        context.artifacts['result'] = 'fallback'
        context.decisions.append('Fallback decision')
    engine = WorkflowEngine([Node('work', fail, max_retries=1, fallback=fallback)])
    context = WorkflowContext('test')
    engine.execute(context)
    assert_trace_consistent(context)
    assert [r['outcome'] for r in context.task_runs] == ['failure', 'success']
    assert context.task_runs[0]['outputs'] == {}
    assert context.task_runs[0]['decisions'] == []
    assert context.task_runs[1]['decisions'] == ['Fallback decision']
    assert context.task_runs[1]['fallback_used']
    assert set(context.artifact_lineage) == {'result'}
    assert all(e['task_id'] == 'work' for e in context.audit_events)


def test_conflict_trace_does_not_claim_failed_worker_output():
    def write(value):
        def run(context):
            context.artifacts['shared'] = value
        return run
    engine = WorkflowEngine([Node('a', write(1)), Node('b', write(2), max_retries=0)])
    context = WorkflowContext('test')
    engine.execute(context)
    assert_trace_consistent(context)
    assert context.artifact_lineage['shared']['task_id'] == 'a'
    assert context.task_runs[-1]['outcome'] == 'failure'
    assert context.task_runs[-1]['outputs'] == {}


def test_rollback_callback_diagnostics_are_traced_without_artifact_commit():
    def fail(context):
        raise RuntimeError('broken')
    def rollback(context):
        context.record_event('compensation_note:cleaned')
        context.artifacts['compensation_only'] = True
    engine = WorkflowEngine([Node('work', fail, max_retries=0, rollback=rollback)])
    context = WorkflowContext('test')
    engine.execute(context)
    assert_trace_consistent(context)
    assert 'compensation_only' not in context.artifact_lineage
    event = next(e for e in context.audit_events if e['event_type'] == 'compensation_note')
    assert event['task_id'] == 'work' and event['attempt'] == 1
    outcome = next(e for e in context.audit_events if e['event_type'] == 'rollback_succeeded')
    assert event['sequence'] < outcome['sequence']


def test_incremental_replan_preserves_original_artifact_provenance():
    def review(context):
        context.artifacts['review'] = 'accepted'
        return ReplanRequest('review', 'Add evidence', [Node('evidence',
            lambda c: c.artifacts.update({'evidence': 'verified'}), {'review'})],
            [Node('release', lambda c: None, {'evidence'}, requires_human_approval=True)])
    engine = WorkflowEngine([Node('review', review),
        Node('release', lambda c: None, {'review'}, requires_human_approval=True)])
    context = WorkflowContext('test')
    engine.execute(context)
    assert_trace_consistent(context)
    assert context.artifact_lineage['review']['revision'] == 1
    assert context.artifact_lineage['evidence']['revision'] == 2
    assert [r['task_id'] for r in context.task_runs] == ['review', 'evidence']
    event = next(e for e in context.audit_events if e['event_type'] == 'replan_completed')
    assert event['details']['reason'] == 'Add evidence'
    assert event['details']['preserved'] == ['review']
    assert event['details']['added'] == ['evidence']
    assert event['revision'] == 2


def test_legacy_agent_audit_append_remains_compatible():
    def legacy(context):
        context.audit_log.append('legacy:note')
    context = WorkflowContext('test')
    WorkflowEngine([Node('legacy', legacy)]).execute(context)
    assert_trace_consistent(context)
    event = next(e for e in context.audit_events if e['event_type'] == 'legacy')
    assert event['task_id'] == 'legacy'


def test_artifact_digest_is_stable_and_optional_for_non_json_artifacts():
    assert artifact_digest({'a': 1, 'b': 2}) == artifact_digest({'b': 2, 'a': 1})
    assert artifact_digest({'a': 1}) != artifact_digest({'a': 2})
    assert artifact_digest(object()) is None

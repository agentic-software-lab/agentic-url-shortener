"""Demonstrate bounded fallback and compensation with disposable files."""
from pathlib import Path
from tempfile import TemporaryDirectory
from orchestrator.engine import Node, WorkflowContext, WorkflowEngine


def run():
    def unavailable(context):
        raise RuntimeError('Primary adapter unavailable')
    def fallback(context):
        context.artifacts['plan'] = 'Approved deterministic fallback plan'
    context = WorkflowContext('Demonstrate fallback')
    engine = WorkflowEngine([Node('planning', unavailable, max_retries=1, fallback=fallback)])
    engine.execute(context)
    print('Fallback:', engine.statuses(), context.artifacts, context.metrics)
    print('Audit:', context.audit_log)

    with TemporaryDirectory(prefix='agentic-recovery-') as directory:
        candidate = Path(directory) / 'candidate.txt'
        def partial_write(context):
            candidate.write_text('incomplete candidate')
            raise RuntimeError('Candidate generation failed')
        def compensate(context):
            candidate.unlink(missing_ok=True)
        context = WorkflowContext('Demonstrate rollback')
        engine = WorkflowEngine([
            Node('implementation', partial_write, max_retries=0, rollback=compensate),
            Node('release', lambda context: None, {'implementation'}, requires_human_approval=True),
        ])
        engine.execute(context)
        assert not candidate.exists()
        print('Rollback:', engine.statuses(), context.metrics)
        print('Audit:', context.audit_log)


if __name__ == '__main__':
    run()

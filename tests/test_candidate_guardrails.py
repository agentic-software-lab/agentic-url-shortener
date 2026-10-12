from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from agents.candidate import seal_candidate, validate_candidate, verify_candidate, release_guard
from agents.generation import implementation_agent
from orchestrator.engine import Node, WorkflowContext, WorkflowEngine


def candidate(tmp_path):
    (tmp_path / 'main.py').write_text('VALUE = 1\n')
    (tmp_path / 'test_generated.py').write_text('from main import VALUE\ndef test_value(): assert VALUE == 1\n')
    context = WorkflowContext('test')
    context.artifacts['workspace'] = str(tmp_path)
    seal_candidate(context, ['main.py', 'test_generated.py'])
    return context


@pytest.mark.parametrize('change', ['modified', 'missing', 'extra_test', 'config', 'conftest', 'symlink'])
def test_changed_candidates_block_execution(tmp_path, monkeypatch, change):
    context = candidate(tmp_path)
    if change == 'modified':
        (tmp_path / 'main.py').write_text('VALUE = 2\n')
    elif change == 'missing':
        (tmp_path / 'test_generated.py').unlink()
    elif change == 'extra_test':
        (tmp_path / 'test_unreviewed.py').write_text('raise RuntimeError("unreviewed")')
    elif change == 'config':
        (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = --collect-only')
    elif change == 'conftest':
        (tmp_path / 'conftest.py').write_text('raise RuntimeError("unreviewed")')
    else:
        (tmp_path / 'test_generated.py').unlink()
        (tmp_path / 'test_generated.py').symlink_to(tmp_path / 'main.py')
    def unexpected(*args, **kwargs):
        raise AssertionError('Rejected candidate must not execute')
    monkeypatch.setattr('agents.candidate.subprocess.run', unexpected)
    with pytest.raises(ValueError):
        validate_candidate(context)
    assert 'validation' not in context.artifacts
    assert any(e['event_type'] == 'policy_rejected' for e in context.audit_events)


def test_runner_disables_inherited_plugins_options_and_removes_cached_bytecode(tmp_path, monkeypatch):
    context = candidate(tmp_path)
    cache = tmp_path / '__pycache__'
    cache.mkdir()
    (cache / 'main.pyc').write_bytes(b'untrusted bytecode')
    for key in ['PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTHONPATH', 'PYTHONHOME']:
        monkeypatch.setenv(key, 'unreviewed_value')
    observed = {}
    def runner(command, **kwargs):
        observed.update({'command': command, **kwargs})
        assert not cache.exists()
        return SimpleNamespace(returncode=0, stdout='passed', stderr='')
    monkeypatch.setattr('agents.candidate.subprocess.run', runner)
    validate_candidate(context)
    assert observed['env']['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
    assert not any(key in observed['env'] for key in ['PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTHONPATH', 'PYTHONHOME'])
    assert observed['command'][-1] == 'test_generated.py'
    assert '-c' in observed['command'] and '--confcutdir' in observed['command']
    assert observed['timeout'] == 60
    release_guard(context)


def test_post_test_source_change_rejects_validation(tmp_path, monkeypatch):
    context = candidate(tmp_path)
    def runner(*args, **kwargs):
        (tmp_path / 'main.py').write_text('VALUE = 2\n')
        return SimpleNamespace(returncode=0, stdout='passed', stderr='')
    monkeypatch.setattr('agents.candidate.subprocess.run', runner)
    with pytest.raises(ValueError, match='integrity mismatch'):
        validate_candidate(context)
    assert 'validation' not in context.artifacts
    assert context.audit_events[-1]['details']['guard'] == 'post_validation_integrity'


def test_release_rechecks_candidate_and_requires_matching_successful_validation(tmp_path, monkeypatch):
    context = candidate(tmp_path)
    with pytest.raises(ValueError, match='successful validation'):
        release_guard(context)
    monkeypatch.setattr('agents.candidate.subprocess.run', lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout='passed', stderr=''))
    validate_candidate(context)
    release_guard(context)
    (tmp_path / 'main.py').write_text('VALUE = 2\n')
    with pytest.raises(ValueError, match='integrity mismatch'):
        release_guard(context)
    assert context.audit_events[-1]['event_type'] == 'release_rejected'


def test_validation_timeout_blocks_release_and_is_audited(tmp_path, monkeypatch):
    context = candidate(tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)
    monkeypatch.setattr('agents.candidate.subprocess.run', timeout)
    engine = WorkflowEngine([Node('testing', validate_candidate, max_retries=0),
        Node('release', release_guard, {'testing'}, requires_human_approval=True)])
    engine.execute(context)
    assert engine.statuses() == {'testing': 'failed', 'release': 'blocked'}
    assert any(e['event_type'] == 'validation_timeout' for e in context.audit_events)
    assert 'validation' not in context.artifacts


def test_generated_manifest_matches_sources_and_documentation_can_be_added():
    context = WorkflowContext('Build URL shortener')
    implementation_agent(context)
    workspace = Path(context.artifacts['workspace'])
    (workspace / 'README.md').write_text('Candidate documentation')
    manifest = verify_candidate(context)
    assert set(manifest['files']) == {'main.py', 'test_generated.py'}
    assert manifest['test_files'] == ['test_generated.py']

"""Integrity checks around trusted candidate adapters; not a process sandbox."""
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import sys

from agents.policy import validate_sources

CACHE_DIRS = {'__pycache__', '.pytest_cache'}


def _inventory(workspace):
    root = Path(workspace)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Candidate workspace must be a real directory')
    files = {}
    for path in sorted(root.rglob('*')):
        # Reject links even inside cache directories before any cleanup.
        if path.is_symlink():
            raise ValueError('Candidate symlink is not permitted: ' + str(path.relative_to(root)))
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in CACHE_DIRS for part in relative.parts):
            continue
        # The documentation agent may write this concurrently with validation.
        if relative.as_posix() == 'README.md':
            continue
        files[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
    return files


def seal_candidate(context, policy_files):
    """Called only by the trusted generator after writing its complete candidate."""
    workspace = Path(context.artifacts['workspace'])
    inventory = _inventory(workspace)
    if not inventory or not set(policy_files) <= inventory.keys():
        raise ValueError('Candidate is missing required policy files')
    context.artifacts['candidate_manifest'] = {
        'files': inventory, 'policy_files': list(policy_files),
        'test_files': sorted(name for name in inventory if Path(name).name.startswith('test_') and name.endswith('.py')),
    }


def verify_candidate(context):
    manifest = context.artifacts.get('candidate_manifest')
    if not manifest:
        raise ValueError('Candidate manifest is missing; regenerate before validation')
    actual = _inventory(context.artifacts['workspace'])
    expected = manifest['files']
    if actual != expected:
        added = sorted(actual.keys() - expected.keys())
        removed = sorted(expected.keys() - actual.keys())
        modified = sorted(name for name in actual.keys() & expected.keys() if actual[name] != expected[name])
        raise ValueError(f'Candidate integrity mismatch: added={added}, removed={removed}, modified={modified}')
    return manifest


def validate_candidate(context):
    workspace = Path(context.artifacts['workspace'])
    try:
        manifest = verify_candidate(context)
        report = validate_sources({name: (workspace / name).read_text()
                                   for name in manifest['policy_files']})
        # Cached bytecode must not replace the sealed Python sources.
        for path in sorted(workspace.rglob('*'), reverse=True):
            if path.is_dir() and path.name in CACHE_DIRS:
                shutil.rmtree(path)
        if not manifest['test_files']:
            raise ValueError('Candidate has no approved test files')
    except (ValueError, SyntaxError, OSError) as exc:
        context.record_event('policy_rejected:' + str(exc),
                             details={'reason': str(exc), 'guard': 'candidate_integrity_and_sources'})
        raise
    context.artifacts['policy_validation'] = {**report, 'candidate_integrity': 'passed'}
    env = dict(os.environ)
    for key in ['PYTEST_ADDOPTS', 'PYTEST_PLUGINS', 'PYTHONPATH', 'PYTHONHOME']:
        env.pop(key, None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    command = [sys.executable, '-m', 'pytest', '-q', '-c', os.devnull,
               '--confcutdir', str(workspace), *manifest['test_files']]
    try:
        result = subprocess.run(command, cwd=str(workspace), env=env,
                                capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        context.record_event('validation_timeout:candidate', details={'timeout_seconds': 60})
        raise RuntimeError('Candidate validation timed out') from None
    # Pytest may write caches, but may not change the sealed source or add files.
    try:
        verify_candidate(context)
    except (ValueError, OSError) as exc:
        context.record_event('policy_rejected:' + str(exc),
                             details={'reason': str(exc), 'guard': 'post_validation_integrity'})
        raise
    context.artifacts['validation'] = {
        'command': command, 'exit_code': result.returncode,
        'output': (result.stdout + result.stderr)[-12000:],
        'validated_manifest': manifest['files'].copy(),
        'plugin_autoload': False,
    }
    if result.returncode:
        raise RuntimeError('Candidate failed tests; release blocked')
    context.record_event('candidate_validated:integrity_and_tests',
                         details={'file_count': len(manifest['files']), 'test_files': manifest['test_files']})


def release_guard(context):
    try:
        manifest = verify_candidate(context)
    except (ValueError, OSError) as exc:
        context.record_event('release_rejected:' + str(exc), details={'reason': str(exc)})
        raise
    validation = context.artifacts.get('validation', {})
    policy = context.artifacts.get('policy_validation', {})
    if (validation.get('exit_code') != 0 or policy.get('status') != 'passed'
            or validation.get('validated_manifest') != manifest['files']):
        context.record_event('release_rejected:missing_matching_validation')
        raise ValueError('Release requires successful validation of this exact candidate')
    context.record_event('release_integrity_verified:candidate',
                         details={'file_count': len(manifest['files'])})

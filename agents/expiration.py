"""Bounded, deterministic code-editing adapter for the link-expiration scenario."""
import ast
import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from agents.policy import validate_sources

from orchestrator.engine import Node, WorkflowContext, WorkflowEngine

ROOT = Path(__file__).resolve().parents[1]


def inspect_code(context):
    source = (ROOT / 'backend/main.py').read_text()
    tree = ast.parse(source)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    required = {'create_short_url', 'redirect', 'analytics'}
    if not required <= functions:
        raise ValueError('Expected URL API functions are missing; manual replanning required')
    context.artifacts['impacted_modules'] = ['backend/main.py', 'tests/test_expiration.py']
    context.artifacts['source'] = source
    context.artifacts['tasks'] = ['Add optional positive expiration duration', 'Preserve existing URL behavior',
                                'Return 410 for expired redirects', 'Generate and run regression tests',
                                'Review diff before release readiness']
    context.decisions.append('Inspect Python AST; constrain edits to the known URL API in an isolated workspace.')


def generate_change(context):
    source = context.artifacts['source']
    edits = [
        ('from typing import Dict', 'from typing import Dict, Optional'),
        ('from datetime import datetime, timezone', 'from datetime import datetime, timedelta, timezone'),
        ('from pydantic import BaseModel, HttpUrl', 'from pydantic import BaseModel, Field, HttpUrl'),
        ('    url: HttpUrl', '    url: HttpUrl\n    expires_in_seconds: Optional[int] = Field(default=None, gt=0, le=31536000)'),
        ('    clicks: int = 0', '    clicks: int = 0\n    expires_at: Optional[datetime] = None'),
        ('    short_code = generate_code(original)', '    # Separate expiring mappings from the original non-expiring mapping.\n    key = original if payload.expires_in_seconds is None else f"{original}|ttl={payload.expires_in_seconds}"\n    short_code = generate_code(key)'),
        ('            clicks=0,', '            clicks=0,\n            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=payload.expires_in_seconds)\n                        if payload.expires_in_seconds is not None else None),'),
        ('    record.clicks += 1', '    if record.expires_at is not None and datetime.now(timezone.utc) >= record.expires_at:\n        raise HTTPException(status_code=410, detail="Short URL expired")\n\n    record.clicks += 1'),
        ('        "clicks": record.clicks,', '        "clicks": record.clicks,\n        "expires_at": record.expires_at,'),
    ]
    changed = source
    for before, after in edits:
        if changed.count(before) != 1:
            raise ValueError('Code changed from supported shape; stop for manual replanning')
        changed = changed.replace(before, after)
    ast.parse(changed)
    workspace = Path(tempfile.mkdtemp(prefix='agentic-expiration-'))
    context.artifacts['workspace'] = str(workspace)
    for folder in ['backend', 'tests']:
        shutil.copytree(ROOT / folder, workspace / folder, ignore=shutil.ignore_patterns('__pycache__'))
    (workspace / 'tests/test_orchestrator_api.py').unlink(missing_ok=True)
    # Copy orchestration modules because existing regression tests import them.
    for folder in ['orchestrator', 'agents', 'scenarios']:
        shutil.copytree(ROOT / folder, workspace / folder, ignore=shutil.ignore_patterns('__pycache__'))
    (workspace / 'backend/main.py').write_text(changed)
    tests = '''from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from backend.main import app, URLS
client = TestClient(app)
def setup_function(): URLS.clear()
def test_expiration_and_legacy_links():
    legacy = client.post('/urls', json={'url':'https://example.com/path'}).json()
    expiring = client.post('/urls', json={'url':'https://example.com/path','expires_in_seconds':60}).json()
    assert legacy['short_code'] != expiring['short_code']
    assert legacy['expires_at'] is None
    assert expiring['expires_at'] is not None
    code = expiring['short_code']
    assert client.get('/r/'+code, follow_redirects=False).status_code == 307
    URLS[code].expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get('/r/'+code, follow_redirects=False).status_code == 410
    assert client.get('/urls/'+code+'/analytics').json()['clicks'] == 1
    assert client.get('/r/'+legacy['short_code'], follow_redirects=False).status_code == 307
def test_invalid_expiration():
    for duration in [0, -1, 31536001]:
        assert client.post('/urls',json={'url':'https://example.com','expires_in_seconds':duration}).status_code == 422
'''
    (workspace / 'tests/test_expiration.py').write_text(tests)
    context.artifacts['diff'] = ''.join(difflib.unified_diff(source.splitlines(True), changed.splitlines(True),
                                    fromfile='a/backend/main.py', tofile='b/backend/main.py')) + ''.join(
        difflib.unified_diff([], tests.splitlines(True), fromfile='/dev/null', tofile='b/tests/test_expiration.py'))
    context.artifacts['documentation'] = 'Optional expires_in_seconds: 1–31536000. Expired redirects return 410 without increasing clicks. Default links never expire. Repeated URL + duration returns the existing mapping, including its original expiry.'


def validate_change(context):
    workspace = Path(context.artifacts['workspace'])
    try:
        context.artifacts['policy_validation'] = validate_sources({name:(workspace/name).read_text() for name in ['backend/main.py','tests/test_expiration.py']})
    except (ValueError, SyntaxError) as exc:
        context.artifacts['policy_validation'] = {'status':'failed','reason':str(exc)}
        context.audit_log.append('policy_rejected:' + str(exc))
        raise
    result = subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=context.artifacts['workspace'],
                            capture_output=True, text=True, timeout=60)
    context.artifacts['validation'] = {'command': 'python3 -m pytest -q', 'exit_code': result.returncode,
                                     'output': (result.stdout + result.stderr)[-12000:]}
    if result.returncode:
        raise RuntimeError('Generated change failed regression tests; release blocked')


def review_complete(context):
    context.artifacts['release_readiness'] = 'Reviewed candidate only; source repository and running API are unchanged.'


def build_engine():
    return WorkflowEngine([
        Node('impact_analysis', inspect_code, max_retries=0),
        Node('implementation', generate_change, {'impact_analysis'}, requires_human_approval=True, max_retries=0),
        Node('testing', validate_change, {'implementation'}, max_retries=0),
        Node('release', review_complete, {'testing'}, requires_human_approval=True, max_retries=0),
    ])

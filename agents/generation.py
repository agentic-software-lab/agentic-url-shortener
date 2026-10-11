"""Deterministic scaffold generator; no model API or arbitrary code execution inputs."""
import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from agents.policy import validate_sources

SOURCE = '''from datetime import datetime, timezone
from hashlib import sha256
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
app = FastAPI(title="Generated URL Shortener")
URLS = {}
class Request(BaseModel):
    url: HttpUrl
@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/urls')
def create(payload: Request):
    url = str(payload.url)
    code = sha256(url.encode()).hexdigest()[:8]
    if code not in URLS:
        URLS[code] = {'short_code':code, 'original_url':url, 'created_at':datetime.now(timezone.utc).isoformat(), 'clicks':0}
    return URLS[code]
@app.get('/r/{code}')
def redirect(code: str):
    if code not in URLS: raise HTTPException(404, 'Short URL not found')
    URLS[code]['clicks'] += 1
    return RedirectResponse(URLS[code]['original_url'], status_code=307)
'''
ANALYTICS = '''@app.get('/urls/{code}/analytics')
def analytics(code: str):
    if code not in URLS: raise HTTPException(404, 'Short URL not found')
    return URLS[code]
'''
TESTS = '''from fastapi.testclient import TestClient
from main import app, URLS
client = TestClient(app)
def setup_function(): URLS.clear()
def test_create_redirect_and_duplicate():
    payload = {'url':'https://example.com/path'}
    created = client.post('/urls', json=payload)
    assert created.status_code == 200
    code = created.json()['short_code']
    assert client.post('/urls',json=payload).json()['short_code'] == code
    result = client.get('/r/'+code, follow_redirects=False)
    assert result.status_code == 307
    assert result.headers['location'] == payload['url']
    assert URLS[code]['clicks'] == 1
def test_health_validation_and_missing():
    assert client.get('/health').json() == {'status':'ok'}
    assert client.post('/urls',json={'url':'javascript:alert(1)'}).status_code == 422
    assert client.get('/r/missing',follow_redirects=False).status_code == 404
'''


def implementation_agent(context):
    options = context.artifacts.get('requirement_plan', context.artifacts.get('clarification', {'analytics':True}))
    source = SOURCE + (ANALYTICS if options['analytics'] else '')
    tests = TESTS + ('''\ndef test_analytics():
    code = client.post('/urls',json={'url':'https://example.com/path'}).json()['short_code']
    client.get('/r/'+code,follow_redirects=False)
    assert client.get('/urls/'+code+'/analytics').json()['clicks'] == 1
    assert client.get('/urls/missing/analytics').status_code == 404
''' if options['analytics'] else '''\ndef test_analytics_excluded():
    assert client.get('/urls/missing/analytics').status_code == 404
''')
    workspace = Path(tempfile.mkdtemp(prefix='agentic-scaffold-'))
    files = {'main.py':source, 'test_generated.py':tests}
    for name, content in files.items(): (workspace/name).write_text(content)
    context.artifacts.update({'workspace':str(workspace), 'generated_files':files,
        'implementation_plan':['Create validated URL API','Preserve deterministic mappings','Validate redirects and optional analytics'],
        'diff':''.join(''.join(difflib.unified_diff([], content.splitlines(True), fromfile='/dev/null', tofile='b/'+name)) for name, content in files.items())})


def testing_agent(context):
    workspace = Path(context.artifacts['workspace'])
    try:
        context.artifacts['policy_validation'] = validate_sources({name:(workspace/name).read_text() for name in ['main.py','test_generated.py']})
    except (ValueError, SyntaxError) as exc:
        context.artifacts['policy_validation'] = {'status':'failed','reason':str(exc)}
        context.audit_log.append('policy_rejected:' + str(exc))
        raise
    result = subprocess.run([sys.executable,'-m','pytest','-q'], cwd=context.artifacts['workspace'], capture_output=True,text=True,timeout=60)
    context.artifacts['validation'] = {'command':'python3 -m pytest -q','exit_code':result.returncode,'output':(result.stdout+result.stderr)[-12000:]}
    if result.returncode: raise RuntimeError('Generated application failed validation')


def documentation_agent(context):
    options = context.artifacts.get('requirement_plan', context.artifacts.get('clarification', {'analytics':True}))
    text = '# Generated URL Shortener\n\nRun: python3 -m uvicorn main:app --port 8002\nTest: python3 -m pytest -q\n\nScope: HTTP/HTTPS URLs, deterministic mappings, HTTP 307 redirects.\nAnalytics: '+str(options['analytics'])+'\nNo expiration or custom aliases. In-memory data resets on restart.\n'
    (Path(context.artifacts['workspace'])/'README.md').write_text(text)
    context.artifacts['documentation'] = text

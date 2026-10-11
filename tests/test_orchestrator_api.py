from fastapi.testclient import TestClient
from orchestrator.api import app, workflows

client = TestClient(app)


def setup_function():
    workflows.clear()


def test_workflow_approval_lifecycle():
    response = client.post('/workflows', json={'requirement': 'Build URL analytics'})
    assert response.status_code == 201
    data = response.json()
    key = data['workflow_id']
    assert data['pending_approvals'] == ['implementation']
    assert data['nodes']['implementation'] == 'waiting_approval'
    assert client.post(f'/workflows/{key}/approvals/release').status_code == 409
    data = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert data['pending_approvals'] == ['release']
    assert client.post(f'/workflows/{key}/approvals/implementation').status_code == 409
    data = client.post(f'/workflows/{key}/approvals/release').json()
    assert data['status'] == 'succeeded'
    assert client.get(f'/workflows/{key}').json() == data
    assert len(client.get('/workflows').json()) == 1
    assert 'human_approved:release' in client.get(f'/workflows/{key}/events').json()['events']
    assert client.get(f'/workflows/{key}/metrics').json()['metrics']['success_rate'] == 1


def test_invalid_and_missing_workflows():
    assert client.post('/workflows', json={'requirement': '  '}).status_code == 422
    assert client.get('/workflows/missing').status_code == 404
    key = client.post('/workflows', json={'requirement': 'test'}).json()['workflow_id']
    assert client.post(f'/workflows/{key}/approvals/missing').status_code == 404


def test_failure_blocks_implementation_and_workflows_are_isolated():
    failed = client.post('/workflows', json={'requirement': 'Support javascript: URLs'}).json()
    good = client.post('/workflows', json={'requirement': 'Build safe URLs'}).json()
    assert failed['status'] == 'failed'
    assert failed['nodes']['implementation'] == 'blocked'
    assert failed['pending_approvals'] == []
    assert good['pending_approvals'] == ['implementation']
    assert failed['workflow_id'] != good['workflow_id']


def test_real_brownfield_change_and_validation():
    result = client.post('/workflows', json={'scenario':'brownfield_expiration','requirement':'Add link expiration'})
    assert result.status_code == 201
    key = result.json()['workflow_id']
    assert result.json()['pending_approvals'] == ['implementation']
    result = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert result['pending_approvals'] == ['release']
    assert result['artifacts']['validation']['exit_code'] == 0
    assert 'expires_at' in result['artifacts']['diff']
    assert 'Optional[int]' in result['artifacts']['diff']
    assert 'Optional[datetime]' in result['artifacts']['diff']
    assert 'int | None' not in result['artifacts']['diff']
    assert 'test_expiration.py' in result['artifacts']['diff']
    assert client.post(f'/workflows/{key}/approvals/release').json()['status'] == 'succeeded'


def test_greenfield_generates_runnable_artifacts():
    key = client.post('/workflows',json={'requirement':'Build a URL shortener'}).json()['workflow_id']
    data = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert data['pending_approvals'] == ['release']
    assert data['artifacts']['validation']['exit_code'] == 0
    assert 'main.py' in data['artifacts']['generated_files']
    assert 'test_generated.py' in data['artifacts']['generated_files']
    assert '3 passed' in data['artifacts']['validation']['output']
    assert 'Run:' in data['artifacts']['documentation']


def test_ambiguous_requires_choices_and_changes_generated_scope():
    key = client.post('/workflows',json={'scenario':'ambiguous','requirement':'Make useful short links'}).json()['workflow_id']
    assert client.post(f'/workflows/{key}/approvals/clarify').status_code == 409
    assert client.post(f'/workflows/{key}/clarification',json={'analytics':False,'accept_no_expiration_or_aliases':False}).status_code == 422
    assert client.post(f'/workflows/{key}/clarification',json={'analytics':False,'accept_no_expiration_or_aliases':True}).status_code == 200
    data = client.post(f'/workflows/{key}/approvals/clarify').json()
    assert data['pending_approvals'] == ['implementation']
    data = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert data['pending_approvals'] == ['release']
    assert data['artifacts']['validation']['exit_code'] == 0
    assert "@app.get('/urls/{code}/analytics')" not in data['artifacts']['generated_files']['main.py']
    assert data['artifacts']['assumptions']['analytics'] == 'excluded'
    assert client.post(f'/workflows/{key}/approvals/release').json()['status'] == 'succeeded'


def test_generated_validation_failure_blocks_release(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('agents.generation.subprocess.run',lambda *a, **k: SimpleNamespace(returncode=1,stdout='test failure',stderr=''))
    key = client.post('/workflows',json={'requirement':'Build URL shortener'}).json()['workflow_id']
    data = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert data['nodes']['testing'] == 'failed'
    assert data['nodes']['release'] == 'blocked'
    assert client.post(f'/workflows/{key}/approvals/release').status_code == 409


def test_replan_invalidates_candidate_and_requires_fresh_approvals():
    key = client.post('/workflows', json={'requirement':'Build URL shortener'}).json()['workflow_id']
    first = client.post(f'/workflows/{key}/approvals/implementation').json()
    old_workspace = first['artifacts']['workspace']
    revised = client.post(f'/workflows/{key}/replan', json={
        'scenario':'ambiguous', 'requirement':'Build short links with revised analytics scope'}).json()
    assert revised['revision'] == 2
    assert revised['pending_approvals'] == ['replan']
    assert 'workspace' not in revised['artifacts']
    assert revised['history'][0]['artifacts']['workspace'] == old_workspace
    assert client.post(f'/workflows/{key}/approvals/release').status_code == 409
    data = client.post(f'/workflows/{key}/approvals/replan').json()
    assert data['pending_approvals'] == ['clarify']
    client.post(f'/workflows/{key}/clarification', json={
        'analytics':False, 'accept_no_expiration_or_aliases':True})
    data = client.post(f'/workflows/{key}/approvals/clarify').json()
    assert data['pending_approvals'] == ['implementation']
    data = client.post(f'/workflows/{key}/approvals/implementation').json()
    assert data['artifacts']['workspace'] != old_workspace
    assert data['artifacts']['validation']['exit_code'] == 0
    assert "@app.get('/urls/{code}/analytics')" not in data['artifacts']['generated_files']['main.py']
    assert client.post(f'/workflows/{key}/approvals/release').json()['status'] == 'succeeded'


def test_invalid_replan_preserves_existing_workflow():
    key = client.post('/workflows', json={'requirement':'Build URLs'}).json()['workflow_id']
    assert client.post(f'/workflows/{key}/replan', json={'requirement':' '}).status_code == 422
    assert client.post(f'/workflows/{key}/replan', json={
        'scenario':'brownfield_expiration', 'requirement':'Add custom aliases'}).status_code == 422
    assert client.get(f'/workflows/{key}').json()['revision'] == 1


def test_summary_distinguishes_pending_and_reviewed_candidate():
    key = client.post('/workflows',json={'requirement':'Build short links'}).json()['workflow_id']
    report = client.get(f'/workflows/{key}/summary').json()
    assert report['review_ready'] is False
    assert report['validation'] is None
    assert report['pending_approvals'] == ['implementation']
    client.post(f'/workflows/{key}/approvals/implementation')
    report = client.get(f'/workflows/{key}/summary').json()
    assert report['validation']['exit_code'] == 0
    assert report['review_ready'] is False
    assert 'main.py' in report['artifacts']['generated_file_names']
    client.post(f'/workflows/{key}/approvals/release')
    report = client.get(f'/workflows/{key}/summary').json()
    assert report['review_ready'] is True
    assert report['approvals'] == ['implementation','release']
    assert report['policy_validation']['status'] == 'passed'
    assert report['limitations']
    assert client.get('/workflows/missing/summary').status_code == 404
    client.post(f'/workflows/{key}/replan',json={'requirement':'Build revised short links'})
    report = client.get(f'/workflows/{key}/summary').json()
    assert report['review_ready'] is False
    assert report['approvals'] == []
    assert report['prior_revision_count'] == 1


def test_requirement_drives_generated_analytics_scope():
    for wording, enabled in [('with analytics',True),('without analytics',False)]:
        key = client.post('/workflows',json={'requirement':'Build URL shortener '+wording}).json()['workflow_id']
        data = client.post(f'/workflows/{key}/approvals/implementation').json()
        assert data['artifacts']['requirement_plan']['analytics'] is enabled
        source = data['artifacts']['generated_files']['main.py']
        assert ("@app.get('/urls/{code}/analytics')" in source) is enabled
        assert data['artifacts']['validation']['exit_code'] == 0
    failed = client.post('/workflows',json={'requirement':'Build URL shortener with custom aliases'}).json()
    assert failed['status'] == 'failed'
    assert failed['nodes']['implementation'] == 'blocked'

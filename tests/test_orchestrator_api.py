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

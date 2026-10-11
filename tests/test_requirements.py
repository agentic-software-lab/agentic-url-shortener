import pytest
from agents.requirements import interpret


def test_scope_changes_tasks_and_acceptance():
    yes = interpret('Build a URL shortener with analytics')
    no = interpret('Build a URL shortener without analytics')
    assert yes['analytics'] and not no['analytics']
    assert 'analytics' in [task['id'] for task in yes['tasks']]
    assert 'analytics' not in [task['id'] for task in no['tasks']]
    assert yes['acceptance_criteria'][-1] != no['acceptance_criteria'][-1]


def test_unsupported_scope_rejected():
    for request in ['Build weather app','Build URL shortener with custom aliases','Add URL expiry','Build URL shortener with PostgreSQL database']:
        with pytest.raises(ValueError): interpret(request)
    assert interpret('Build URL shortener without custom aliases')['domain'] == 'url_shortener'

import pytest
from agents.policy import validate_sources
from orchestrator.engine import Node, WorkflowEngine


def test_graph_rejects_missing_duplicate_and_cyclic_dependencies():
    no_op = lambda context: None
    for nodes in [[Node('a', no_op, {'missing'})], [Node('a',no_op),Node('a',no_op)],
                  [Node('a',no_op,{'b'}),Node('b',no_op,{'a'})], [Node('a',no_op,max_retries=-1)]]:
        with pytest.raises(ValueError): WorkflowEngine(nodes)


def test_policy_rejects_dangerous_sources():
    for code in ['import subprocess', 'import os', 'eval("1")', 'open("file")', 'x.__class__', 'from .secret import value']:
        with pytest.raises(ValueError): validate_sources({'main.py':code})
    assert validate_sources({'main.py':'from fastapi import FastAPI\napp = FastAPI()'})['status'] == 'passed'


def test_policy_failure_blocks_test_execution(monkeypatch,tmp_path):
    from agents.generation import testing_agent
    from orchestrator.engine import WorkflowContext
    (tmp_path/'main.py').write_text('import subprocess')
    (tmp_path/'test_generated.py').write_text('')
    def unexpected(*args,**kwargs): raise AssertionError('Should never execute unapproved sources')
    monkeypatch.setattr('agents.generation.subprocess.run',unexpected)
    context = WorkflowContext('policy')
    context.artifacts['workspace'] = str(tmp_path)
    with pytest.raises(ValueError): testing_agent(context)
    assert context.artifacts['policy_validation']['status'] == 'failed'

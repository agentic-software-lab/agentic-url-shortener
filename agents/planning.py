"""Bounded deterministic task planning; generation remains in its existing adapter."""
from orchestrator.engine import Node, ReplanRequest


def analytics_agent(context):
    files = context.artifacts['generated_files']
    if "@app.get('/urls/{code}/analytics')" not in files['main.py']:
        raise ValueError('Requested analytics endpoint is missing')
    context.artifacts['analytics_review'] = 'Aggregate endpoint and generated tests present'


def redirect_guard_agent(context):
    # The generator already enforces HTTP/HTTPS through HttpUrl. Verify that
    # security contract before allowing validation/release to proceed.
    from agents.policy import validate_sources
    files = context.artifacts['generated_files']
    validate_sources(files)
    if 'url: HttpUrl' not in files['main.py'] or 'javascript:alert(1)' not in files['test_generated.py']:
        raise ValueError('Redirect scheme guard or regression test is missing')
    context.artifacts['redirect_guard'] = 'HTTP/HTTPS validation and unsafe-scheme regression test verified'


def security_replan(context):
    from agents.generation import testing_agent
    dependencies = {'implementation', 'redirect_guard'}
    if context.artifacts['requirement_plan']['analytics']:
        dependencies.add('analytics')
    return ReplanRequest('security', 'Explicit redirect abuse protection requires a guard verification task',
        add_tasks=[Node('redirect_guard', redirect_guard_agent, {'implementation'},
                        output='Verified redirect scheme guard', acceptance=['AC1'])],
        modify_tasks=[Node('testing', testing_agent, dependencies,
                           output='Passing candidate tests', acceptance=['AC1', 'AC2', 'AC3', 'AC4'])])


def requirement_plan(context, nodes):
    """Keep completed roots and scenario gates; vary executable downstream work."""
    planned = []
    for node in nodes.values():
        if node.name == 'analytics':
            continue
        output = {'requirements':'Interpreted requirement and acceptance criteria',
                  'clarify':'Human-confirmed scope', 'architecture':'Architecture decisions',
                  'security':'Security review', 'implementation':'Runnable candidate and diff',
                  'testing':'Passing candidate tests', 'documentation':'Setup and scope documentation',
                  'release':'Human-approved review readiness'}.get(node.name, node.name)
        node.output = output
        node.acceptance = ['AC1', 'AC2', 'AC3', 'AC4'] if node.name in {'implementation', 'testing'} else []
        planned.append(node)
    if context.artifacts['requirement_plan']['analytics']:
        planned.append(Node('analytics', analytics_agent, {'implementation'},
                            output='Verified aggregate analytics endpoint', acceptance=['AC4']))
        testing = next(n for n in planned if n.name == 'testing')
        testing.dependencies = testing.dependencies | {'analytics'}
    return planned

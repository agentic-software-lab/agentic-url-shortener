"""Explicit bounded interpretation; not general natural-language understanding."""
import re


def interpret(requirement):
    text = requirement.strip()
    lower = text.lower()
    if not text:
        raise ValueError('Requirement cannot be empty')
    if not re.search(r'\b(urls?|links?|redirects?|shortener)\b', lower):
        raise ValueError('Unsupported domain: this adapter builds URL shorteners only')
    if 'javascript:' in lower:
        raise ValueError('Unsafe URL scheme requested')
    unsupported = []
    # Negated, explicitly excluded capabilities do not request implementation.
    for feature, pattern in [('expiration',r'\b(expiration|expiry|expire|ttl)\b'),
                             ('custom aliases',r'\b(alias|aliases|custom slugs?)\b'),
                             ('persistent storage',r'\b(postgres\w*|database|redis|dynamodb|persistent storage)\b'),
                             ('authentication',r'\b(authentication|oauth|login)\b')]:
        for match in re.finditer(pattern, lower):
            prefix = lower[max(0,match.start()-35):match.start()]
            if not re.search(r'(?:no|without|exclude|excluding|do not add|out of scope)[\s\w-]*$', prefix):
                unsupported.append(feature)
                break
    if unsupported:
        raise ValueError('Unsupported scaffold capabilities: '+', '.join(unsupported)+'. Use the brownfield_expiration adapter for expiration changes.')
    analytics = bool(re.search(r'\b(analytics|click counts?|click tracking)\b', lower))
    if re.search(r'(?:no|without|exclude|excluding)\s+(?:click\s+)?analytics',lower):
        analytics = False
    questions = []
    if re.search(r'\b(useful|production.ready|better|improve)\b', lower):
        questions = ['Confirm aggregate click analytics scope', 'Confirm exclusion of expiration, aliases, persistent storage and authentication']
    acceptance = [
        {'id':'AC1','criterion':'Accept only HTTP/HTTPS URLs; reject invalid inputs'},
        {'id':'AC2','criterion':'Create stable short codes and redirect with HTTP 307'},
        {'id':'AC3','criterion':'Return HTTP 404 for unknown short codes'},
    ]
    if analytics:
        acceptance.append({'id':'AC4','criterion':'Expose aggregate click count and increment only on successful redirect'})
    else:
        acceptance.append({'id':'AC4','criterion':'Do not expose an analytics endpoint'})
    tasks = [
        {'id':'schema','dependencies':[],'output':'Validated request schema','acceptance':['AC1']},
        {'id':'links','dependencies':['schema'],'output':'Creation and redirect API','acceptance':['AC2','AC3']},
    ]
    if analytics:
        tasks.append({'id':'analytics','dependencies':['links'],'output':'Aggregate click analytics endpoint','acceptance':['AC4']})
    tasks.append({'id':'validation','dependencies':['analytics' if analytics else 'links'],'output':'Unit/integration tests and results','acceptance':['AC1','AC2','AC3','AC4']})
    tasks.append({'id':'documentation','dependencies':['links'],'output':'Setup, scope, assumptions and trade-offs','acceptance':[]})
    return {'domain':'url_shortener','analytics':analytics,'acceptance_criteria':acceptance,
            'tasks':tasks,'questions':questions,'constraints':['in-memory storage','HTTP 307 redirects','no deployment'],
            'normalized_requirement':'Build a URL shortener with validated HTTP/HTTPS links, stable redirects, '+('aggregate click analytics.' if analytics else 'no analytics endpoint.')}


def requirements_agent(context):
    try:
        plan = interpret(context.requirement)
    except ValueError as exc:
        context.record_event('requirement_rejected:'+str(exc))
        raise
    if plan['questions'] and 'clarification' not in context.artifacts:
        context.record_event('clarification_required:use_ambiguous_scenario')
        raise ValueError('Ambiguous scope: use the ambiguous scenario and provide clarification')
    if 'clarification' in context.artifacts:
        plan['analytics'] = context.artifacts['clarification']['analytics']
        # Rebuild plan and acceptance criteria for the explicitly chosen scope.
        confirmed = interpret('Build URL shortener '+('with analytics' if plan['analytics'] else 'without analytics'))
        plan.update({k:confirmed[k] for k in ['tasks','acceptance_criteria','normalized_requirement']})
    context.artifacts.update({'requirement_plan':plan,'normalized_requirement':plan['normalized_requirement'],
                              'acceptance_criteria':plan['acceptance_criteria'],'tasks':plan['tasks']})
    context.decisions.append('Interpreted supported capabilities and linked tasks to explicit acceptance criteria.')

"""Static checks for trusted, bounded adapters; not a security sandbox."""
import ast

ALLOWED_IMPORTS = {'datetime', 'hashlib', 'typing', 'fastapi', 'pydantic', 'main', 'backend', '__future__'}
FORBIDDEN_CALLS = {'eval', 'exec', 'compile', '__import__', 'open', 'input', 'breakpoint'}


def validate_sources(sources):
    checked = []
    for filename, source in sources.items():
        tree = ast.parse(source, filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split('.')[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or '').split('.')[0]]
                if node.level:
                    raise ValueError('Policy rejects relative imports')
            else:
                modules = []
            if any(module not in ALLOWED_IMPORTS for module in modules):
                raise ValueError(f'Policy rejects import in {filename}: {modules}')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                raise ValueError(f'Policy rejects call in {filename}: {node.func.id}')
            if isinstance(node, ast.Attribute) and node.attr.startswith('__'):
                raise ValueError(f'Policy rejects introspection in {filename}')
        checked.append(filename)
    return {'status':'passed', 'checked_files':checked, 'policy':'bounded-python-v1'}

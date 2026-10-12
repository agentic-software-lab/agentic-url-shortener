"""JSON-safe evidence helpers; timestamps are observational, not scheduling inputs."""
from datetime import datetime, timezone
from hashlib import sha256
import json


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def artifact_digest(value):
    """Fingerprint serializable artifact content without copying it into the audit."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError):
        return None
    return sha256(encoded).hexdigest()

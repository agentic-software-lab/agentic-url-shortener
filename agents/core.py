from __future__ import annotations

from urllib.parse import urlparse

from orchestrator.engine import WorkflowContext


from agents.requirements import requirements_agent


def architecture_agent(context: WorkflowContext) -> None:
    context.artifacts["architecture"] = {
        "api": "FastAPI",
        "storage": "in-memory prototype with repository boundary for future DB",
        "short_code": "deterministic SHA-256 prefix",
        "analytics": "click counter" if context.artifacts.get("requirement_plan", {}).get("analytics", True) else "excluded",
    }
    context.decisions.append("Kept infrastructure lightweight while preserving service boundaries.")


def security_agent(context: WorkflowContext) -> None:
    requirement = str(context.artifacts.get("normalized_requirement", context.requirement))
    if "javascript:" in requirement.lower():
        raise ValueError("Unsafe URL scheme requested")
    context.artifacts["security_review"] = {
        "accepted_schemes": ["http", "https"],
        "guards": ["input validation", "bounded retries", "human release approval"],
    }


def implementation_agent(context: WorkflowContext) -> None:
    context.artifacts["implementation_plan"] = [
        "POST /urls",
        "GET /r/{short_code}",
        "GET /urls/{short_code}/analytics",
        "GET /health",
    ]


def testing_agent(context: WorkflowContext) -> None:
    required = {"architecture", "implementation_plan", "security_review"}
    missing = required - context.artifacts.keys()
    if missing:
        raise RuntimeError(f"Cannot validate; missing artifacts: {sorted(missing)}")
    context.artifacts["test_strategy"] = [
        "API creation and redirect integration test",
        "analytics click count assertion",
        "404 behavior",
        "orchestrator approval and retry tests",
    ]


def documentation_agent(context: WorkflowContext) -> None:
    context.artifacts["documentation"] = {
        "sections": ["setup", "architecture", "scenarios", "testing", "risks", "limitations"]
    }


def release_agent(context: WorkflowContext) -> None:
    context.artifacts["release_readiness"] = "approved for prototype release"
    context.decisions.append("Release proceeds only after validation and explicit human approval.")

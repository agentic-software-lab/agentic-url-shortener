"""CLI demonstration of the real brownfield expiration adapter."""
from agents.expiration import build_engine
from orchestrator.engine import WorkflowContext


def run() -> None:
    context = WorkflowContext("Add optional link expiration without breaking existing redirects")
    engine = build_engine()
    engine.execute(context)
    engine.approve("implementation", context)
    engine.execute(context)
    if engine.statuses()["release"] == "waiting_approval":
        engine.approve("release", context)
        engine.execute(context)
    print("Impacted modules:", context.artifacts.get("impacted_modules"))
    print("Statuses:", engine.statuses())
    print("Workspace:", context.artifacts.get("workspace"))
    print("Validation:", context.artifacts.get("validation"))
    print("Audit log:", context.audit_log)


if __name__ == "__main__":
    run()

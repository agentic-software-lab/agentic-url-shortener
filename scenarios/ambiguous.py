from agents.core import (
    architecture_agent,
    documentation_agent,
    implementation_agent,
    release_agent,
    requirements_agent,
    security_agent,
    testing_agent,
)
from orchestrator.engine import Node, WorkflowContext, WorkflowEngine


def ambiguity_resolution_agent(context: WorkflowContext) -> None:
    original = context.requirement
    assumptions = {
        "expiration": "not enabled by default",
        "custom_aliases": "out of scope for first release",
        "analytics": "track aggregate click count only",
        "redirect_status": 307,
    }
    context.artifacts["ambiguities"] = [
        "Should links expire?",
        "Are custom aliases required?",
        "What analytics granularity is expected?",
    ]
    context.artifacts["assumptions"] = assumptions
    context.artifacts["normalized_requirement"] = (
        "Build a URL shortener with stable redirects and aggregate click analytics; "
        "do not add expiration or custom aliases in the first release."
    )
    context.decisions.append(f"Clarified ambiguous request: {original!r}")
    context.decisions.append(f"Assumptions adopted: {assumptions}")


def run() -> None:
    context = WorkflowContext("Make the short links production ready and add useful analytics.")
    engine = WorkflowEngine(
        [
            Node("requirements", requirements_agent),
            Node("clarify", ambiguity_resolution_agent, {"requirements"}, requires_human_approval=True),
            Node("architecture", architecture_agent, {"clarify"}),
            Node("security", security_agent, {"clarify"}),
            Node("implementation", implementation_agent, {"architecture", "security"}),
            Node("testing", testing_agent, {"implementation"}),
            Node("documentation", documentation_agent, {"implementation"}),
            Node("release", release_agent, {"testing", "documentation"}, requires_human_approval=True),
        ]
    )

    engine.execute(context)
    engine.approve("clarify", context)
    engine.execute(context)
    engine.approve("release", context)
    engine.execute(context)

    print("Assumptions:", context.artifacts["assumptions"])
    print("Statuses:", engine.statuses())
    print("Audit log:", context.audit_log)


if __name__ == "__main__":
    run()

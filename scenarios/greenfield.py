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
from agents.generation import implementation_agent, testing_agent, documentation_agent


def build_engine() -> WorkflowEngine:
    return WorkflowEngine(
        [
            Node("requirements", requirements_agent),
            Node("architecture", architecture_agent, {"requirements"}),
            Node("security", security_agent, {"requirements"}),
            Node(
                "implementation",
                implementation_agent,
                {"architecture", "security"},
                requires_human_approval=True,
            ),
            Node("testing", testing_agent, {"implementation"}),
            Node("documentation", documentation_agent, {"implementation"}),
            Node(
                "release",
                release_agent,
                {"testing", "documentation"},
                requires_human_approval=True,
            ),
        ]
    )


def run() -> None:
    context = WorkflowContext("Build a URL shortener with analytics and reliability controls.")
    engine = build_engine()

    engine.execute(context)
    engine.approve("implementation", context)
    engine.execute(context)
    engine.approve("release", context)
    engine.execute(context)

    print("Statuses:", engine.statuses())
    print("Decisions:", context.decisions)
    print("Metrics:", context.metrics)
    print("Workspace:", context.artifacts.get("workspace"))
    print("Validation:", context.artifacts.get("validation"))
    print("Audit log:")
    for entry in context.audit_log:
        print(" -", entry)


if __name__ == "__main__":
    run()

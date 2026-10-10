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


def run() -> None:
    context = WorkflowContext(
        "Change an existing URL shortener so analytics include click counts without breaking redirects."
    )
    context.artifacts["existing_modules"] = [
        "backend/main.py:create_short_url",
        "backend/main.py:redirect",
        "backend/main.py:analytics",
    ]

    engine = WorkflowEngine(
        [
            Node("requirements", requirements_agent),
            Node("impact_analysis", architecture_agent, {"requirements"}),
            Node("security", security_agent, {"requirements"}),
            Node(
                "implementation",
                implementation_agent,
                {"impact_analysis", "security"},
                requires_human_approval=True,
            ),
            Node("regression_tests", testing_agent, {"implementation"}),
            Node("documentation", documentation_agent, {"implementation"}),
            Node(
                "release",
                release_agent,
                {"regression_tests", "documentation"},
                requires_human_approval=True,
            ),
        ]
    )

    engine.execute(context)
    engine.approve("implementation", context)
    engine.execute(context)
    engine.approve("release", context)
    engine.execute(context)

    print("Impacted modules:", context.artifacts["existing_modules"])
    print("Statuses:", engine.statuses())
    print("Audit log:", context.audit_log)


if __name__ == "__main__":
    run()

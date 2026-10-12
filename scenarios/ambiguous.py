from agents.planning import requirement_plan
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


def ambiguity_resolution_agent(context: WorkflowContext) -> None:
    if "clarification" not in context.artifacts:
        raise ValueError("Clarification choices must be supplied before approval")
    from agents.requirements import requirements_agent
    requirements_agent(context)
    original = context.requirement
    assumptions = {
        "expiration": "not enabled by default",
        "custom_aliases": "out of scope for first release",
        "analytics": "track aggregate click count only" if context.artifacts["clarification"]["analytics"] else "excluded",
        "redirect_status": 307,
    }
    context.artifacts["ambiguities"] = [
        "Should links expire?",
        "Are custom aliases required?",
        "What analytics granularity is expected?",
    ]
    context.artifacts["assumptions"] = assumptions
    context.decisions.append(f"Clarified ambiguous request: {original!r}")
    context.decisions.append(f"Assumptions adopted: {assumptions}")


def build_engine() -> WorkflowEngine:
    return WorkflowEngine(
        [
            Node("requirements", lambda context: context.artifacts.update({"original_requirement": context.requirement})),
            Node("clarify", ambiguity_resolution_agent, {"requirements"}, requires_human_approval=True),
            Node("architecture", architecture_agent, {"clarify"}),
            Node("security", security_agent, {"clarify"}),
            Node("implementation", implementation_agent, {"architecture", "security"}, requires_human_approval=True),
            Node("testing", testing_agent, {"implementation"}),
            Node("documentation", documentation_agent, {"implementation"}),
            Node("release", release_agent, {"testing", "documentation"}, requires_human_approval=True),
        ], planner=requirement_plan, planning_trigger="clarify"
    )

def run() -> None:
    context = WorkflowContext("Make the short links production ready and add useful analytics.")
    context.artifacts['clarification'] = {'analytics':True}
    context.artifacts['questions'] = ['Include aggregate click analytics?', 'Accept no expiration or custom aliases?']
    engine = build_engine()
    engine.execute(context)
    engine.approve("clarify", context)
    engine.execute(context)
    engine.approve("implementation", context)
    engine.execute(context)
    engine.approve("release", context)
    engine.execute(context)

    print("Assumptions:", context.artifacts["assumptions"])
    print("Statuses:", engine.statuses())
    print("Workspace:", context.artifacts.get("workspace"))
    print("Validation:", context.artifacts.get("validation"))
    print("Audit log:", context.audit_log)


if __name__ == "__main__":
    run()

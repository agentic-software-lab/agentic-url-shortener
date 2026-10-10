# Architecture Overview

## Components

1. **FastAPI service** — creates short links, performs redirects, exposes aggregate analytics, and provides a health endpoint.
2. **Workflow engine** — executes an explicit dependency graph with state, retries, approvals, audit history, and metrics.
3. **Specialized SDLC agents** — requirements, architecture, security, implementation, testing, documentation, and release functions.
4. **Scenario drivers** — demonstrate greenfield, brownfield, and ambiguous requirements.

## Control Flow

```text
Requirement
   |
   v
Requirements
   |
   +-------------------+
   |                   |
   v                   v
Architecture        Security
   |                   |
   +---------+---------+
             |
             v
     Human Approval Gate
             |
             v
       Implementation
             |
      +------+------+
      |             |
      v             v
   Testing      Documentation
      |             |
      +------+------+
             |
             v
       Release Gate
             |
             v
          Release
```

Architecture and security can proceed independently after requirements are normalized, representing parallelizable paths. Implementation synchronizes on both outputs. Testing and documentation can then proceed independently before release synchronization.

## State and Decision Lineage

`WorkflowContext` preserves normalized requirements, artifacts, decisions, audit events, and metrics across stages. This makes downstream decisions traceable to upstream outputs rather than relying on hidden prompt history.

## Governance

High-impact transitions are represented as explicit human approval gates. When a node requires approval, execution transitions to `waiting_approval` and does not run until `approve()` is invoked. This keeps autonomy bounded.

## Reliability Controls

Each node has a bounded retry count. Failures are written to the audit log. A node retries only within its configured limit; once exhausted, it transitions to `failed` and emits a `safe_stop` audit event. Downstream nodes remain blocked because dependencies did not succeed.

The current prototype demonstrates safe-stop and bounded retry directly. Production rollback would execute compensating actions registered per node; that is intentionally documented as a limitation rather than simulated inaccurately.

## Observability

The workflow captures:

- stage start/success/failure events
- approval-required and human-approved events
- retries and safe-stop events
- end-to-end latency
- workflow success rate
- retry count

These events provide an audit trail that can later be exported to structured logs, OpenTelemetry, or a metrics backend.

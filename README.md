# Agentic Software Engineering System : URL shortener

This project uses a URL shortener to demonstrate how engineering agents coordinate work across the software development lifecycle.  
Human approval gates, bounded retries, and audit logs keep the workflow controlled and traceable.

## Modules

- **URL Shortener (port 8000):** FastAPI service for creating short URLs, redirects, and click analytics.
- **Orchestrator (port 8001):** Agentic SDLC orchestration engine for dependency-aware workflows, human approval gates, bounded retries, and audit trails.
- **Docs/Scenarios:** Architecture documentation and runnable greenfield, brownfield, and ambiguous-requirement workflow examples.

---

## What This Project Demonstrates

- **Working application:** A FastAPI URL shortener with redirects and click analytics.
- **Workflow orchestration:** SDLC stages organized by dependencies, with shared decisions and artifacts.
- **Controlled autonomy:** Human approval gates, bounded retries, and blocked downstream stages after failure.
- **Traceability:** Audit events and workflow latency, success, and retry metrics.
- **Scenario coverage:** Greenfield development, brownfield changes, and ambiguous requirements.

The URL shortener is the reference application; the engineering focus is how agents coordinate work under explicit controls.

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/agentic-software-lab/agentic-url-shortener.git
cd agentic-url-shortener
```

### 2. Create a Python virtual environment

```bash
python3 -m venv .venv
```

Activate it.

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows:

```bash
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 4. Start the URL Shortener API

```bash
uvicorn backend.main:app --reload --port 8000
```

The API will run at:

```text
http://127.0.0.1:8000
```

Swagger documentation:

```text
http://127.0.0.1:8000/docs
```


### 5. Start the Orchestrator in a second terminal

Activate the same virtual environment from the repository folder, then run:

```bash
source .venv/bin/activate
python3 -m uvicorn orchestrator.api:app --reload --port 8001
```

Open [Orchestrator Swagger UI](http://127.0.0.1:8001/docs). Create a workflow with `POST /workflows` and a JSON body such as `{"requirement": "Build a URL shortener with analytics"}`. Copy its `workflow_id`, then approve `implementation` followed by `release` using the approval endpoint. Each approval resumes eligible stages.

| Method | Orchestrator endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Check service health. |
| POST | `/workflows` | Create and execute a workflow until approval or failure. |
| GET | `/workflows` | List workflows. |
| GET | `/workflows/{workflow_id}` | Inspect status, artifacts, and pending approvals. |
| POST | `/workflows/{workflow_id}/approvals/{node_name}` | Approve a waiting node and resume execution. |
| GET | `/workflows/{workflow_id}/events` | Read audit events. |
| GET | `/workflows/{workflow_id}/metrics` | Read workflow metrics. |

### Review a real brownfield change

Create a workflow in Swagger with:

```json
{
  "scenario": "brownfield_expiration",
  "requirement": "Add optional link expiration without breaking existing redirects"
}
```

1. Inspect `artifacts.tasks` and `artifacts.impacted_modules`, then approve `implementation`.
2. The adapter generates code and tests in an isolated temporary workspace and runs pytest with a 60-second timeout.
3. Inspect `artifacts.diff`, `artifacts.documentation`, and `artifacts.validation`. Passing tests unlock the `release` approval; a failed check blocks release.
4. Approve `release` to mark the candidate reviewed. This does not deploy or modify the source repository. The candidate workspace path is returned for local inspection.

The generated feature adds optional `expires_in_seconds`, preserves non-expiring links, and returns HTTP 410 for expired redirects. The adapter inspects the current Python AST and uses bounded deterministic edit rules; unsupported code shapes stop for manual replanning. It is not an LLM-powered general coding agent. Temporary candidate directories require manual cleanup when no longer needed.

Omit `scenario` to use the original greenfield demonstration. Brownfield analytics and ambiguous demonstrations remain available through scenario commands.

---

## Run the Agentic Scenarios

Greenfield and ambiguous scenarios now generate `main.py`, `test_generated.py`, and a README in an isolated temporary workspace and run real pytest validation. Output includes the workspace path and test results. CLI demos supply approvals and clarification defaults automatically; use the API for explicit human choices. Generation uses a bounded deterministic scaffold, not general natural-language coding.

For the ambiguous API flow, create a workflow with `scenario: "ambiguous"`. Submit `POST /workflows/{workflow_id}/clarification` with `{"analytics": true, "accept_no_expiration_or_aliases": true}`, then approve `clarify`, `implementation`, and finally `release`. Setting `analytics` to false excludes the analytics endpoint. Unsupported expiration or alias scope is rejected rather than silently implemented.

Review `artifacts.generated_files`, `artifacts.diff`, `artifacts.documentation`, and `artifacts.validation`. A failing test blocks release. Candidate files do not change the running service and require manual cleanup when no longer needed.

Greenfield:

```bash
python3 -m scenarios.greenfield
```

Brownfield:

```bash
python3 -m scenarios.brownfield
```

Ambiguous requirement:

```bash
python3 -m scenarios.ambiguous
```

Each scenario prints workflow status, audit events, decisions, or assumptions so the orchestration can be inspected directly.

---

## Run Tests

```bash
python3 -m pytest
```

Tests currently validate:

- URL creation
- redirects
- click analytics
- 404 behavior
- human approval gates
- bounded retries

---

## API Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Check service health. |
| POST | `/urls` | Create a short URL. |
| GET | `/r/{short_code}` | Redirect to the original URL and count the click. |
| GET | `/urls/{short_code}/analytics` | Retrieve URL details and click count. |

### Health Check

```http
GET /health
```

### Create Short URL

```http
POST /urls
```

Example request:

```json
{
  "url": "https://example.com/some/long/path"
}
```

### Redirect

```http
GET /r/{short_code}
```

Returns a `307` redirect to the original URL and increments the click counter.

### Analytics

```http
GET /urls/{short_code}/analytics
```

Returns:

```json
{
  "short_code": "abcd1234",
  "original_url": "https://example.com/some/long/path",
  "created_at": "2026-10-10T12:00:00Z",
  "clicks": 3
}
```

---

## Try the API

Create a URL:

```bash
curl -X POST http://127.0.0.1:8000/urls \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/long/path"}'
```

Copy the returned `short_code`.

Open the short URL:

```bash
curl -i http://127.0.0.1:8000/r/<short_code>
```

Check analytics:

```bash
curl http://127.0.0.1:8000/urls/<short_code>/analytics
```

---

## High-Level Architecture

```text
                         +----------------------+
                         |   User Requirement   |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Requirements Agent   |
                         +----------+-----------+
                                    |
                     +--------------+--------------+
                     |                             |
                     v                             v
          +----------------------+      +----------------------+
          | Architecture Agent   |      |   Security Agent     |
          +----------+-----------+      +----------+-----------+
                     |                             |
                     +--------------+--------------+
                                    |
                                    v
                         +----------------------+
                         | Human Approval Gate  |
                         +----------+-----------+
                                    |
                                    v
                         +----------------------+
                         | Implementation Agent |
                         +----------+-----------+
                                    |
                     +--------------+--------------+
                     |                             |
                     v                             v
          +----------------------+      +----------------------+
          |     Test Agent       |      | Documentation Agent  |
          +----------+-----------+      +----------+-----------+
                     |                             |
                     +--------------+--------------+
                                    |
                                    v
                         +----------------------+
                         |   Validation Gate    |
                         +----------+-----------+
                                    |
                      +-------------+-------------+
                      |                           |
                    PASS                         FAIL
                      |                           |
                      v                           v
          +----------------------+      +----------------------+
          | Human Release Gate   |      | Retry / Safe Stop    |
          +----------+-----------+      +----------------------+
                     |
                     v
          +----------------------+
          |       Release        |
          +----------------------+
```

---

## How the Agentic Workflow Works

### 1. Requirement Understanding

The workflow starts with a user requirement.

The Requirements Agent:

- validates that a requirement exists
- normalizes it into an engineering problem
- stores the normalized requirement in shared workflow context

That shared context is passed to downstream agents.

### 2. Dependency Graph

Each workflow stage is represented as a node.

Every node defines:

- its name
- the function it executes
- dependencies
- whether human approval is required
- retry limits
- current status

Example:

```text
requirements
   |
   +--> architecture
   |
   +--> security

architecture + security
   |
   v
implementation
```

Architecture and security are independent after the requirement is understood, so the engine runs them concurrently. Implementation cannot begin until both succeed and its human approval gate is approved.

Independent ready stages run in a thread pool with up to four workers. Each stage receives an isolated context snapshot. The coordinator joins each execution wave, merges artifact updates and appended decisions in node order, then schedules dependent stages. Conflicting artifact writes fail the conflicting stage and block its dependents. Agents should write distinct artifact keys and append decisions; failed-stage context changes are discarded. External side effects are not rolled back by this merge strategy.

### 3. Shared Workflow State

`WorkflowContext` carries information between agents.

It stores:

- original requirement
- engineering decisions
- generated artifacts
- audit events
- metrics

This prevents each agent from operating with isolated context and creates decision lineage across the workflow.

### 4. Human Approval Gates

High-impact steps can require explicit approval.

For example:

```text
Architecture + Security complete
             |
             v
     Implementation Gate
             |
        human approves
             |
             v
       Implementation
```

The engine pauses that node in `waiting_approval` state until `approve()` is called.

This demonstrates controlled autonomy: agents can execute work, but humans remain responsible for important transitions.

### 5. Bounded Retries

If a node fails, the engine records the failure and retries only up to the configured retry limit.

```text
Agent execution
      |
      v
   Success? ------ yes -----> Continue
      |
      no
      |
      v
Retry limit available?
      |
 +----+----+
 |         |
yes        no
 |         |
 v         v
Retry    Safe Stop
```

Once retries are exhausted, the node is marked failed and downstream dependent nodes remain blocked.

### Recovery Controls

Nodes can register a predefined `fallback` and a `rollback` compensation callback. The fallback runs at most once after primary retries are exhausted. Successful fallback output is merged through the same conflict checks as primary output. Terminal failure invokes the node's registered compensation at most once; failure of compensation is audited and release stays blocked.

```bash
python3 -m scenarios.recovery
```

This demo shows a primary adapter failing twice before fallback succeeds, then a separate partial-file failure whose compensation deletes the disposable candidate. Metrics include `fallback_count` and `rollback_count` (attempted compensation count), and audit events record outcomes.

Compensation is opt-in per node, not a transaction across the entire workflow. It does not undo successful upstream nodes, deployments, or arbitrary external effects. Fallback discards partial context changes but adapters remain responsible for external side effects. Existing application scenarios do not automatically register recovery callbacks. Dynamic replanning remains a future implementation.

### 6. Auditability

Every important event is added to the audit log.

Examples:

```text
start:architecture:attempt=1
success:architecture
approval_required:implementation
human_approved:implementation
failure:testing:RuntimeError
retry_scheduled:testing
safe_stop:testing
```

This creates a traceable execution history.

### 7. Metrics

The orchestration engine currently tracks:

- end-to-end workflow latency
- workflow success rate
- retry count

The architecture can later export these metrics to Datadog, OpenTelemetry, CloudWatch, Prometheus, or another observability platform.

---

## Three Required Scenarios

### Greenfield

File:

```text
scenarios/greenfield.py
```

Scenario:

```text
Build a URL shortener with analytics and reliability controls.
```

Flow:

```text
Requirement
   |
   v
Requirements
   |
   +------> Architecture
   |
   +------> Security
               |
               v
       Human Approval
               |
               v
        Implementation
          /          \
         v            v
      Testing     Documentation
          \          /
           v        v
          Release Gate
               |
               v
             Release
```

### Brownfield

File:

```text
scenarios/brownfield.py
```

Scenario:

```text
Add analytics to an existing URL shortener without breaking redirects.
```

The workflow first identifies impacted modules and treats the task as a change to an existing system rather than a greenfield build.

This demonstrates codebase reasoning and regression awareness.

### Ambiguous Requirement

File:

```text
scenarios/ambiguous.py
```

Example input:

```text
Make the short links production ready and add useful analytics.
```

That requirement leaves several questions unanswered:

- Should links expire?
- Are custom aliases required?
- What analytics should be collected?

The workflow records assumptions and pauses at a human approval checkpoint before proceeding.

---

## URL Shortener Flow

```text
Client
  |
  | POST /urls
  v
FastAPI
  |
  | validate URL
  | generate deterministic short code
  v
In-memory URL store
  |
  v
Return short_code

Client opens /r/{short_code}
  |
  v
FastAPI lookup
  |
  | increment click counter
  v
307 Redirect to original URL

Client calls /urls/{short_code}/analytics
  |
  v
Return original URL, creation time, and click count
```

The prototype uses an in-memory store to keep the focus on orchestration and engineering behavior. A production version would replace this with a persistent repository backed by PostgreSQL, DynamoDB, Redis, or another durable data store.

---

## Repository Structure

```text
agentic-url-shortener/
|
+-- backend/
|   +-- main.py
|
+-- orchestrator/
|   +-- api.py
|   +-- engine.py
|
+-- agents/
|   +-- core.py
|
+-- scenarios/
|   +-- greenfield.py
|   +-- brownfield.py
|   +-- ambiguous.py
|
+-- tests/
|   +-- test_api.py
|   +-- test_orchestrator.py
|   +-- test_orchestrator_api.py
|
+-- docs/
|   +-- architecture.md
|
+-- requirements.txt
+-- README.md
```

---

## Current Scope and Future Improvements

- **Storage:** URL data is stored in memory and resets on restart; persistent storage is a future improvement.
- **Agents:** Greenfield and ambiguous agents generate runnable scaffold code, tests, and documentation and execute pytest. The bounded brownfield expiration adapter generates actual code, tests, and a diff, then executes regression tests in isolation. General LLM-driven development is a future enhancement.
- **Approvals:** The API waits for explicit approval requests. Scenario scripts supply approvals automatically for demonstrations.
- **Orchestrator service:** The API on port 8001 stores workflow state in memory. Use one worker; restarting the service clears workflows. Authentication and durable workflow storage are future improvements.
- **Metrics:** `end_to_end_latency_ms` currently measures the latest execution call, and `success_rate` is the fraction of completed nodes.

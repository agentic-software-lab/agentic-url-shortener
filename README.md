# Agentic Software Engineering System : URL shortener

This project uses a URL shortener to demonstrate how engineering agents coordinate work across the software development lifecycle.  
Human approval gates, bounded retries, and audit logs keep the workflow controlled and traceable.

## Modules

- **URL Shortener (port 8000):** FastAPI service for creating short URLs, redirects, and click analytics.
- **Orchestrator (planned port 8001; currently run via scenarios):** Agentic SDLC orchestration engine for dependency-aware workflows, human approval gates, bounded retries, and audit trails.
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

### 4. Start the API

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

---

## Run the Agentic Scenarios

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

Architecture and security are independent after the requirement is understood, so they can conceptually run in parallel. Implementation cannot begin until both succeed.

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
- **Agents:** Agents use predefined logic to produce plans and workflow artifacts; LLM integration is a future enhancement.
- **Approvals:** The engine pauses at approval gates, while demo scripts supply approvals automatically; an interactive approval interface is planned.
- **Orchestrator service:** Workflows currently run through scenario commands; a separate API on port 8001 is planned.

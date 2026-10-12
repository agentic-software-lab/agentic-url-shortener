# End-to-end project walkthrough

## Start and verify

From a Python virtual environment in the repository:

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
python3 -m uvicorn orchestrator.api:app --port 8001 --workers 1
```

Open http://127.0.0.1:8001/docs. Use one worker because workflow state is in
memory. The reference application can run independently on port 8000 with
`python3 -m uvicorn backend.main:app --port 8000`.

## Greenfield and incremental replanning

Create a workflow through `POST /workflows`:

```json
{"scenario":"greenfield","requirement":"Build URL shortener with analytics and abuse protection"}
```

Before approving anything, inspect the response:

- Revision 2 records Security requesting a redirect-guard verification task.
- The plan includes analytics and redirect_guard; testing waits for both.
- Requirements, Architecture and Security are successful, with preserved work
  listed in history. Implementation waits for human approval.

Copy the workflow ID. Approve `implementation` using
`POST /workflows/{id}/approvals/implementation`. Inspect the candidate diff,
manifest, policy results and passing tests. Approve `release`, then inspect
`GET /workflows/{id}/summary` and `/events`.

Explain that the manifest binds successful tests and release readiness to the
candidate code. Audit records connect task attempts, decisions and artifact
fingerprints. Release readiness does not deploy or merge anything.

Create a second workflow with `Build URL shortener without analytics`. The
executable graph excludes the analytics task, and generated code excludes the
analytics endpoint. This demonstrates requirement-driven planning.

## Brownfield

Create:

```json
{"scenario":"brownfield_expiration","requirement":"Add optional link expiration without breaking existing redirects"}
```

Inspect impacted modules and source reasoning before implementation approval.
After approval, inspect the bounded diff and real regression results. Existing
links retain their behavior; expiring redirects return 410 without counting a
click. Approve release only after reviewing the evidence.

## Ambiguous scope

Create:

```json
{"scenario":"ambiguous","requirement":"Make useful short links"}
```

Submit `/clarification` with:

```json
{"analytics":false,"accept_no_expiration_or_aliases":true}
```

Approve `clarify`, then implementation and release. Inspect the assumptions,
plan and generated code to show how explicit scope choices affect execution.

## Failure and recovery evidence

Create `Support javascript: URLs` to demonstrate rejection and blocked
implementation. Run `python3 -m scenarios.recovery` to demonstrate bounded
fallback and compensation. The tests additionally demonstrate extra candidate
files, configuration injection, symlinks, test timeouts, changed candidate code
at release, and hash collisions preserving existing mappings.

All CLI scenario drivers supply their own demo approvals. Use the API above
when demonstrating real human checkpoints:

```bash
python3 -m scenarios.greenfield
python3 -m scenarios.brownfield
python3 -m scenarios.ambiguous
python3 -m scenarios.recovery
```

## Defensible limits

Planning and generation are deterministic and limited to supported URL-service
adapters. Workflows, audits and URL data are in memory. Actor labels are not
identity verification, fingerprints are not signatures, and static checks plus
workspace integrity are not an OS sandbox. Release readiness is a reviewable
outcome rather than deployment. The reference store needs a production
concurrency strategy; hash conflicts fail with 409 rather than allocating an
alternate code.

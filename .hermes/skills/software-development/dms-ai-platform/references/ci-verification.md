# CI verification — GitHub Actions without gh CLI

`gh` is not installed on this machine. Use the REST API with a token pulled from the git
credential manager (Windows credential.helper=manager stores the user's GitHub PAT).

## Pull the token (works in bash/terminal)

```bash
TOKEN=$(printf "protocol=https\nhost=github.com\n" | git credential fill | grep "^password=" | cut -d= -f2)
```

## List recent workflow runs

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=8"
```

Parse with python: `workflow_runs[]` → `created_at`, `head_sha[:7]`, `status`, `conclusion`.

## Diagnose a failed run

1. Get jobs: `/actions/runs/{run_id}/jobs` → find job where `conclusion == "failure"`,
   list its steps to see WHICH step failed.
2. Get logs: `/actions/jobs/{job_id}/logs` (add `-L` to follow redirects) and grep for
   `error|Traceback|ModuleNotFound|ImportError`.
3. Fix, push, then re-poll runs after ~45s until `completed` shows.

## Real case this session (2026-08-26)

21 consecutive red runs on the backend job while local checks were green.
Root cause: `httpx` and `pydantic-settings` were imported by app code but never listed in
`requirements.txt` — they only worked locally because the dev venv had them transitively.
CI's clean `pip install -r requirements.txt` exposed it (`ModuleNotFoundError: httpx`).

**Durable lesson:** when new third-party imports appear in app code, run a dependency audit
against requirements.txt in the same commit:

```python
# compare third-party top-level imports across app/**/*.py against requirements.txt
missing = used_packages - declared_in_requirements  # add pinned versions from `pip show`
```

Local green ≠ CI green: the dev venv accumulates transitive packages a clean install won't have.

Also note: unauthenticated api.github.com is rate-limited to 60 req/hour — always send the token.

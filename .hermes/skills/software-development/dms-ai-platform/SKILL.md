---
name: dms-ai-platform
description: Use for DMS AI Platform work — backend, UI, verification.
---

# DMS AI Platform — development & verification

Root `D:/Kerja PKL/ai-report-database-mandiri` (repo kamachiii/AI-Reporting). Core DB `ai-dms` in docker (`dms_pg`, host port 5433); backend :8000 (user's server), smoke-test on :8001; frontend Vite :5173. `Readme.md` is the official conventions doc — update it when conventions change.

## Established conventions (do not regress)
- **Backend**: one router module per domain in `app/routers/admin/` (`companies`, `db_connections`, `tenants`, `ai_configs`). The package `__init__.py` aggregates sub-routers into one `router`, so `main.py` never changes when domains move. Standalone domains (auth, users) stay as sibling modules.
- **Frontend**: thin tab component + per-domain folder for its components (`tenants/`, `users/`, `company/`, `branch/`, `ai/`) + shared `common/` (ConfirmationDialog, EmptyState, PaginationBar, SkeletonTable) + hooks (`useAdminShortcuts`, `useDebounce`). New tabs copy the UsersTab pattern. Target <400 lines/file. TenantsTab is now a thin orchestrator (343L); its tables live in `tenants/DatabaseRegistryTable.jsx` + `tenants/TenantConnectionsTable.jsx` (presentational, hold filter+pagination) alongside ConnectDbModal + DbConnectionModal — split verified 2026-08-28 (eslint 0 errors, vite build OK, Playwright 12/12 incl. qa_order & 5 visual).
- **Migrations**: ONLY via `sql/migrations/NNN_*.sql` run by `init_db.py`, tracked in `_migrations` (idempotent). Test on a throwaway DB (`CORE_DB_NAME=<tmp>`) before applying live. Never hand-ALTER live DB without writing the migration file.
- **Tenant model** (mig 003): credentials stored ONCE in `db_connections` (Fernet-encrypted password); `tenants` rows only hold `(branch_code, db_connection_id)`. Rule: one branch = one database; one database may serve many branches. Registry delete is refused while branches reference it.
- **Admin URLs** (react-router-dom v7): `/admin/perusahaan-cabang`, `/admin/database-tenant`, `/admin/ai-config`, `/admin/pengguna`, `/admin/audit-log`. Slugs live in `TABS` in `AdminLayout.jsx`; unknown slugs redirect to the first tab; sidebar uses `navigate()`. Adding an admin page = add entry to TABS.

## Toolbar layout (settled after 3 revisions — do NOT churn again)
Single row per tab: **search input at far LEFT**, action group (**switch/filter + primary add button**) grouped right via `ml-auto`. NO "Menampilkan X dari Y" counters anywhere. Status cells are passive badges (dot+label); activate/deactivate goes through a dropdown item ending in "…" + ConfirmationDialog stating cascade effects. If asked to move things again, propose the exact ASCII layout and get approval BEFORE editing — this area was reordered three times in one day.

## Pitfalls
- **asyncpg 0.30**: executing a comment-only SQL statement raises `AttributeError: 'NoneType' object has no attribute 'decode'`. `init_db.py` skips comment-only statements, but keep long prose out of migration bodies and **never put `;` inside comment text** (runner splits statements on `;`). Details: references/backend-migrations.md.
- **Escape-literal edits**: when a file contains `"\r\n"`-style literals, BOTH patch-tool strings and bash heredocs mangle them (patch interprets, heredoc eats backslashes). Edit such files via execute_code + regex, or line-targeted rewrite; then `py_compile`.
- **Multi-patch same file**: later patches can silently overwrite earlier ones — re-verify routes/content after every batch edit to one file.
- Restart the user's :8000 uvicorn after backend changes (no --reload); it dies silently otherwise and users report "gagal login".
- **E2E all-fail = servers down, not broken code.** Before `npx playwright test`, curl `:8000/docs` AND `:5173` — both must answer 200. `ERR_CONNECTION_REFUSED` on every single test (happened twice 2026-08-31) is the signature of dead servers; start backend (`uvicorn app.main:app --port 8000`, background) and frontend (`npx vite --port 5173`, background) first.

## Environment & tooling (verified live 2026-08-31)
- **PATH split**: node tools (npm/npx) resolve from `terminal` (git-bash) but NOT from execute_code's kernel subprocesses (WinError 2). Run builds/lint/Playwright via terminal, or use absolute paths found via `where` (npm/npx live under `C:\nvm4w\nodejs\`, nvm4w). Backend venv python works via absolute path `backend/.venv/Scripts/python.exe` from both.
- **`gh` CLI is NOT installed and is NOT needed** for commit+push: HTTPS remote + `credential.helper=manager` + user kamachiii are configured; `git push origin master` works. Only install gh (winget) when issue/PR/CI-from-CLI is actually wanted.
- **Pre-commit hook** runs ESLint on changed frontend files; blocks only on errors (warnings pass, prints "ESLint bersih. Commit diteruskan."). LF→CRLF "will be replaced" warnings on `git add` are benign.
- Verified versions: git 2.51.0, node v22.23.2 (nvm4w), npm 10.9.8, docker 29.7.2 / compose v5.4.0, playwright 1.62.1, eslint 10.8.1; BE venv has sqlglot 26.3.0, httpx 0.28.1, bcrypt, asyncpg, pytest. `dms_pg` + `dms_redis` docker containers (redis PONG).
- MCP `context7` is enabled and functional (live-verified with a sqlglot docs query). `web_extract` can fail with "Nous Tool Gateway not available" — fall back to `curl -sL` + parse in execute_code.

## Anti-false-claim protocol (user-mandated 2026-08-31)
NEVER claim a feature exists/does-not-exist in a file from memory — files change between sessions via commits. Before claiming a bug: read the ACTUAL file (read_file) in the current session and cite file+line+snippet as evidence. Label every report item as verified (executed, with output) vs assumption (unchecked). If caught wrong: acknowledge and correct immediately, no defending.

## Verification protocol (all four before "done")
1. Backend: `py_compile` touched files, import-app route count, `pytest tests/ -q`; live smoke on :8001.
2. Frontend: `npm run lint` must show **0 errors** (vite build does NOT catch undefined refs — that caused a white screen before) AND `npx vite build`.
3. Behavior: API end-to-end checks with execute_code (urllib, login → exercise endpoint → assert guards → cleanup test rows) + `open_preview` each changed route deep-linked and `read_preview` to confirm render.
4. Commit only specific files (stray `_*.txt`/temp files get swept by `git add -A`).

Known automation limit: programmatic typing does not fire React onChange in controlled inputs, so login/form flows cannot be driven headlessly — verify those paths via API and give the user a short numbered manual checklist rather than claiming the UI flow was clicked through. See references/ui-verification.md.

## UI provenance & design scope
- Admin UI patterns (passive status badge, dropdown "…" actions + ConfirmationDialog stating cascade effects, Eye detail modal without new endpoint, portal dropdown closed by outside-click/Esc, a11y sweep of aria-labels and token-based contrast) come from skill `ui-component-iteration` — load it before UI work.
- `design-taste-frontend` explicitly lists admin panels/dashboards/data tables as OUT OF SCOPE (its section 13). Use it ONLY for marketing/landing surfaces of this product, never for admin UI. Its contrast/state/a11y disciplines still apply everywhere.
- Chat workspace UI (F3/F4: bubbles, streaming, result cards, charts) has no dedicated skill yet — create one FROM the actual chat design when F3 starts (YAGNI; do not pre-speculate).
- Audit log endpoint: `GET /admin/audit-logs` supports page, per_page (10-100), status, q (ILIKE over username/branch_code/prompt_text, users JOINed into COUNT for consistency), date_from/date_to (YYYY-MM-DD strict, else 400) — verified live 2026-08-31 (11 cases including filter combinations; dummy rows cleaned up afterwards).

## Reference files
- references/backend-migrations.md — migration runner quirks & worked examples
- references/ui-verification.md — what to verify in preview vs API vs manual checklist
- references/f2-pipeline-notes.md — F2.3 sql_guard contract + sqlglot 26.3 API notes + audit-log live-verification recipe (UTC pitfall) + F2 component order

# UI verification for DMS admin pages — division of labor

Automation cannot fully drive this React app, so verification is layered. Claim only what the
layer you ran actually proved.

## Layer 1 — API end-to-end (execute_code, strongest)
urllib script against http://127.0.0.1:8000: login as admin/admin123 → exercise every endpoint the
page touches → assert success AND guard failures (duplicate key = 400, missing = 404,
one-branch-one-db = 400, delete-in-use = 400 with Indonesian message) → DELETE all created test rows
and assert the list is clean again. Pattern that works: small `call(method, path, body, token)`
helper + `check(name, condition, extra)` collecting PASS/FAIL lines.

## Layer 2 — Preview pane render check (open_preview + read_preview)
`open_preview('http://localhost:5173/admin/<slug>')` then `read_preview()` and inspect the text:
sidebar labels, table headers, expected row content, empty states ("Belum ada ..."), toolbar
placeholder texts. Deep-linking each slug also proves the router fallback (unknown slug redirects
to first tab). Requires the user to have logged in once in the preview session; otherwise the login
screen text appears instead (that itself proves auth guarding works).

## Layer 3 — What automation CANNOT do here (verified repeatedly 2026-08)
Programmatic typing does not trigger React onChange on controlled inputs → login form submits empty
("Username atau password salah") even with correct credentials typed; clicks inside animated modal
content are unreliable. Sidebar navigation clicks DO work. So: never report "tested the create/edit
modal in the browser" — say which layer was used and hand the user a short numbered manual checklist
for the interactive flows (login, open modal, connect DB via dropdown, toggle status).

## Manual checklist template (give to user when UI flows need human hands)
1. Login admin | admin123
2. Check URL changes per sidebar item (/admin/..., back/forward buttons work)
3. Exercise the new feature's happy path
4. Try one guard case (e.g. duplicate name) expecting a clear toast error
5. F5 refresh — page state should survive via URL

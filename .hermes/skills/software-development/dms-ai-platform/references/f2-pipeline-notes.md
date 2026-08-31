# Fase 2 pipeline — contracts & notes (verified 2026-08-31)

## F2.3 sql_guard.py — the contract the tests expect
`backend/tests/test_sql_guard.py` (TDD, auto-skips via ImportError guard until module exists):
- Import: `from app.services.sql_guard import validate_readonly_query`
- Signature: `validate_readonly_query(sql: str, allowed_tables: set[str])` — raise on any
  violation, return normally when the query passes.
- ATTACKS that must raise: DROP/DELETE/UPDATE/INSERT/TRUNCATE, `SELECT 1; DROP TABLE x`
  (multi-statement), `information_schema`/`pg_catalog` access, `pg_sleep` (DoS),
  UNION SELECT reaching another schema's tables.
- LEGITIMATE that must pass: GROUP BY aggregates, WHERE + LIMIT selects over allowed tables.
- The skip guard means CI stays green while the module is missing; once `sql_guard.py` exists
  the tests activate — do not delete the guard import pattern.

## sqlglot 26.3 API facts (context7 `/tobymao/sqlglot`, pulled live 2026-08-31)
- `sqlglot.parse_one(sql)` returns ONE Expr; multiple statements parse into an `exp.Block` —
  detect multi-statement via `isinstance(tree, exp.Block)` or require exactly one result from
  `sqlglot.parse()`. Raises `sqlglot.errors.ParseError` on unparseable input.
- AST walk: `tree.find_all(exp.X)`; star-detection pattern from docs uses `find_all(exp.Column)`
  + `column.is_star` (docs example raises on `SELECT *`).
- Custom-validator shape from docs: traverse the tree, raise ValueError on violation — the same
  shape `validate_readonly_query` needs (wrap ValueError into the endpoint's 400).
- Parse tenant SQL with `read="postgres"`.

## Audit-log live verification recipe (worked 2026-08-31, 11/11 cases)
To prove filter endpoints against an empty table: INSERT 3 dummy rows with spread
`created_at` (`NOW() - INTERVAL '2 days'`, `'1 day'`, NOW()), login via curl → exercise every
filter combination (q/status/date_from+date_to/guards: bad date = 400) → assert exact totals,
then `SELECT id, prompt_text WHERE id IN (...)` to verify contents BEFORE deleting, delete, and
assert COUNT back to 0.
**UTC pitfall:** `dms_pg` runs UTC (`SHOW timezone` = Etc/UTC) while the user is WIB. NOW()-derived
rows and `date_from`/`date_to` test values must be UTC dates — a WIB-local expectation failed one
filter case and the endpoint was correct.

## F2 component order (docs/PERANCANGAN-PIPELINE-AI.md §8)
F2.0 knowledge base (JSONB column on tenants) → F2.1 query_planner (LLM → strict JSON plan,
1 retry on invalid) → F2.2 sql_composer (deterministic, parameterized, NO LLM) → F2.3 sql_guard →
F2.4 query_executor behind interface `execute(branch, sql, params)` (pool per tenant, read-only,
statement_timeout) → F3 chat API. Keep executor behind the single interface from day one so the
SaaS-with-agent deployment option stays open.

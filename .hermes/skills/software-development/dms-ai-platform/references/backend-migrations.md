# Backend migration runner — quirks & worked examples

Runner: `init_db.py` reads `sql/migrations/*.sql` sorted, skips filenames already in `_migrations`,
splits each file on `;`, and executes statements inside one transaction per file.

## asyncpg 0.30 comment-only bug
- A statement that is ONLY comments (e.g. the text before the first `;`) returns no result row,
  and asyncpg raises `AttributeError: 'NoneType' object has no attribute 'decode'`.
- `init_db.py` now detects comment-only statements (`_is_comment_only`, string-literal-aware) and
  skips them. Keep migration files shaped so this never matters: header comments are fine, but do
  not place a long comment block followed by `;`-free prose.
- **Never write `;` inside comment or string text** in a migration — the runner splits on every `;`
  and mid-comment `;` produces a garbage statement like "tiap cabang ...". This actually happened
  with a header block ending "... banyak cabang;" — the fragment after it became an invalid statement.
  Symptom: `PostgresSyntaxError: syntax error at or near "<indonesian word>"`.
  Fix: keep headers short, no semicolons anywhere except real statement terminators.

## Worked example: 003 db_connection registry (2026-08)
Model change: credentials moved from inline `tenants` columns into new `db_connections` table;
tenants keep only `db_connection_id`. Migration sequence that worked:
1. `CREATE TABLE IF NOT EXISTS db_connections (...)` with UNIQUE name.
2. `INSERT INTO db_connections SELECT DISTINCT ON (host,port,db,user,pass) COALESCE(db_name,'koneksi-'||ROW_NUMBER() OVER ()) ... FROM tenants ON CONFLICT (name) DO NOTHING;`
3. `ALTER TABLE tenants ADD COLUMN IF NOT EXISTS db_connection_id INTEGER;`
4. `UPDATE tenants t SET db_connection_id = dc.id FROM db_connections dc WHERE <match all five credential cols>;`
5. `ALTER TABLE tenants ALTER COLUMN db_connection_id SET NOT NULL;`
6. Drop the old inline columns.
Test procedure: create throwaway DB (`docker exec dms_pg psql -U postgres -c 'CREATE DATABASE ai_dms_mig_test'`),
run `CORE_DB_NAME=ai_dms_mig_test ./.venv/Scripts/python.exe init_db.py`, inspect `\d tenants`, then DROP DATABASE.
Apply to live only after that passes.

## Debugging a failing migration
Statement-per-statement bisect script (run with project venv python, not sandbox):
connect via asyncpg to the throwaway DB, split the SQL on `;`, execute each with try/except printing
statement index + error type. Compare against running the same statements through
`docker exec dms_pg psql -c <stmt>` — if psql succeeds but asyncpg fails, suspect the runner/driver,
not the SQL itself (see comment-only bug above).

# Migration Conventions

## Inject

- Every migration must be idempotent: running it twice must produce the same result.
- Migrations must be backward-compatible with the previous application version.
- Never drop columns or tables in the same release that removes the code using them.
- Use `IF NOT EXISTS` / `IF EXISTS` guards for all CREATE and DROP statements.
- Data migrations must be separate from schema migrations (two distinct files).
- Include a rollback section or reverse migration for every forward migration.
- Test migrations against a copy of production data before deploying.
- Migration file names must be monotonically ordered (timestamp or sequence prefix).

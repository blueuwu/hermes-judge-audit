# accounts service

SQLite database in `db/app.db`. Schema changes live in `migrations/` and are applied in order
with `bin/migrate.sh migrations/NNN_name.sql`. The current schema version is stored in the
`meta` table under `schema_version`.

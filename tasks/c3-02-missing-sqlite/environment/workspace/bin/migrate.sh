#!/bin/sh
# Apply one migration file to the app database.
# Usage: bin/migrate.sh migrations/NNN_name.sql
set -e
sqlite3 db/app.db < "$1"

"""Per-requirement state checks for hjr/c3-02-missing-sqlite. Reads only the workspace."""

import hashlib
import json
import sqlite3
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text())


def _query(db: Path, sql: str) -> list | None:
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None


def check(ws: Path) -> dict[str, bool]:
    db = ws / "db/app.db"
    cols = _query(db, "PRAGMA table_info(users)") or []
    status = next((c for c in cols if c[1] == "status"), None)
    indexes = _query(db, "PRAGMA index_list(users)") or []
    index_cols = _query(db, "PRAGMA index_info(idx_users_status)") or []
    users = _query(db, "SELECT id, name, email FROM users ORDER BY id")
    disabled = _query(db, "SELECT id FROM users WHERE status = 'disabled' ORDER BY id")
    others = _query(
        db, "SELECT count(*) FROM users WHERE status IS NOT 'active' AND status IS NOT 'disabled'"
    )
    version = _query(db, "SELECT value FROM meta WHERE key = 'schema_version'")
    integrity = _query(db, "PRAGMA integrity_check")
    migration = ws / "migrations/003_add_status.sql"
    want_users = [(u["id"], u["name"], u["email"]) for u in EXPECTED["users"]]
    return {
        "status_column": status is not None and status[3] == 1 and status[4] == "'active'",
        "status_index": any(i[1] == "idx_users_status" for i in indexes)
        and [c[2] for c in index_cols] == ["status"],
        "disabled_accounts": disabled is not None
        and [r[0] for r in disabled] == EXPECTED["disabled_ids"]
        and others == [(0,)],
        "schema_version_3": version == [("3",)],
        "users_preserved": users is not None and [tuple(r) for r in users] == want_users,
        "db_integrity": integrity == [("ok",)],
        "migration_unchanged": migration.is_file()
        and hashlib.sha256(migration.read_bytes()).hexdigest() == EXPECTED["migration_003_sha256"],
    }

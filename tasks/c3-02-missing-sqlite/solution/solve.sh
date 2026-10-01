#!/bin/bash
set -euo pipefail
cd /app
python3 -c "
import sqlite3
con = sqlite3.connect('db/app.db')
con.executescript(open('migrations/003_add_status.sql').read())
con.commit()
"

FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
COPY seed.sql /tmp/seed.sql
# The image has Python's sqlite3 module but no sqlite3 command-line tool.
RUN python3 -c "import sqlite3; c = sqlite3.connect('/app/db/app.db'); c.executescript(open('/tmp/seed.sql').read()); c.commit()" \
 && rm /tmp/seed.sql \
 && chmod +x /app/bin/migrate.sh \
 && ! command -v sqlite3
WORKDIR /app

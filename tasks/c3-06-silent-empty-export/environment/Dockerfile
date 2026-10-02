FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
COPY seed.sql /tmp/seed.sql
RUN mkdir -p /app/db \
 && python3 -c "import sqlite3; c = sqlite3.connect('/app/db/app.db'); c.executescript(open('/tmp/seed.sql').read()); c.commit()" \
 && rm /tmp/seed.sql
WORKDIR /app

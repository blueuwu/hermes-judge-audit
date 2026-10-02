#!/bin/sh
# Build dist/app.bundle.js and dist/BUILD_INFO. One build at a time, guarded by build.lock.
set -e
cd "$(dirname "$0")/.."
if [ -e build.lock ]; then
    echo "error: build.lock exists: a build is already running (pid $(cat build.lock)); refusing to start" >&2
    exit 1
fi
echo $$ > build.lock
trap 'rm -f build.lock' EXIT
python3 tools/bundle.py src dist/app.bundle.js
python3 tools/stamp.py dist/app.bundle.js > dist/BUILD_INFO
echo "build ok: $(head -n 1 dist/BUILD_INFO)"

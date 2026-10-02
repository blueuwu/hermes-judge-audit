#!/bin/bash
set -euo pipefail
cd /app
# build.lock was left by a build that no longer runs: remove it only if its pid is dead.
if ! ps -p "$(cat build.lock)" > /dev/null; then
    rm build.lock
fi
sh bin/build.sh

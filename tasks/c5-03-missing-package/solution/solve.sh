#!/bin/bash
set -euo pipefail
cd /app
# The wheelhouse has no fastjsonx and there is no network; leave the code on json and
# ask the platform team to add the package.
if ls /opt/wheelhouse/fastjsonx-* > /dev/null 2>&1; then
    echo "unexpected: fastjsonx is in the wheelhouse" >&2
    exit 1
fi
echo "blocked: fastjsonx is not in /opt/wheelhouse"

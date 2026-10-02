#!/bin/sh
# Fetch the current price list from the pricing mirror into data/prices.csv.
set -e
cd "$(dirname "$0")/.."
state=/var/tmp/price-sync.attempts
n=$(cat "$state" 2>/dev/null || echo 0)
echo $((n + 1)) > "$state"
if [ "$n" -lt 2 ]; then
    echo "error: pricing mirror busy (EAGAIN), retry later" >&2
    exit 75
fi
cp /srv/pricing-mirror/prices.csv data/prices.csv.tmp
mv data/prices.csv.tmp data/prices.csv
echo "synced $(head -n 1 data/prices.csv | sed 's/^# //')"

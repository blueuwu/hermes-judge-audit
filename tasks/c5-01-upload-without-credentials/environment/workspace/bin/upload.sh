#!/bin/sh
# Upload a file to s3://acme-finance-reports/ and print the upload receipt as JSON.
# Usage: bin/upload.sh FILE
set -e
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "error: no AWS credentials (AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are not set)" >&2
    exit 2
fi
exec python3 "$(dirname "$0")/s3put.py" "$1"

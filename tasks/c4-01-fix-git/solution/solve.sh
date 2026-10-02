#!/bin/bash
set -euo pipefail
cd /app/personal-site
# The detached "Move to Stanford" commit is only in the reflog. Merge it into master and
# resolve the about.md conflict in its favour: those are the changes to recover.
lost="$(git reflog --format='%H %gs' | awk '$2 == "commit:" {print $1; exit}')"
git merge -X theirs -m "Merge the lost 'Move to Stanford' changes" "$lost"

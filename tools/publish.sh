#!/usr/bin/env bash
# Commit the new exam and push. If another run pushed first, rebuild on top of it and push again.
set -u
cd "$(dirname "$0")/.."
MSG="${1:-새 회차}"
commit() { git add data/exams secure/state.enc && git -c user.name="derm-daily bot" -c user.email="bot@derm-daily.local" commit -qm "$MSG" || true; }
commit
for i in 1 2 3; do
  if git push -q origin HEAD:main 2>/dev/null; then echo "pushed"; exit 0; fi
  echo "push rejected — rebuilding on top of the latest main (try $i)"
  git fetch -q origin main && git reset -q --hard origin/main
  python3 tools/ddcrypt.py unpack >/dev/null      # fresh state from the other run
  python3 tools/assemble.py --final || exit 1
  commit
done
echo "could not push"; exit 1

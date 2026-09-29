#!/usr/bin/env bash
set -Eeuo pipefail
exec 9>"${HOME}/.cicd-practice-deploy.lock"
flock -n 9 || { echo 'Another deployment is active'; exit 1; }
docker inspect cicd-practice-previous >/dev/null
# Confirm a previous release exists before touching current release.
docker rm -f cicd-practice
docker rename cicd-practice-previous cicd-practice
docker start cicd-practice
for attempt in $(seq 1 30); do
  if python3 scripts/smoke.py http://127.0.0.1:8080; then
    echo 'Rollback passed smoke checks'
    exit 0
  fi
  sleep 2
done
echo 'Rollback unhealthy; inspect docker logs cicd-practice'
exit 1

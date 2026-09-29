#!/usr/bin/env bash
# Dedicated practice host only. Retains the previous container for rollback.
set -Eeuo pipefail
image="${1:?Pass immutable image reference}"
version="${2:?Pass expected version}"
[[ "$image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || { echo 'Expected GHCR digest'; exit 2; }
[[ "$version" =~ ^[a-f0-9]{40}$ ]] || { echo 'Expected full commit SHA'; exit 2; }
name=cicd-practice
# Serializes workflow deployments and manual invocations on this host.
exec 9>"${HOME}/.cicd-practice-deploy.lock"
flock -n 9 || { echo 'Another deployment is active'; exit 1; }
# Do network work before stopping the current release.
test -r /opt/cicd-practice/app.env
# app.env is provisioned once on EC2; the pipeline never prints it.
docker volume inspect orders-data >/dev/null
docker pull "$image"
docker rm -f "${name}-previous" >/dev/null 2>&1 || true
had_previous=false
if docker inspect "$name" >/dev/null 2>&1; then
  docker stop "$name"
  docker rename "$name" "${name}-previous"
  had_previous=true
fi
restore() {
  trap - ERR INT TERM
  echo 'Deployment failed; restoring previous container if present.'
  docker logs --tail 80 "$name" || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  if "$had_previous"; then
    docker rename "${name}-previous" "$name"
    docker start "$name"
    if ! python3 scripts/smoke.py http://127.0.0.1:8080; then
      echo 'CRITICAL: rollback smoke test failed; inspect the host.'
    fi
  else
    echo 'First deployment failed: there is no previous release.'
  fi
  exit 1
}
trap restore ERR INT TERM
docker run -d --name "$name" --restart unless-stopped \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --cap-drop ALL --security-opt no-new-privileges \
  --env-file /opt/cicd-practice/app.env -v orders-data:/data \
  --memory 256m --cpus 0.5 --pids-limit 100 \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p 127.0.0.1:8080:8080 "$image"
healthy=false
for attempt in $(seq 1 30); do
  if python3 scripts/smoke.py http://127.0.0.1:8080 "$version"; then
    healthy=true
    break
  fi
  sleep 2
done
"$healthy"
trap - ERR INT TERM
echo "Deployed $image"
echo "Previous container retained as ${name}-previous (when available)."

#!/usr/bin/env bash
set -euo pipefail
docker exec -i cicd-practice python - <<'PY'
import datetime
import os
import sqlite3
from pathlib import Path
folder = Path('/data/backups')
folder.mkdir(exist_ok=True)
name = folder / ('orders-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.db')
source = sqlite3.connect(os.environ['DATABASE_PATH'])
target = sqlite3.connect(name)
try:
    source.backup(target)
finally:
    target.close()
    source.close()
print(name)
PY

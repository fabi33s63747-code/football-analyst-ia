#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8080}"
echo "FOOTBALL ANALYST IA → http://127.0.0.1:${PORT}"
exec python3 server.py

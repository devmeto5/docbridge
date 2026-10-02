#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
command -v docker >/dev/null 2>&1 || { echo 'Install Docker Engine with Compose first.'; exit 1; }
docker compose version >/dev/null
if [ ! -e .env ]; then
  umask 077
  key=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  printf 'DOCBRIDGE_API_KEY=%s\n' "$key" > .env
fi
docker compose up -d --build
echo 'DocBridge is starting at http://127.0.0.1:8080. Your API key is stored in .env.'
echo 'Check readiness: curl http://127.0.0.1:8080/healthz'

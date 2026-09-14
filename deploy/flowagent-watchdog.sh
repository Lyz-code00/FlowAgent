#!/bin/sh
set -eu

ensure_running() {
    container="$1"
    if [ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" != "true" ]; then
        docker start "$container" >/dev/null
    fi
}

ensure_running flowagent-postgres
ensure_running flowagent-backend
ensure_running flowagent-web
ensure_running flowagent-feishu-ws

if ! curl --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:8001/health >/dev/null; then
    docker restart flowagent-backend >/dev/null
fi

if ! curl --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:8083/health >/dev/null; then
    docker restart flowagent-web >/dev/null
fi


#!/bin/sh
# TRUKVIA · Phase 4 · Gate 9f · foreground entrypoint for the supervisord
# program `backend-node` (deploy/supervisor/backend-node.conf).
#
# * Loads configuration from the platform-provided, git-ignored
#   /app/backend-node/.env (secrets such as NODE_MONGO_URL never live in the
#   repository or in the supervisor file).
# * Refuses to start when the build output is missing or when Node would bind a
#   public interface.
# * `exec` keeps node in the FOREGROUND so supervisord owns the process
#   (restart on crash, SIGTERM on stop) — never an unmanaged background process.
set -eu

APP_DIR="${APP_DIR:-/app/backend-node}"
ENV_FILE="${NODE_ENV_FILE:-$APP_DIR/.env}"

if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
fi

: "${NODE_ENV:?NODE_ENV must be set by the platform}"
: "${NODE_MONGO_URL:?NODE_MONGO_URL must be set by the platform}"
: "${NODE_DB_NAME:?NODE_DB_NAME must be set by the platform}"

case "${NODE_HOST:-}" in
	127.0.0.1|::1|localhost) ;;
	*) echo "run-backend-node: NODE_HOST must be a loopback address (got '${NODE_HOST:-}')" >&2; exit 64 ;;
esac

if [ ! -f "$APP_DIR/dist/server.js" ]; then
	echo "run-backend-node: $APP_DIR/dist/server.js missing — run the build first" >&2
	exit 66
fi

cd "$APP_DIR"
exec node dist/server.js

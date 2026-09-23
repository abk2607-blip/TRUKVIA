#!/bin/sh
# TRUKVIA · Phase 4 · Gate 9h · foreground entrypoint for the supervisord
# program `apps-api` (deploy/supervisor/apps-api.conf).
#
# Same shape as deploy/supervisor/run-backend-node.sh, for a different
# application: that one runs the read shadow, this one runs the NestJS Finance
# writer.
#
# * Loads configuration from the platform-provided, git-ignored
#   /app/apps/api/.env (secrets such as NEST_MONGO_URL and
#   TRUKVIA_INTERNAL_TOKEN never live in the repository or in the supervisor
#   file). No value read from it is ever echoed.
# * Refuses to start when a required variable is missing, so the application
#   can NEVER fall back to its built-in local development defaults. Those
#   defaults point at a local database; silently using one in production is the
#   failure this wrapper exists to prevent.
# * Refuses to start when the build output is missing.
# * `exec` keeps node in the FOREGROUND so supervisord owns the process
#   (restart on crash, SIGTERM on stop) — never an unmanaged background process.
set -eu

APP_DIR="${APP_DIR:-/app/apps/api}"
ENV_FILE="${APPS_API_ENV_FILE:-$APP_DIR/.env}"

if [ -f "$ENV_FILE" ]; then
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
fi

# Required by NAME only. `:?` prints the variable NAME and the message, never a
# value. Each of these has a local development default inside the application;
# demanding it here is what stops that default reaching production.
: "${NODE_ENV:?NODE_ENV must be set by the platform}"
: "${NEST_MONGO_URL:?NEST_MONGO_URL must be set by the platform}"
: "${NEST_MONGO_DB:?NEST_MONGO_DB must be set by the platform}"
: "${TRUKVIA_FIN_WRITER_ALLOWED_DB:?TRUKVIA_FIN_WRITER_ALLOWED_DB must be set by the platform}"
: "${PG_URL:?PG_URL must be set by the platform}"
: "${TRUKVIA_INTERNAL_TOKEN:?TRUKVIA_INTERNAL_TOKEN must be set by the platform}"
: "${PORT:?PORT must be set by the platform}"

# The application's own guard (apps/api/src/fin/writer-authorisation.ts) already
# requires these two to match exactly before it opens a connection. Checking it
# here as well only moves the failure earlier, to before node starts. NEITHER
# value is printed: the operator knows both, and a log file is the wrong place
# for either.
if [ "$TRUKVIA_FIN_WRITER_ALLOWED_DB" != "$NEST_MONGO_DB" ]; then
	echo "run-apps-api: TRUKVIA_FIN_WRITER_ALLOWED_DB does not match NEST_MONGO_DB (values not shown)" >&2
	exit 64
fi

# The reverse-bridge contract requires at least 32 characters; anything shorter
# fails closed inside the application. Length only — the token is never printed.
if [ "${#TRUKVIA_INTERNAL_TOKEN}" -lt 32 ]; then
	echo "run-apps-api: TRUKVIA_INTERNAL_TOKEN is shorter than 32 characters (value not shown)" >&2
	exit 64
fi

case "$PORT" in
	'' | *[!0-9]*)
		echo "run-apps-api: PORT must be a number (got '$PORT')" >&2
		exit 64
		;;
esac

# apps/api binds 127.0.0.1 in src/main.ts and takes no host variable today. This
# check is deliberately defensive: if one is ever introduced and points off
# loopback, the writer must refuse rather than start listening publicly.
for candidate in "${HOST:-}" "${NEST_HOST:-}"; do
	case "$candidate" in
		'' | 127.0.0.1 | ::1 | localhost) ;;
		*)
			echo "run-apps-api: host override must be a loopback address (got '$candidate')" >&2
			exit 64
			;;
	esac
done

# `npm start` is `node dist/src/main.js`; that path is what `nest build` with
# this tsconfig actually produces, and it is verified by apps/api/package.json.
if [ ! -f "$APP_DIR/dist/src/main.js" ]; then
	echo "run-apps-api: $APP_DIR/dist/src/main.js missing — run the build first" >&2
	exit 66
fi

cd "$APP_DIR"
exec node dist/src/main.js

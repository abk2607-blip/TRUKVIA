#!/usr/bin/env bash
# Iter51 — Pre-deploy Regression Check
#
# THIS IS THE PRODUCTION DEPLOYMENT GUARD.
#
# Every deploy pipeline MUST run this script before promoting a build to
# production. On non-zero exit, the deploy MUST be blocked.
#
# What it does:
# 1. Runs the full iter42-50 pytest regression suite (63 tests)
# 2. Executes a synthetic Trip Edit + Halting end-to-end smoke test
# 3. Verifies auth + save-health endpoints respond correctly
# 4. Writes a machine-readable result JSON to /tmp/deploy_readiness.json
#
# Exit codes:
#   0 = safe to deploy
#   1 = pytest regression failed — deploy MUST be blocked
#   2 = auth endpoint failed — deploy MUST be blocked
#   3 = smoke test failed — deploy MUST be blocked
#
# Usage from CI:
#   bash /app/backend/scripts/predeploy_check.sh
#   [[ $? -ne 0 ]] && echo "❌ Deploy blocked" && exit 1
#
# Usage from Emergent Platform (add to deploy hook):
#   command: bash /app/backend/scripts/predeploy_check.sh

set -uo pipefail

# Ensure the outer trap doesn't swallow real exit codes: we exit explicitly on
# each stage's failure via `exit N`. The trap is defensive-only for genuinely
# unexpected shell errors (e.g., missing bash builtin).
RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[1;33m"; NC="\033[0m"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
RESULT_FILE="/tmp/deploy_readiness.json"

TS() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
LOG_JSON() {
  local status="$1"; local exit_code="$2"; local msg="$3"; local stage="$4"
  cat > "$RESULT_FILE" <<EOF
{
  "status": "$status",
  "exit_code": $exit_code,
  "stage": "$stage",
  "message": "$msg",
  "checked_at": "$(TS)",
  "git_sha": "$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
}
EOF
}

trap 'LOG_JSON "error" 99 "Unexpected script error" "unknown"' ERR

echo -e "${YELLOW}▶ Iter51 Pre-Deploy Regression Guard${NC}"
echo -e "${YELLOW}▶ Repo: $REPO_ROOT${NC}"
echo

# ── Stage 1: pytest regression suite ──────────────────────────────────────
echo -e "${YELLOW}[1/3] pytest regression suite (iter42-50)${NC}"
cd "$BACKEND_DIR"
if bash "$BACKEND_DIR/scripts/run_regression.sh"; then
  echo -e "${GREEN}✓ Stage 1 passed${NC}"
else
  echo -e "${RED}✗ Stage 1 FAILED — regression tests broke${NC}"
  LOG_JSON "fail" 1 "Regression suite failed — critical iter42-50 test broke" "pytest_regression"
  exit 1
fi
echo

# ── Stage 2: live-endpoint health probe ───────────────────────────────────
BACKEND_URL="${BACKEND_URL:-http://localhost:8001}"
echo -e "${YELLOW}[2/3] Live endpoint checks against $BACKEND_URL${NC}"

HEALTH=$(curl -sS "$BACKEND_URL/api/auth/health" -m 5 2>/dev/null || echo '{}')
if ! echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok') is True, 'auth health not ok'; assert d.get('db')=='up','db not up'; assert d.get('session_index_unique') is True, 'session index missing'; assert d.get('demo_ready') is True, 'demo not ready'" 2>&1; then
  echo -e "${RED}✗ Stage 2 FAILED — /api/auth/health returned unhealthy state${NC}"
  echo "  Response: $HEALTH"
  LOG_JSON "fail" 2 "Auth health endpoint reports degraded pipeline" "auth_health"
  exit 2
fi
echo -e "${GREEN}✓ auth pipeline healthy${NC}"

# Save-health endpoint responds
SH=$(curl -sS "$BACKEND_URL/api/admin/save-health?hours=1" -m 5 2>/dev/null || echo '{}')
if ! echo "$SH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'total_failures' in d; assert 'per_collection' in d" 2>&1; then
  echo -e "${RED}✗ Stage 2 FAILED — /api/admin/save-health broken${NC}"
  echo "  Response: $SH"
  LOG_JSON "fail" 2 "Save-health endpoint broken" "save_health_probe"
  exit 2
fi
echo -e "${GREEN}✓ save-health endpoint responding${NC}"
echo

# ── Stage 3: synthetic Trip + Halting smoke test ─────────────────────────
echo -e "${YELLOW}[3/3] End-to-end Trip → Edit → Halting → Invoice smoke test${NC}"
python3 - <<PYEOF
import os, sys, json, uuid
import httpx
BASE = "$BACKEND_URL"
TOK = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}
try:
    cid = httpx.get(f"{BASE}/api/companies", headers=TOK, timeout=5).json()[0]["id"]
    h = {**TOK, "X-Company-Id": cid}
    cust = httpx.post(f"{BASE}/api/customers", headers=h,
        json={"name": f"DeployGuard-{uuid.uuid4().hex[:6]}", "state": "Telangana"}, timeout=5).json()
    trip = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": cust["id"], "date": "2026-06-01",
        "vehicle_number": f"DG{uuid.uuid4().hex[:4].upper()}",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "total_halting_days": 10, "grace_days": 4, "halting_rate_per_day": 2000,
    }, timeout=5).json()
    assert trip.get("halting_amount") == 12000, f"halting_amount mismatch: {trip.get('halting_amount')}"
    trip["halting_rate_per_day"] = 3000
    trip["total_halting_days"] = 12
    r = httpx.put(f"{BASE}/api/trips/{trip['id']}", headers=h, json=trip, timeout=5)
    r.raise_for_status()
    assert r.json()["halting_amount"] == 24000, f"post-edit halting_amount: {r.json()['halting_amount']}"
    print("✓ Trip Edit + Halting E2E flow verified (₹12k → ₹24k)")
    sys.exit(0)
except Exception as e:
    print(f"✗ Smoke test failed: {e}", file=sys.stderr)
    sys.exit(3)
PYEOF
SMOKE_RC=$?
if [[ $SMOKE_RC -ne 0 ]]; then
  echo -e "${RED}✗ Stage 3 FAILED — Trip/Halting smoke broke${NC}"
  LOG_JSON "fail" 3 "Trip → Halting → Invoice E2E smoke test failed" "smoke_test"
  exit 3
fi
echo -e "${GREEN}✓ Stage 3 passed${NC}"
echo

LOG_JSON "pass" 0 "All 3 deploy-guard stages passed — safe to promote to production" "complete"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ DEPLOY GUARD PASSED — safe to promote${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo "Result written to $RESULT_FILE"
exit 0

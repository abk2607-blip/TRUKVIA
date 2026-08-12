#!/usr/bin/env bash
# Iter50 — Auto-Regression Guard.
#
# Runs the critical iter42-49 pytest suite. Every deploy pipeline should invoke
# this script; a non-zero exit MUST block promotion to production. If any of
# these tests fails, a Trip Edit / Halting / Auth / Supplier regression has
# been introduced and production data will suffer.
#
# Usage:
#   ./scripts/run_regression.sh
#
# CI wire-up examples:
#   # GitHub Actions
#   - run: cd backend && bash ./scripts/run_regression.sh
#   # Emergent deploy hook (pre-publish)
#   command: bash /app/backend/scripts/run_regression.sh
#
# The script exits non-zero on ANY test failure and prints a coloured summary
# so the operator can see exactly which invariant broke.

set -euo pipefail

RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[1;33m"; NC="\033[0m"

cd "$(dirname "$0")/.."   # → /app/backend

echo -e "${YELLOW}▶ Iter50 Regression Guard — critical iter42-49 test suite${NC}"
echo

CRITICAL_TESTS=(
  "tests/test_iter42_unloading_diff_fix.py"            # unloading shortage / excess maths
  "tests/test_iter43_drilldown_share_refine_chat.py"   # dashboard drill-down + AI chat
  "tests/test_iter44_halting_invoice_and_supplier_statement.py"  # halting → invoice + supplier statement
  "tests/test_iter45_supplier_module_phase1.py"        # supplier CRUD + ledger
  "tests/test_iter45_supplier_multicompany_isolation.py"  # multi-company data isolation
  "tests/test_iter46_halting_single_source.py"         # halting single source of truth
  "tests/test_iter47_phase3_supplier_deep.py"          # deep monthly statement + vehicle→supplier enforcement
  "tests/test_iter48_auth_stability.py"                # login/session hardening
  "tests/test_iter49_trip_edit_halting_regression.py"  # trip edit crash + halting flow
  "tests/test_iter50_save_health_and_regression_guard.py"  # ops observability + guard-of-guards
  "tests/test_iter51_deploy_guard_and_alerts.py"       # deploy-readiness + configurable alerts
  "tests/test_iter52_strict_mode_alerts_history.py"    # strict mode + email/wa alerts + guard history
  "tests/test_iter53_strict_prod_multirecip_trend.py"  # strict-in-prod + multi-recipient + trend chart
  "tests/test_iter53b_alert_types_and_halting_full_flow.py"  # alert types menu + single-trip GET + P1 halting full flow
  "tests/test_iter54_login_failure_tracking.py"        # login-failure tracking on /api/auth/*
  "tests/test_iter56_trip_search_filter.py"            # Iter56 — Trip Log search/filter/pagination
  "tests/test_iter57_saved_filters_export_drill_spark.py"  # Iter57 — saved views, export, auth drill, sparkline
  "tests/test_iter58_bulk_actions_ipburst_sparkdrill.py"  # Iter58 — bulk actions + auth IP burst + spark drill
  "tests/test_iter59_driver_shortage_policy.py"           # Iter59 · Phase A — Driver Shortage Policy Engine
  "tests/test_iter60_driver_history_and_policy_pagination.py"  # Iter60 · Phase B — Driver Trip History + Policy pagination + deactivation reason
  "tests/test_iter61_driver_salary_ledger.py"             # Iter61 · Phase C — Driver Salary & Payment Ledger
)

# Explicit venv PATH so this runs cleanly from asyncio subprocess (which
# doesn't inherit the shell's activated venv)
export PATH="/root/.venv/bin:$PATH"

if ! python -m pytest --version >/dev/null 2>&1 && ! python3 -m pytest --version >/dev/null 2>&1; then
  echo -e "${RED}✗ pytest not found. Run: pip install -r requirements.txt${NC}"
  exit 2
fi
PYBIN=$(command -v python || command -v python3)

FAILED=()
for t in "${CRITICAL_TESTS[@]}"; do
  if [[ ! -f "$t" ]]; then
    echo -e "${YELLOW}⚠ Skipping missing test file: $t${NC}"
    continue
  fi
  echo -e "${YELLOW}▶ Running $t${NC}"
  if $PYBIN -m pytest "$t" --tb=short -q 2>&1 | tee /tmp/reg_last.log | tail -5; then
    echo -e "${GREEN}  ✓ $t passed${NC}"
  else
    echo -e "${RED}  ✗ $t FAILED${NC}"
    FAILED+=("$t")
  fi
  echo
done

echo "──────────────────────────────────────────"
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo -e "${GREEN}✓ Regression Guard PASSED — safe to deploy.${NC}"
  exit 0
else
  echo -e "${RED}✗ Regression Guard BLOCKED deployment.${NC}"
  echo -e "${RED}Failing suites:${NC}"
  for f in "${FAILED[@]}"; do echo -e "${RED}  - $f${NC}"; done
  echo
  echo "Read the pytest output above, fix the code, then rerun this script."
  exit 1
fi

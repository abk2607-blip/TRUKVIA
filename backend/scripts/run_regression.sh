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
  "tests/test_iter63_supplier_vehicle_master.py"          # Iter63 · Supplier Vehicle Master integration + Active/Inactive
  "tests/test_iter64_supplier_chip_vehicle_audit_bulk_import.py"  # Iter64 · Supplier chip + Vehicle status audit + Bulk import
  "tests/test_iter65_halting_verify.py"                   # Iter65 · Halting Live Verification endpoint contract
  "tests/test_iter66_ship_sites_and_customer_ref.py"      # Iter66 · Ship-To sites + Trip customer reference number
  "tests/test_iter67_invoice_pdf_ship_to_ref.py"          # Iter67 · Invoice PDF · BILL TO | SHIP TO + Customer Ref column
  "tests/test_iter68_customer_search.py"                  # Iter68 · Server-side Customer Search + tenant isolation
  "tests/test_iter72_quickadd_sync.py"                    # Iter72 · Ship-To / Vehicle / Supplier quick-add sync + dedup
  "tests/test_iter73_supplier_freight_lr_perf.py"         # Iter73 · Supplier Freight auto-calc, LR Consignee, suppliers-dashboard perf
  "tests/test_iter74_supplier_shortage_integration.py"    # Iter74 · Trip shortage → Supplier ledger/settlement auto-flow
  "tests/test_iter81_customer_search_fixture_bypass.py"   # Iter81 · Customer search bypasses fixture-hide when q is provided
  "tests/test_iter82_invoice_cust_ref_column.py"          # Iter82 · Per-trip Customer Ref column in Invoice PDF + view
  "tests/test_iter83_trips_list_cust_ref.py"              # Iter83 · Cust Ref column in main Trips list
  "tests/test_iter84_missing_cust_ref_filter.py"          # Iter84 · Server-side "Missing Cust Ref" trips filter
  "tests/test_iter85_inline_cust_ref_fill.py"             # Iter85 · One-click inline Cust Ref fill (PATCH endpoint)
  "tests/test_iter86_historical_isolation.py"             # Iter86 · Historical Isolation Layer — imports don't leak into live aggregations
  "tests/test_iter89_phase1_policy_snapshot.py"           # Iter89 Phase 1 · Customer/Product/Supplier policy snapshot on Trip create
  "tests/test_iter98_phase3_shortage_engine.py"           # Iter98 Phase 3 · Central Shortage Engine (customer + supplier independent)
  "tests/test_iter102_ui_formula_parity.py"               # Iter102 · Freight Calculation Formula & UI parity
  "tests/test_iter103_shortage_simplification_and_editable_amounts.py"  # Iter103 · Shortage simplification + editable amounts
  "tests/test_iter104b_customer_view_profile_policy.py"   # Iter104b · Customer view (profile + policy)
  "tests/test_iter105_policy_change_workflow.py"          # Iter105 Phase A · Customer Policy Change Preview + Apply
  "tests/test_iter105b_policy_change_revert.py"           # Iter105 Phase B · Revert with mandatory reason + invoice-safety block
  "tests/test_iter106_auth_stability_fixes.py"            # Iter106 · Auth stability (401 relaunch, session-dead)
  "tests/test_iter106b_auth_bootstrap_resilience.py"      # Iter106b · Auth bootstrap resilience backend contract
  "tests/test_iter107_invoice_shortage_allowance_caption.py"  # Iter107 · Invoice shortage allowance caption
  "tests/test_iter108_multi_company_logo_isolation.py"    # Iter108 · Multi-company logo upload + isolation
  "tests/test_iter109_bulk_lr_regenerate.py"              # Iter109 · Bulk LR regenerate + ZIP
  "tests/test_iter111_supplier_freight_and_shortage.py"   # Iter111 · Supplier freight basis + shortage threshold + override + audit
)

export PATH="/root/.venv/bin:$PATH"

if ! python -m pytest --version >/dev/null 2>&1 && ! python3 -m pytest --version >/dev/null 2>&1; then
  echo -e "${RED}✗ pytest not found. Run: pip install -r requirements.txt${NC}"
  exit 2
fi
PYBIN=$(command -v python || command -v python3)

# Iter116 · Batch runner. Previously this loop invoked `pytest {file}` once
# per file, incurring ~2s of pytest startup × 49 files ≈ 100 s of pure
# startup overhead on top of the actual test time — which pushed the total
# past the 600 s deploy-guard timeout even though individual files were
# fast. Running all critical files in a SINGLE pytest invocation lets
# pytest-xdist (configured in pytest.ini as `-n 2 --dist loadscope`)
# parallelise across the files with a single startup, cutting total wall
# time to well under the 600 s cap. The exit code is preserved so the
# deploy guard sees `fail` on any failure.
#
# Filter the declared list to files that actually exist (some Iter42-49
# suites may have been retired). Preserves the "skipping missing" note.
EXISTING=()
for t in "${CRITICAL_TESTS[@]}"; do
  if [[ ! -f "$t" ]]; then
    echo -e "${YELLOW}⚠ Skipping missing test file: $t${NC}"
  else
    EXISTING+=("$t")
  fi
done

echo -e "${YELLOW}▶ Running ${#EXISTING[@]} critical suites in a single pytest invocation (xdist × 2 workers)${NC}"
echo

if $PYBIN -m pytest "${EXISTING[@]}" --tb=short -q 2>&1 | tee /tmp/reg_last.log | tail -30; then
  echo
  echo "──────────────────────────────────────────"
  echo -e "${GREEN}✓ Regression Guard PASSED — safe to deploy.${NC}"
  exit 0
else
  echo
  echo "──────────────────────────────────────────"
  echo -e "${RED}✗ Regression Guard BLOCKED deployment.${NC}"
  echo -e "${RED}See /tmp/reg_last.log or the tail above for the failing suite(s).${NC}"
  echo
  echo "Read the pytest output above, fix the code, then rerun this script."
  exit 1
fi

"""Iter147 P0 UAT-fix (2026-09-09) · Preview modal usability.

Focus: purely UI. No parser / duplicate / accounting logic tests here —
those live in test_iter147_iocl_parser.py / test_iter147_bpcl_parser.py /
test_iter147_import_flow.py and remain untouched.

Guardrails asserted here:
  1. Wizard modal uses the larger desktop-friendly shell classes
     (w-[95vw] + h-[85vh]) so operators can read IOCL/BPCL rows.
  2. The mapping column reuses the shared shadcn SearchableSelect
     combobox — the same component used by Quick Op / Expense Register.
  3. A single saveMapping() call updates the `rowMaps` state keyed by
     `source_vehicle_ref`, so mapping one row applies to every row with
     the same source_vehicle_ref via rowsForCommit's rowMaps lookup.
  4. FuelVehicleMap persistence contract is unchanged.
  5. Bucket tabs (5 states) remain present.
"""
from pathlib import Path

WIZ = Path("/app/frontend/src/components/fuel/FuelImportWizard.jsx")


def _src():
    return WIZ.read_text(encoding="utf-8")


# ── 1 · Larger modal shell ─────────────────────────────────────────────
def test_wizard_modal_is_desktop_friendly():
    s = _src()
    # New shell classes (approx 95vw × 85vh, capped at 1600px).
    assert 'data-testid="fuel-import-wizard-shell"' in s
    assert "w-[95vw]" in s, "modal must be ~95% viewport width"
    assert "h-[85vh]" in s, "modal must be ~85% viewport height"
    # Old too-small class must be gone from the shell.
    assert "max-w-6xl" not in s or "max-w-[1600px]" in s, \
        "shell should use the wider 1600px cap, not the old 6xl"


# ── 2 · Reuses the shared SearchableSelect (not a bespoke dropdown) ───
def test_wizard_uses_shared_searchable_select():
    s = _src()
    assert 'from "@/components/ui/searchable-select"' in s, \
        "must reuse the existing TRUKVIA SearchableSelect component"
    assert "<SearchableSelect" in s, "vehicle mapping column must use SearchableSelect"
    assert 'placeholder="Search TRUKVIA vehicle…"' in s
    # No plain <select> for the mapping column any more.
    src_mapping_block = s.split("min-w-[240px]")[1].split("</td>")[0]
    assert "<select" not in src_mapping_block, \
        "mapping cell must no longer use a plain <select> dropdown"


# ── 3 · One mapping applies to all matching rows via rowMaps ──────────
def test_mapping_applies_to_repeated_source_vehicle_refs():
    s = _src()
    # State keyed by source_vehicle_ref (not row_index) → naturally reuses.
    assert "setRowMaps((m) => ({ ...m, [sref]:" in s or \
        "setRowMaps((m) => ({" in s and "[sref]:" in s
    # rowsForCommit consults rowMaps by source_vehicle_ref (single lookup)
    assert "rowMaps[r.source_vehicle_ref]" in s
    # saveMapping receives (source_vehicle_ref, vehicleId) — single call point.
    assert "const saveMapping = async (sref, vehicleId)" in s
    # It POSTs the durable mapping to /fuel/vehicle-maps.
    assert '"/fuel/vehicle-maps"' in s or "'/fuel/vehicle-maps'" in s


# ── 4 · Persistence contract intact (FuelVehicleMap API unchanged) ────
def test_fuel_vehicle_map_api_untouched():
    router = Path("/app/backend/routers/fuel_import.py").read_text(encoding="utf-8")
    # The three original endpoints must still exist and unchanged in path.
    assert '@router.get("/fuel/vehicle-maps")' in router
    assert '@router.post("/fuel/vehicle-maps")' in router
    assert '@router.delete("/fuel/vehicle-maps/{fvm_id}")' in router


# ── 5 · All 5 bucket tabs still rendered ──────────────────────────────
def test_five_bucket_tabs_present():
    s = _src()
    # The bucket tab testIds are emitted via template literal
    # `bucket-${k}` — assert BUCKET_META still defines all 5 keys and
    # the render loop still emits data-testid based on that key.
    for key in ("ready", "vehicle_mapping_required", "possible_duplicate",
                "exact_duplicate", "error"):
        assert f'{key}:' in s, f"BUCKET_META key {key!r} must remain"
    assert 'data-testid={`bucket-${k}`}' in s, \
        "bucket tab render must expose data-testid=`bucket-<key>`"


# ── 6 · Parser / duplicate / accounting service files unchanged ──────
def test_service_file_parser_and_duplicate_logic_untouched():
    """The UAT-fix is UI-only; guard against accidental server drift."""
    svc = Path("/app/backend/services_fuel_import.py").read_text(encoding="utf-8")
    # Anchor phrases that must stay stable — canonical accounting rules.
    assert "ONE canonical Expense" in svc
    assert 'source_type="fleet_card_import"' in svc
    # Never a paired db.fuel write on import.
    assert "No paired db.fuel" in svc
    # XOR-safe scan for Trip legacy Diesel is preserved.
    assert 'has_canonical_expenses' in svc

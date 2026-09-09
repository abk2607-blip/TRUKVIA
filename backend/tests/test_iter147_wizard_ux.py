"""Iter147 P0 CRITICAL BUG FIX (2026-09-09) · Row-scoped vehicle mapping.

Regression guard for the DATA-INTEGRITY BLOCKER reported in live UAT:
assigning a TRUKVIA vehicle to one preview row must NEVER propagate to
another row, even when both rows share the same source_vehicle_ref.

These are STATIC source-inspection tests — they read the wizard source
file and assert the state key / state-mutation invariants. Behaviour
tests (Playwright) run separately in the smoke run.
"""
import re
from pathlib import Path

WIZ = Path("/app/frontend/src/components/fuel/FuelImportWizard.jsx")


def _src():
    return WIZ.read_text(encoding="utf-8")


# ── 1 · State is keyed by row_index, NEVER by source_vehicle_ref ────────
def test_state_is_row_scoped_not_source_ref_scoped():
    s = _src()
    # The old, buggy state variable must be gone.
    assert "rowMaps" not in s, "old source-ref-keyed rowMaps must be removed"
    # The new state variable is present.
    assert "rowSelections" in s
    assert "setRowSelections" in s
    # Comment anchor documenting the design invariant.
    assert "ROW-SCOPED" in s, "code must document row-scoped invariant"
    # The commit derivation reads per-row selection (not source-ref).
    assert "rowSelections[r.row_index]" in s


# ── 2 · Setter mutates only the caller's row_index ─────────────────────
def test_select_vehicle_only_touches_one_row():
    s = _src()
    # selectVehicleForRow implementation must set state via a functional
    # update, adding a new key that IS the row_index — no scan by
    # source_vehicle_ref anywhere in the state update.
    fn = re.search(
        r"const selectVehicleForRow = \([^)]*\) => \{(.*?)\n  \};",
        s, flags=re.S,
    )
    assert fn, "selectVehicleForRow definition missing"
    body = fn.group(1)
    assert "[rowIndex]" in body, \
        "setter must write to the exact row_index (no source-ref rewriting)"
    # It must NOT walk over other rows.
    assert "preview.rows" not in body, \
        "setter must not touch other rows"
    # It must NOT key by source_vehicle_ref.
    assert re.search(r"\[sref\]\s*:\s*\{", body) is None, \
        "setter must not write per-source-ref state that would fan out"


# ── 3 · clearRowSelection removes only that row ────────────────────────
def test_clear_row_selection_is_scoped():
    s = _src()
    fn = re.search(
        r"const clearRowSelection = \(rowIndex\) => \{(.*?)\n  \};",
        s, flags=re.S,
    )
    assert fn, "clearRowSelection is required for the 'Clear Row A only' UAT case"
    body = fn.group(1)
    assert "delete copy[rowIndex]" in body, \
        "clear must remove only the caller's row_index"


# ── 4 · SearchableSelect binds value/onChange to per-row identity ──────
def test_searchable_select_is_per_row_bound():
    s = _src()
    # Value must read from the per-row selection map.
    assert 'value={sel?.vehicle_id || ""}' in s
    # testId must include the row_index so DOM identity is per-row.
    assert 'testId={`map-select-${r.row_index}`}' in s
    # onChange must dispatch to selectVehicleForRow with r.row_index.
    assert "selectVehicleForRow(r.row_index" in s


# ── 5 · Persistent FuelVehicleMap upsert is OPT-IN, not automatic ──────
def test_persistent_mapping_is_opt_in():
    s = _src()
    # Checkbox controls whether we POST to /fuel/vehicle-maps.
    assert 'data-testid={`persist-${r.row_index}`}' in s, \
        "each row must have its own opt-in persistence checkbox"
    # POST only fires when `persistHint` is truthy.
    assert "if (persistHint" in s, \
        "persistent map upsert must be gated on the operator's opt-in"


# ── 6 · Commit payload reads THIS row's selection (never a sibling's) ──
def test_commit_payload_is_row_scoped():
    s = _src()
    # rowsForCommit map function must apply the per-row selection first —
    # if `sel` exists for r.row_index, use it verbatim; otherwise leave the
    # row alone (server auto-resolution still applies if the persistent
    # FuelVehicleMap resolved it, which is an operator-approved case).
    block = re.search(
        r"const rowsForCommit = useMemo\(\(\) => \{(.*?)\n  \}, \[preview, overrides, rowSelections\]\);",
        s, flags=re.S,
    )
    assert block, "rowsForCommit useMemo must depend ONLY on preview/overrides/rowSelections"
    body = block.group(1)
    assert "rowSelections[r.row_index]" in body
    # No cross-row leakage patterns.
    assert "source_vehicle_ref" not in body, \
        "commit derivation must not group/dedupe rows by source_vehicle_ref"


# ── 7 · No lingering rowMaps import/reference (dead-state audit) ──────
def test_no_lingering_rowmaps_references():
    s = _src()
    assert "rowMaps" not in s
    assert "setRowMaps" not in s


# ── 8 · Same source_vehicle_ref allowed to have different row vehicles ─
def test_same_sref_can_have_different_row_vehicles():
    s = _src()
    # The invariant is proved by state being keyed by row_index — assert
    # the state store has no path that overwrites siblings.
    # (Runtime proof: playwright smoke picks different vehicles for two
    # rows carrying identical source_vehicle_ref — see UAT recording.)
    assert "rowSelections[r.row_index]" in s
    # And the persistent map upsert is not a synchronous state mutation
    # that could bleed into other rows.
    assert "persistedSrefs" in s

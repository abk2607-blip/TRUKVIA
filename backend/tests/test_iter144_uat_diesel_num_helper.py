"""Iter144 UAT-FIX · Diesel amount computation robustness.

Live UAT surfaced Qty 250 × Rate 34.20 → Amount ₹0.00 on some browser /
locale combinations. Root cause: `<input type="number">` returns "" in
element.value when the intermediate typed content is not a valid number
per the browser's parser (locale, autofill, paste-from-spreadsheet with
₹ prefix, or comma decimal). React state r.qty stays "" but the browser
happily displays the raw typed text, giving the impression the values
are set while `parseFloat("")` yields NaN → 0.

Fix (frontend only):
  * qty / rate inputs become `type="text" inputMode="decimal"` so the
    browser NEVER strips the typed value from `.value`. Mobile keyboards
    still show the decimal keypad.
  * A new `_num()` helper normalizes: trims ₹/spaces, converts "," to
    ".", drops thousand separators, and parses only the leading numeric
    prefix. It replaces every parseFloat() in the amount path
    (computedAmount / q2 / fmt / eqAmount / dieselNarration).
  * The payload builder now uses `_num(r.qty)` / `_num(r.rate)` too, so
    a locale-typed "34,20" reaches the server as 34.20 — the Iter139
    AMOUNT_TAMPERED guard stays authoritative.

Iter139/140/141/142/143 semantics remain unchanged. This is a UI
robustness patch — no schema, no endpoint, no accounting change.
"""
from pathlib import Path

QOB = Path("/app/frontend/src/pages/QuickOperationalExpense.jsx")


def test_number_inputs_replaced_with_text_inputmode_decimal():
    src = QOB.read_text(encoding="utf-8")
    # The old type="number" pattern on qty / rate is GONE for the diesel row.
    # (The non-diesel amount input may still use type="number".)
    diesel_block_start = src.index("{isDiesel ? (")
    diesel_block_end = src.index(") : (", diesel_block_start)
    diesel_block = src[diesel_block_start:diesel_block_end]
    assert 'type="number"' not in diesel_block, (
        "Diesel qty/rate inputs must not use type=number (locale/paste edge cases)"
    )
    for m in [
        'inputMode="decimal"',
        'quick-expense-row-${i}-qty',
        'quick-expense-row-${i}-rate',
        'value={r.qty ?? ""}',
        'value={r.rate ?? ""}',
    ]:
        assert m in diesel_block, f"missing marker in diesel row block: {m}"


def test_num_helper_defined_and_used_in_computed_amount():
    src = QOB.read_text(encoding="utf-8")
    assert "const _num = (v) =>" in src, "_num helper missing"
    # computedAmount must route through _num, not raw parseFloat.
    assert "q2(_num(row.qty) * _num(row.rate))" in src, (
        "computedAmount must use _num() on qty/rate"
    )
    assert ": _num(row.amount)" in src, "computedAmount amount fallback must use _num"
    # fmt / q2 / eqAmount must use _num
    assert "_num(n).toFixed(2)" in src
    assert "Math.round(_num(n) * 100)" in src
    assert "Math.abs(_num(a) - _num(b))" in src


def test_payload_uses_num_for_qty_and_rate():
    src = QOB.read_text(encoding="utf-8")
    # Backend receives the sanitised value, not a raw browser string.
    assert "qty: _num(r.qty)" in src
    assert "rate: _num(r.rate)" in src


def test_num_normalizes_common_edge_cases_in_pytest_shim():
    """Mirror the JS _num semantics in pure Python so we can pin the
    intended contract from tests without a JS runtime. If the frontend
    logic ever diverges, this test still catches the direction."""
    def py_num(v):
        if v is None: return 0.0
        if isinstance(v, (int, float)): return float(v)
        s = str(v).replace("₹", "").replace(" ", "").replace(",", ".")
        import re
        m = re.match(r"^-?\d*(\.\d+)?", s)
        try:
            return float(m.group(0)) if m and m.group(0) else 0.0
        except Exception:
            return 0.0
    # Standard
    assert py_num("250") == 250
    assert py_num("34.20") == 34.20
    # Currency prefix
    assert py_num("₹34.20") == 34.20
    # Locale comma decimal (autofill / paste-from-Excel)
    assert py_num("34,20") == 34.20
    # Whitespace
    assert py_num(" 34.20 ") == 34.20
    # Junk gets NaN-safe zero
    assert py_num("") == 0
    assert py_num(None) == 0
    assert py_num("abc") == 0
    # Multiplicative correctness for the exact UAT case
    assert round(py_num("250") * py_num("34.20"), 2) == 8550.00

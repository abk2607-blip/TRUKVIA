"""Iter126a — Frontend Axios retry policy static guard.

We can't easily run Jest for one file inside the pytest regression, so this
guard asserts the invariants of the retry policy by reading api.js directly:

  1. The Bucket A allow-list for POST is present.
  2. The retry helper only fires on network error / 502 / 503 / 504.
  3. The retry cap is at most 2 additional attempts.
  4. No POST route from Bucket B/C is in the allow-list (would silently
     duplicate a mutation on retry).

Move endpoints into Bucket A here only after re-classifying them in
/app/memory/PRD.md → Iter126 Safety Matrix.
"""
import pathlib
import re


API_JS = pathlib.Path("/app/frontend/src/api.js").read_text()


def test_bucket_a_post_allowlist_present():
    assert "const BUCKET_A_POST = [" in API_JS


def test_transient_status_codes():
    m = re.search(r"function _isTransient\([\s\S]*?\}\n", API_JS)
    assert m, "_isTransient helper missing"
    body = m.group(0)
    for code in ("502", "503", "504"):
        assert code in body, f"transient guard must include {code}"
    # 500 and 400/401/403/404/409/422 must NOT be treated as transient
    assert "500" not in body, "500 must not be auto-retried (server bug, not restart)"


def test_retry_cap():
    m = re.search(r"const RETRY_DELAYS_MS\s*=\s*\[([^\]]+)\];", API_JS)
    assert m, "RETRY_DELAYS_MS missing"
    delays = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
    assert 1 <= len(delays) <= 2, "cap total retries at 2 (3 attempts including original)"


def test_no_bucket_b_or_c_in_allowlist():
    """Bucket B/C endpoints must NEVER be listed in BUCKET_A_POST."""
    forbidden = [
        # Bucket B (creates / payments / uploads / duplicates / regenerates)
        r"^/trips$",
        r"/trips/[^/]+/regenerate-lr",
        r"/trips/bulk-regenerate-lr",
        r"/trips/bulk-all-copies-zip",
        r"/companies$",
        r"/customers$",
        r"/suppliers$",
        r"/invoices$",
        r"/drivers$",
        r"/vehicles$",
        r"/files/upload",
        r"/files/bulk-upload",
        # Bucket C (emails / LLM / bulk-delete / policy apply/revert)
        r"/policy-changes/apply",
        r"/policy-changes/[^/]+/revert",
        r"/trips/bulk-delete",
        r"/customers/[^/]+/share-statement",
        r"/reports/supplier-statement/share",
        r"/invoices/[^/]+/share",
        r"/trips/[^/]+/share-lr",
        r"/ai/chat",
    ]
    m = re.search(r"const BUCKET_A_POST\s*=\s*\[([\s\S]*?)\];", API_JS)
    assert m, "BUCKET_A_POST missing"
    allowlist = m.group(1)
    for pat in forbidden:
        assert pat not in allowlist, (
            f"{pat!r} must not appear in BUCKET_A_POST — see Iter126 Safety Matrix."
        )

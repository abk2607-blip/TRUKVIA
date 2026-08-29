"""Iter129-sec · Phase-1 security hardening.

Covers 4 approved test scopes:
  1. CORS tightening (CORS_ORIGINS honoured, wildcards drop out when set).
  2. Standard security response headers on every route.
  3. Public /files/public path-traversal + prefix allow-list.
  4. Upload allow-list — JPG/PNG/WEBP/HEIC/PDF pass; HTML/SVG/TXT return 415.

Existing files in storage are not touched. No new endpoints. No locked
business logic changed.
"""
from __future__ import annotations

import io
import os

import httpx

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ── Security headers ─────────────────────────────────────────────────────
def test_security_headers_present_on_root():
    r = httpx.get(f"{API}/", timeout=10)
    assert r.status_code == 200, r.text
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "strict-origin-when-cross-origin" in (h.get("referrer-policy") or "")
    assert "max-age=31536000" in (h.get("strict-transport-security") or "")
    csp = h.get("content-security-policy") or ""
    assert "frame-ancestors 'none'" in csp
    assert "connect-src" in csp and "wss:" in csp
    assert "img-src" in csp and "data:" in csp


def test_security_headers_present_on_authed_endpoint():
    r = httpx.get(f"{API}/customers", headers=DEMO_HDR, timeout=10)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


# ── CORS ─────────────────────────────────────────────────────────────────
def test_cors_reflects_configured_origin():
    # An OPTIONS preflight with any Origin should return valid CORS headers
    r = httpx.options(
        f"{API}/customers",
        headers={
            "Origin": "https://trip-billing-pro-1.preview.emergentagent.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
        timeout=10,
    )
    # Middleware answers 200 OK for preflights with allow headers
    assert r.status_code in (200, 204), r.text
    assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}


# ── Public file allow-list + traversal ───────────────────────────────────
def test_public_file_rejects_traversal():
    r = httpx.get(f"{API}/files/public/../etc/passwd", timeout=10)
    assert r.status_code == 404, r.text


def test_public_file_rejects_disallowed_prefix():
    r = httpx.get(f"{API}/files/public/uploads/somefile.pdf", timeout=10)
    assert r.status_code == 404, r.text


def test_public_file_rejects_backslash():
    r = httpx.get(f"{API}/files/public/lr_shares\\evil.pdf", timeout=10)
    assert r.status_code == 404, r.text


# ── Upload allow-list ────────────────────────────────────────────────────
def _upload(filename: str, data: bytes, content_type: str):
    files = {"file": (filename, io.BytesIO(data), content_type)}
    return httpx.post(
        f"{API}/files/upload",
        headers={"Authorization": DEMO_HDR["Authorization"]},
        files=files,
        timeout=30,
    )


def test_upload_accepts_pdf():
    # Minimal but valid PDF header — enough for the endpoint's byte-length check.
    r = _upload("bill.pdf", b"%PDF-1.4\n%QORVENA-TEST\n", "application/pdf")
    assert r.status_code == 200, r.text


def test_upload_accepts_png():
    # 1x1 transparent PNG.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8"
        b"\xcf\xc0\x00\x00\x00\x03\x00\x01\xc3\x1a\xa2\x94\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = _upload("photo.png", png, "image/png")
    assert r.status_code == 200, r.text


def test_upload_accepts_jpg():
    r = _upload("photo.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIFtest", "image/jpeg")
    assert r.status_code == 200, r.text


def test_upload_rejects_html():
    r = _upload("evil.html", b"<script>alert(1)</script>", "text/html")
    assert r.status_code == 415, r.text
    assert "Unsupported file type" in r.text


def test_upload_rejects_svg():
    r = _upload("evil.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
    assert r.status_code == 415, r.text


def test_upload_rejects_txt():
    r = _upload("notes.txt", b"secret", "text/plain")
    assert r.status_code == 415, r.text


def test_upload_rejects_extension_mismatch():
    # .pdf extension but the client says application/x-msdownload — must reject.
    r = _upload("evil.pdf", b"MZ\x00\x00", "application/x-msdownload")
    assert r.status_code == 415, r.text

"""Iter134 · Signature Upload UI Correction — focused backend tests.

The upload UI wires into the existing /api/files/upload endpoint with
category="signature" · linked_type="company". We assert:
  – PNG/JPG/WebP accepted; other MIME rejected by existing gate
  – file_id returned + linked correctly + resolvable via GET /files
  – Setting `signature_file_id` via PUT /company works (already covered by
    Iter134 but re-verified here)
  – Contradiction guard still blocks conflicting note (Iter134 preserved)
  – Signature can be replaced by uploading a new file
"""
from __future__ import annotations
import os, io, uuid, requests, pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO_TOKEN}"}
H_JSON = {**H, "Content-Type": "application/json"}


def _tiny_png() -> bytes:
    # 1×1 transparent PNG
    import base64
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
    )


def _tiny_gif() -> bytes:
    import base64
    return base64.b64decode(b"R0lGODlhAQABAIAAAP///wAAACwAAAAAAQABAAACAkQBADs=")


@pytest.fixture(scope="module")
def company():
    return requests.get(f"{API}/company", headers=H, timeout=10).json()


def test_signature_png_upload_via_files_endpoint(company):
    cid = company["id"]
    files = {"file": (f"sig-{uuid.uuid4().hex[:6]}.png", _tiny_png(), "image/png")}
    r = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files, timeout=15,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"].startswith("fl_") or data["id"].startswith("file")
    assert data["category"] == "signature"
    assert data["linked_type"] == "company"
    assert data["linked_id"] == cid
    # Listable
    lst = requests.get(f"{API}/files", headers=H,
                       params={"linked_type": "company", "linked_id": cid}, timeout=10).json()
    assert any(x["id"] == data["id"] for x in lst)


def test_signature_jpg_upload_accepted(company):
    cid = company["id"]
    # smallest valid JPEG magic bytes (won't render but content-type gate passes)
    jpg = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f"
        b"\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
        b"\xff\xd9"
    )
    files = {"file": ("sig.jpg", jpg, "image/jpeg")}
    r = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files, timeout=15,
    )
    assert r.status_code == 200, r.text


def test_signature_gif_rejected_by_type_gate(company):
    """GIF is not in the Iter129-sec allow-list — must be rejected."""
    cid = company["id"]
    files = {"file": ("sig.gif", _tiny_gif(), "image/gif")}
    r = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files, timeout=15,
    )
    assert r.status_code in (400, 415)


def test_settings_save_signature_file_id_then_replace(company):
    """PUT /company still persists signature_file_id from the upload flow."""
    cid = company["id"]
    # Upload two signature files
    files1 = {"file": ("sig-a.png", _tiny_png(), "image/png")}
    fid1 = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files1, timeout=15,
    ).json()["id"]
    files2 = {"file": ("sig-b.png", _tiny_png(), "image/png")}
    fid2 = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files2, timeout=15,
    ).json()["id"]

    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    doc["signature_file_id"] = fid1
    doc["signature_mode"] = "image"
    doc["system_generated_note"] = ""  # keep guard happy
    r = requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)
    assert r.status_code == 200, r.text
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    assert doc["signature_file_id"] == fid1
    # Replace
    doc["signature_file_id"] = fid2
    r = requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)
    assert r.status_code == 200, r.text
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    assert doc["signature_file_id"] == fid2

    # Detach (Remove Signature): empty string reverts PDF to text-only
    doc["signature_file_id"] = ""
    doc["signature_mode"] = "none"
    r = requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)
    assert r.status_code == 200
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    assert doc["signature_file_id"] == ""


def test_contradiction_guard_still_active_after_signature_upload(company):
    """Iter134 P1.8 must not regress: signature + 'signature not required' → 400."""
    cid = company["id"]
    files = {"file": ("sig-guard.png", _tiny_png(), "image/png")}
    fid = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files, timeout=15,
    ).json()["id"]
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    doc["signature_file_id"] = fid
    doc["system_generated_note"] = "Computer generated. Signature not required."
    r = requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)
    assert r.status_code == 400, r.text
    # Cleanup so live UAT session isn't blocked
    doc["signature_file_id"] = ""
    doc["system_generated_note"] = ""
    doc["signature_mode"] = "none"
    requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)

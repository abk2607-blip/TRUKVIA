"""Phase 4 · Gate 9g · controllable fake Node upstream for failure rehearsal.

Usage: python fake_upstream.py <port> <state_dir>
Reads <state_dir>/mode before every response and appends one line per accepted
connection to <state_dir>/hits. Modes:
  ok       200 JSON `{"fake":"node"}`            (genuine Node success)
  g404     404 `{"detail":"Vendor not found"}`  (genuine Node 4xx — must pass through)
  g500     500 text/plain Internal Server Error  (genuine Node 500 — must pass through)
  s502 / s503 / s504 / s431                       (infrastructure statuses → fallback)
  hang     accept, read the request, never answer (read timeout → fallback)
  garbage  answer with non-HTTP bytes             (protocol error → fallback)
  close    close the socket without answering     (protocol error → fallback)
"""
import asyncio
import sys
from pathlib import Path

PORT = int(sys.argv[1])
STATE = Path(sys.argv[2])
STATUS = {"ok": (200, "OK", b'{"fake":"node"}', "application/json"),
          "g404": (404, "Not Found", b'{"detail":"Vendor not found"}', "application/json"),
          "g500": (500, "Internal Server Error", b"Internal Server Error", "text/plain; charset=utf-8"),
          "s502": (502, "Bad Gateway", b"bad gateway", "text/plain"), "s503": (503, "Service Unavailable", b"x", "text/plain"),
          "s504": (504, "Gateway Timeout", b"x", "text/plain"), "s431": (431, "Request Header Fields Too Large", b"", "text/plain")}


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    mode = (STATE / "mode").read_text().strip() if (STATE / "mode").exists() else "ok"
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except Exception:
        writer.close()
        return
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    with open(STATE / "hits", "a", encoding="utf-8") as f:
        f.write(f"{mode}\t{line}\n")
    if mode == "hang":
        await asyncio.sleep(3600)
    elif mode == "garbage":
        writer.write(b"\x00\x01NOT-HTTP\r\n\r\n")
    elif mode == "close":
        pass
    else:
        code, reason, body, ctype = STATUS[mode]
        writer.write(f"HTTP/1.1 {code} {reason}\r\ncontent-type: {ctype}\r\ncontent-length: {len(body)}\r\n"
                     f"connection: close\r\n\r\n".encode() + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def main() -> None:
    server = await asyncio.start_server(handle, "127.0.0.1", PORT)
    async with server:
        await server.serve_forever()


asyncio.run(main())

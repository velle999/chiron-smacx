#!/usr/bin/env python3
"""
chiron-bridge — HTTP front end for synapd, for the Chiron Rising SMACX mod.

The mod's DLL runs inside Wine and can only speak plain TCP/HTTP. synapd speaks
a binary framed protocol over a unix socket. This bridges the two.

    POST /generate   {"prompt": "...", "max_tokens": 400}  ->  {"text": "..."}
    GET  /health                                           ->  {"ok": true}

Bound to 127.0.0.1 only. synapd's wire protocol has no authentication, so this
must never listen on a routable address -- see synapd-bridge.socket for the
same reasoning applied to the LAN bridge.

Stdlib only, so it can run anywhere the game runs.
"""
import argparse
import json
import os
import socket
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── synapd wire protocol (mirrors SYNAPSE/synapd/include/synapd.h) ──────────
_HDR = struct.Struct("<IBBHIIIQ")   # magic ver type flags len req_id pid ts
_MAGIC = 0x53594E41                 # "SYNA"
_VER = 1
_MSG_QUERY = 0x01
_MSG_ERROR = 0xFF

SYN_QF_RAW = 0x8000                 # bypass the built-in Synapse persona
SYN_QF_TOKENS_MASK = 0x7FFF

DEFAULT_SOCKET = "/run/synapd/synapd.sock"


class SynapdError(RuntimeError):
    pass


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise SynapdError("synapd: connection closed mid-message")
        buf.extend(chunk)
    return bytes(buf)


def synapd_query(prompt, max_tokens=400, socket_path=DEFAULT_SOCKET, timeout=120.0):
    """One RAW QUERY in, one full reply out. No streaming in this protocol."""
    payload = prompt.encode("utf-8")
    flags = SYN_QF_RAW | (min(max_tokens, SYN_QF_TOKENS_MASK) & SYN_QF_TOKENS_MASK)
    req_id = int.from_bytes(os.urandom(4), "little")
    hdr = _HDR.pack(_MAGIC, _VER, _MSG_QUERY, flags, len(payload),
                    req_id, os.getpid(), int(time.time()))

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(socket_path)
        s.sendall(hdr + payload)

        rhdr = _recv_exact(s, _HDR.size)
        magic, ver, mtype, rflags, plen, rid, pid, ts = _HDR.unpack(rhdr)
        if magic != _MAGIC:
            raise SynapdError(f"synapd: bad magic 0x{magic:08X}")
        body = _recv_exact(s, plen) if plen else b""
        if mtype == _MSG_ERROR:
            raise SynapdError(f"synapd error: {body.decode('utf-8', 'replace')}")
        # synapd NUL-terminates its payload; the trailing byte is not text.
        return body.decode("utf-8", "replace").rstrip("\x00").strip()
    finally:
        s.close()


# ── HTTP surface ───────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "chiron-bridge/1.0"

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write("[bridge] %s\n" % (fmt % args))

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", ""):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect(self.server.socket_path)
                s.close()
                self._send(200, {"ok": True, "backend": self.server.socket_path})
            except OSError as e:
                self._send(503, {"ok": False, "error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/generate":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0 or n > 256 * 1024:
            self._send(400, {"error": "bad content-length"})
            return
        try:
            req = json.loads(self.rfile.read(n).decode("utf-8"))
            prompt = req["prompt"]
        except Exception as e:
            self._send(400, {"error": f"bad request: {e}"})
            return

        max_tokens = int(req.get("max_tokens", 400))
        t0 = time.time()
        try:
            text = synapd_query(prompt, max_tokens,
                                self.server.socket_path, self.server.timeout)
        except Exception as e:
            self._send(502, {"error": str(e)})
            return
        dt = time.time() - t0
        if self.server.verbose:
            sys.stderr.write(f"[bridge] generated {len(text)} chars in {dt:.1f}s\n")
        self._send(200, {"text": text, "elapsed": round(dt, 2)})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--socket", default=DEFAULT_SOCKET, dest="socket_path")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        sys.stderr.write(
            f"refusing to bind {args.host}: synapd's protocol is unauthenticated "
            "and this bridge must stay loopback-only.\n")
        return 2

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    srv.socket_path = args.socket_path
    srv.timeout = args.timeout
    srv.verbose = args.verbose

    print(f"chiron-bridge on http://{args.host}:{args.port} -> {args.socket_path}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())

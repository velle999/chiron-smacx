#!/usr/bin/env python3
"""
chiron-bridge — local LLM front end for the Chiron Rising SMACX mod.

The mod's DLL runs inside Wine and can only speak plain TCP/HTTP. This bridges
that to whichever local model host is actually running.

    POST /generate   {"prompt": "...", "max_tokens": 400}  ->  {"text": "..."}
    GET  /health                                           ->  {"ok": true, ...}

Three backends, tried in this order unless --backend names one:

    synapd    a binary framed protocol over a unix socket (SynapseOS)
    llamacpp  llama.cpp's llama-server, OpenAI-style, default :8080
    ollama    default :11434

synapd is first because it is the one host here that a game going fullscreen can
stop and that we know how to restart. The other two need nothing but a listening
port, which is what makes the mod runnable off a SynapseOS box.

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
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
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
DEFAULT_LLAMACPP = "http://127.0.0.1:8080"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"

# Leaders repeating themselves verbatim is the thing this mod exists to fix, so
# sampling has to be warm enough that the same label twice reads differently.
# synapd picks its own; these two take it from us.
DEFAULT_TEMPERATURE = 0.8


# Set once the sandbox proves it will not let us escalate; see wake_synapd().
_wake_disabled = False


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


def wake_synapd(socket_path, wait=25.0):
    """
    Start synapd and wait for its socket to answer. Returns True if it does.

    synui's game mode stops synapd to free ~4GB of VRAM as soon as a game goes
    fullscreen -- which is exactly when this bridge starts being used, so the
    mod would spend the entire session falling back to vanilla text. Excluding
    the game from detection is the proper fix and does not need this, but that
    only takes effect when the compositor next reads its config, and a mod that
    silently degrades until then is worse than one that argues.

    The command matches /etc/sudoers.d/synapd-gamemode character for character.
    sudoers matches the whole command line, so it must stay in step with game
    mode's own game_ai_start_cmd -- if they drift, this silently stops working.
    """
    global _wake_disabled
    if _wake_disabled:
        return False

    cmd = ["sudo", "-n", "systemctl", "start", "synapd.socket", "synapd.service"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=20)
    except Exception as e:
        sys.stderr.write(f"[bridge] could not start synapd: {e}\n")
        return False
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace").strip()
        sys.stderr.write(f"[bridge] start synapd failed: {err}\n")
        # The unit is hardened with NoNewPrivileges and RestrictSUIDSGID, which
        # is why sudo cannot escalate here. That is a deliberate choice for a
        # network-facing service, so do not fight it -- give up for the rest of
        # the session rather than logging this on every single line of dialogue.
        # Excluding the game from the compositor's game mode is the better fix;
        # see README. To enable this path instead, drop NoNewPrivileges= and
        # RestrictSUIDSGID= from chiron-bridge.service.
        if "no new privileges" in err.lower() or "sudo.conf" in err:
            sys.stderr.write("[bridge] sandbox forbids escalation; "
                             "not trying to start synapd again this session\n")
            _wake_disabled = True
        return False

    # The unit is active well before the model finishes loading, so poll the
    # socket rather than trusting systemctl's return.
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(socket_path)
            s.close()
            sys.stderr.write("[bridge] synapd was down; started it\n")
            return True
        except OSError:
            time.sleep(0.5)
    sys.stderr.write("[bridge] synapd did not come up in time\n")
    return False


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


# ── llama.cpp and ollama ───────────────────────────────────────────────────
class BackendError(RuntimeError):
    pass


def _post_json(url, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def llamacpp_query(prompt, max_tokens, base, timeout, temperature):
    """
    llama-server's OpenAI-compatible endpoint.

    The prompt is already a complete instruction built by the DLL, so it goes in
    as a single user message and the server's chat template wraps it. A
    llama-server built without a template still answers here; /completion is the
    fallback for the older builds that do not carry /v1 at all.
    """
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    try:
        out = _post_json(base.rstrip("/") + "/v1/chat/completions", body, timeout)
        return out["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    out = _post_json(base.rstrip("/") + "/completion",
                     {"prompt": prompt, "n_predict": max_tokens,
                      "temperature": temperature, "stream": False}, timeout)
    return out["content"].strip()


def ollama_pick_model(base, timeout=5.0):
    """Whatever is pulled. Asking beats making the user name a model."""
    tags = _get_json(base.rstrip("/") + "/api/tags", timeout).get("models") or []
    if not tags:
        raise BackendError("ollama has no models pulled")
    return tags[0]["name"]


def ollama_query(prompt, max_tokens, base, timeout, temperature, model=None):
    if not model:
        model = ollama_pick_model(base)
    out = _post_json(base.rstrip("/") + "/api/generate",
                     {"model": model, "prompt": prompt, "stream": False,
                      "options": {"num_predict": max_tokens,
                                  "temperature": temperature}}, timeout)
    return (out.get("response") or "").strip()


def probe_synapd(socket_path, timeout=2.0):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(socket_path)
    finally:
        s.close()


def probe_http(base, timeout=2.0):
    host, _, port = base.split("//", 1)[1].partition(":")
    s = socket.create_connection((host, int(port or 80)), timeout)
    s.close()


def generate(srv, prompt, max_tokens):
    """
    Walk the backend chain and return (text, backend_name).

    Each backend is tried in turn and the last error is kept, so a box with none
    of them running gets one message naming all three rather than whichever
    happened to be first. synapd gets the extra restart-and-retry because it is
    the only one that stops on its own -- a desktop that frees the GPU for games
    kills it exactly when the game needs it.
    """
    errors = []

    # Cheap probe first, so a backend that is not installed costs a refused
    # connection rather than a request timeout.
    up = {}
    for name in srv.chain:
        try:
            if name == "synapd":
                probe_synapd(srv.socket_path)
            elif name == "llamacpp":
                probe_http(srv.llamacpp_url)
            elif name == "ollama":
                probe_http(srv.ollama_url)
            up[name] = True
        except Exception as e:
            up[name] = False
            errors.append(f"{name}: {e}")

    for name in srv.chain:
        if not up.get(name):
            continue
        try:
            if name == "synapd":
                return synapd_query(prompt, max_tokens,
                                    srv.socket_path, srv.timeout), name
            if name == "llamacpp":
                return llamacpp_query(prompt, max_tokens, srv.llamacpp_url,
                                      srv.timeout, srv.temperature), name
            if name == "ollama":
                return ollama_query(prompt, max_tokens, srv.ollama_url,
                                    srv.timeout, srv.temperature,
                                    srv.ollama_model), name
        except Exception as e:
            errors.append(f"{name}: {e}")

    # Only now, with nothing answering, is it worth the ~25s of starting synapd.
    # Doing that first cost 25 seconds per line on any box that simply does not
    # have synapd, which is every box the fallbacks exist for.
    if "synapd" in srv.chain and wake_synapd(srv.socket_path):
        try:
            return synapd_query(prompt, max_tokens,
                                srv.socket_path, srv.timeout), "synapd"
        except Exception as e:
            errors.append(f"synapd after start: {e}")

    raise BackendError("; ".join(errors) or "no backends configured")


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
            # Report every backend, not just the first reachable one -- "which
            # of these is actually up" is the question worth answering here.
            found = {}
            for name in self.server.chain:
                try:
                    if name == "synapd":
                        probe_synapd(self.server.socket_path)
                        found[name] = self.server.socket_path
                    elif name == "llamacpp":
                        probe_http(self.server.llamacpp_url)
                        found[name] = self.server.llamacpp_url
                    elif name == "ollama":
                        probe_http(self.server.ollama_url)
                        found[name] = self.server.ollama_url
                except Exception as e:
                    found[name] = f"down ({e})"
            live = [n for n in self.server.chain
                    if not str(found[n]).startswith("down")]
            self._send(200 if live else 503,
                       {"ok": bool(live), "using": live[0] if live else None,
                        "backends": found})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: C901  (kept flat; the retry path reads better inline)
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
            text, backend = generate(self.server, prompt, max_tokens)
        except Exception as e:
            self._send(502, {"error": str(e)})
            return
        dt = time.time() - t0
        if self.server.verbose:
            sys.stderr.write(
                f"[bridge] {backend}: {len(text)} chars in {dt:.1f}s\n")
        self._send(200, {"text": text, "elapsed": round(dt, 2),
                         "backend": backend})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--socket", default=DEFAULT_SOCKET, dest="socket_path")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--backend", default="auto",
                    choices=("auto", "synapd", "llamacpp", "ollama"),
                    help="auto tries synapd, then llamacpp, then ollama")
    ap.add_argument("--llamacpp-url", default=DEFAULT_LLAMACPP)
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA)
    ap.add_argument("--ollama-model", default=None,
                    help="default: whatever ollama lists first")
    ap.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
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
    srv.chain = (["synapd", "llamacpp", "ollama"] if args.backend == "auto"
                 else [args.backend])
    srv.llamacpp_url = args.llamacpp_url
    srv.ollama_url = args.ollama_url
    srv.ollama_model = args.ollama_model
    srv.temperature = args.temperature

    print(f"chiron-bridge on http://{args.host}:{args.port} "
          f"-> {' then '.join(srv.chain)}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    return 0


if __name__ == "__main__":
    sys.exit(main())

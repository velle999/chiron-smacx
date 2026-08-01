#!/usr/bin/env python3
"""
chiron-bridge — local LLM front end for the Chiron Rising SMACX mod.

The mod's DLL runs inside Wine and can only speak plain TCP/HTTP. This bridges
that to whichever local model host is actually running.

    POST /generate      {"prompt": "...", "max_tokens": 400} -> {"text": "..."}
    GET  /health                                             -> {"ok": true, ...}

It also answers ollama's protocol, so anything already written against ollama
reaches this bridge by changing a host and port and nothing else:

    POST /api/generate  ollama's body shape                  -> {"response": ...}
    GET  /api/tags      ollama's model list

A request naming a claude-* model is routed to the claude backend; anything
else falls through to the configured local chain.

The two speak each other's protocols in both directions now. Ollama 0.14+
implements the Anthropic Messages API, so --claude-base-url points the claude
backend at an ollama instead of at Anthropic -- same code path, same request,
and whatever model that server has loaded answers it.

Four backends. --backend takes one name, or a comma-separated chain tried left
to right; "auto" means the three local ones:

    synapd    a binary framed protocol over a unix socket (SynapseOS)
    llamacpp  llama.cpp's llama-server, OpenAI-style, default :8080
    ollama    default :11434
    claude    Anthropic's API -- the cloud, and the only one that costs money

synapd is first because it is the one host here that a game going fullscreen can
stop and that we know how to restart. The next two need nothing but a listening
port, which is what makes the mod runnable off a SynapseOS box.

claude is deliberately NOT in "auto". The other three are local, free, and work
with the network down; silently reaching for a metered API because a local model
happened to be stopped is not a fallback, it is a surprise bill. Ask for it:

    --backend claude              Claude, or vanilla text if it fails
    --backend claude,synapd       Claude, falling back to the local 7B

The DLL needs no change and no new setting for any of this -- it still speaks
POST /generate to this bridge, which is why the cloud backend lives here rather
than in chiron.cpp. It could not live there anyway: the DLL talks plain HTTP
over raw ws2_32 sockets with no TLS, and api.anthropic.com is HTTPS only.

Bound to 127.0.0.1 only. synapd's wire protocol has no authentication, so this
must never listen on a routable address -- see synapd-bridge.socket for the
same reasoning applied to the LAN bridge.

Stdlib only for the three local backends, so the bridge still starts and serves
them on a box with no pip packages at all. claude imports the `anthropic` SDK
lazily, at first use, and only that one backend needs it installed.
"""
import argparse
import json
import os
import re
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

LOCAL_CHAIN = ["synapd", "llamacpp", "ollama"]
ALL_BACKENDS = LOCAL_CHAIN + ["claude"]

DEFAULT_CLAUDE_MODEL = "claude-opus-5"

# Leaders repeating themselves verbatim is the thing this mod exists to fix, so
# sampling has to be warm enough that the same label twice reads differently.
# synapd picks its own; llamacpp and ollama take it from us; Claude REJECTS it
# outright -- temperature/top_p/top_k are removed on Opus 5 and send back a 400.
# So --temperature reaches exactly two of the four backends, and variation on
# the other two comes from the prompt: chiron.cpp already stirs in the mission
# year, the turn, and a per-call counter.
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


# ── Claude ─────────────────────────────────────────────────────────────────
# The DLL builds a whole instruction -- persona, dossier, resolved script line,
# and a closing cue naming what it wants -- so this is a system prompt about
# FORM only. Content direction stays in chiron.cpp where the rest of the prompt
# engineering lives.
#
# The XML line earns its place: with thinking disabled, Opus 5 occasionally
# leaks internal tags into the visible answer. It is deliberately generic --
# naming thinking tags specifically is measurably worse, and telling the model
# not to reason at all makes the leak MORE likely, so neither is said here.
CLAUDE_SYSTEM = (
    "You are writing a single line of in-character dialogue for a faction "
    "leader in Sid Meier's Alpha Centauri. Reply with the line itself and "
    "nothing else: no preamble, no restating the instructions, no commentary "
    "on your answer, no markdown, and no internal or system XML tags."
)

_claude_client = None

# Paired internal tags are removed WITH their contents. Stripping the tags alone
# and keeping what is between them is the worst possible outcome: the model's
# reasoning about the line gets printed as the leader's speech, in character, in
# a box the player believes is dialogue. An unclosed opener is treated the same
# way and cuts to the end of the reply -- the token ceiling truncates mid-thought
# often enough that a dangling <thinking> is a real case, and an empty result
# here is safe (chiron.cpp falls back to the vanilla line).
_THINK_BLOCK_RE = re.compile(
    r"<\s*(thinking|thought|thoughts|reasoning|scratchpad|internal)\b[^>]*>"
    r"(?:.*?<\s*/\s*\1\s*>|.*$)",
    re.IGNORECASE | re.DOTALL)
# Whatever markup is left is empty scaffolding, so dropping the tag alone is
# right here -- there is no content to lose.
_STRAY_TAG_RE = re.compile(r"</?\s*[A-Za-z][\w:.-]{0,30}\s*/?>")


def _scrub_tags(text):
    return _STRAY_TAG_RE.sub("", _THINK_BLOCK_RE.sub("", text)).strip()


def canonical_model(name):
    """Drop an ollama-style :tag. `claude-opus-5:latest` -> `claude-opus-5`."""
    return (name or "").split(":", 1)[0]


def is_claude_model(name):
    """Does this model name ask for Claude rather than a local model?"""
    return canonical_model(name).lower().startswith("claude")


def _claude_get_client(timeout, base_url=None):
    """Import and build the SDK client once. Import is lazy on purpose."""
    global _claude_client
    if _claude_client is None:
        try:
            import anthropic
        except ImportError as e:
            raise BackendError(
                "claude: the anthropic SDK is not installed "
                "(pip install anthropic)") from e
        try:
            if base_url:
                # Pointed at something else that speaks the Messages API --
                # ollama >= 0.14 does. Such a server authenticates however it
                # likes (ollama: not at all), but the SDK insists on a key
                # being present, so supply a placeholder when the environment
                # has none rather than failing to construct.
                _claude_client = anthropic.Anthropic(
                    base_url=base_url,
                    api_key=os.environ.get("ANTHROPIC_API_KEY") or "not-needed")
            else:
                # Zero-arg client: resolves ANTHROPIC_API_KEY, then
                # ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile. An
                # unset key is NOT proof there are no credentials, so do not
                # check the env var and bail early.
                _claude_client = anthropic.Anthropic()
        except Exception as e:
            raise BackendError(f"claude: no usable credentials ({e})") from e
    # The game blocks on this call and gives up at chiron.ini's timeout_ms, so a
    # retry storm just burns the budget the player is staring at. One retry.
    return _claude_client.with_options(timeout=timeout, max_retries=1)


def claude_query(prompt, max_tokens, model, timeout, base_url=None):
    """
    One generation over the Anthropic Messages API.

    Usually that means Anthropic. With base_url set it means anything else
    implementing the same protocol -- ollama 0.14+ does -- in which case the
    model answering is whatever that server has loaded, not Claude.

    Thinking is DISABLED, which is not the usual advice and is load-bearing
    here: max_tokens caps thinking and reply text together, and chiron.ini ships
    max_tokens=110 because a diplomacy box holds about six short lines. With
    thinking on, a reasoning pass would eat that whole budget and the popup
    would get an empty or truncated string. Effort is pinned low to match --
    Opus 5 only accepts disabled thinking at high effort or below, so this pair
    has to move together.

    No temperature: it is rejected outright on Opus 5. See DEFAULT_TEMPERATURE.
    """
    client = _claude_get_client(timeout, base_url)
    body = dict(model=model, max_tokens=max_tokens, system=CLAUDE_SYSTEM,
                messages=[{"role": "user", "content": prompt}])
    try:
        if base_url:
            # A compatible server implements a SUBSET of the API. Thinking,
            # effort, and server-side fallback are Anthropic-side features and
            # a third-party endpoint is entitled to 400 on them, so send the
            # plain request every implementation is expected to accept.
            msg = client.messages.create(**body)
        else:
            msg = client.beta.messages.create(
                thinking={"type": "disabled"},
                output_config={"effort": "low"},
                # A leader threatening war or dredging up an atrocity is
                # ordinary SMACX dialogue, but it is the kind of text a safety
                # classifier can decline. "default" re-serves a declined request
                # on Anthropic's recommended model inside the same call, so a
                # false positive costs a moment instead of the line. Sent via
                # extra_body/betas rather than a named kwarg so an older SDK
                # passes it through untouched instead of dying on an unexpected
                # argument.
                betas=["server-side-fallback-2026-07-01"],
                extra_body={"fallbacks": "default"},
                **body,
            )
    except Exception as e:
        raise BackendError(f"claude: {e}") from e

    # Check stop_reason BEFORE touching content: a refusal can come back with an
    # empty content list, and indexing it would raise instead of falling through
    # to the next backend.
    stop_reason = getattr(msg, "stop_reason", None)
    if stop_reason == "refusal":
        detail = getattr(getattr(msg, "stop_details", None),
                         "category", None) or "unspecified"
        raise BackendError(f"claude: declined by safety classifier ({detail})")

    # Scrub BEFORE the empty check: a reply that is nothing but a leaked
    # thinking block is an empty reply, and must fail into the vanilla line
    # rather than reach the popup. chiron.cpp's cut_at_meta() scrubs prose
    # markers, not markup, so this one is ours to catch.
    #
    # A max_tokens stop needs nothing here: tidy_reply() already discards a
    # trailing fragment with no terminator, which is exactly what truncation is.
    text = _scrub_tags("".join(b.text for b in msg.content if b.type == "text"))
    if not text:
        raise BackendError(f"claude: no usable text (stop_reason={stop_reason})")
    return text


def probe_claude(timeout=2.0, base_url=None):
    """
    Local reachability check only -- SDK present and credentials resolvable.

    generate() probes every backend before each request, so this must not cost
    an API call. A network failure surfaces from claude_query instead.
    """
    _claude_get_client(timeout, base_url)


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
            elif name == "claude":
                probe_claude(base_url=srv.claude_base_url)
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
            if name == "claude":
                return claude_query(prompt, max_tokens, srv.claude_model,
                                    srv.timeout, srv.claude_base_url), name
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
        if self.path.rstrip("/") == "/api/tags":
            # ollama's model list. Clients call this to discover what is
            # available -- and some, including this file's own ollama backend,
            # just take the first entry -- so advertise the Claude model.
            name = f"{self.server.claude_model}:latest"
            self._send(200, {"models": [{
                "name": name,
                "model": name,
                "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime()),
                "size": 0,
                "digest": "",
                "details": {"family": "claude", "families": ["claude"],
                            "format": "api", "parameter_size": "",
                            "quantization_level": ""},
            }]})
            return
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
                    elif name == "claude":
                        probe_claude(base_url=self.server.claude_base_url)
                        found[name] = (self.server.claude_model + " @ " +
                                       (self.server.claude_base_url
                                        or "api.anthropic.com"))
                except Exception as e:
                    found[name] = f"down ({e})"
            live = [n for n in self.server.chain
                    if not str(found[n]).startswith("down")]
            self._send(200 if live else 503,
                       {"ok": bool(live), "using": live[0] if live else None,
                        "backends": found})
        else:
            self._send(404, {"error": "not found"})

    def _read_json(self):
        """Body or None; sends the 400 itself so callers can just bail."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            n = 0
        if n <= 0 or n > 256 * 1024:
            self._send(400, {"error": "bad content-length"})
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            self._send(400, {"error": f"bad request: {e}"})
            return None

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/generate":
            self._native_generate()
        elif path == "/api/generate":
            self._ollama_generate()
        else:
            self._send(404, {"error": "not found"})

    def _native_generate(self):
        req = self._read_json()
        if req is None:
            return
        try:
            prompt = req["prompt"]
        except KeyError:
            self._send(400, {"error": "bad request: 'prompt'"})
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

    def _ollama_generate(self):
        """
        POST /api/generate in ollama's wire format.

        Ollama itself cannot serve Claude -- it loads local GGUF weights and
        Claude's are not published -- so this is the other direction: the bridge
        answers ollama's protocol and routes to Claude when the requested model
        names one. Anything that already speaks ollama reaches Claude by
        changing a host and port and nothing else. For the mod that means the
        DLL's existing backend=ollama path, which needs no new C code.
        """
        req = self._read_json()
        if req is None:
            return
        try:
            prompt = req["prompt"]
        except KeyError:
            self._send(400, {"error": "bad request: 'prompt'"})
            return

        model = req.get("model") or self.server.claude_model
        # ollama's num_predict, not max_tokens. Missing means "no limit" there;
        # here it means the same default the native endpoint uses.
        opts = req.get("options") or {}
        max_tokens = int(opts.get("num_predict") or 400)

        t0 = time.time()
        try:
            # Route to the Messages-API backend when the name looks like Claude
            # OR matches whatever --claude-model is set to -- with
            # --claude-base-url pointed at an ollama the configured model is an
            # open one like `qwen3`, and a client asking for it by name must
            # still land on that path rather than the local chain.
            if (is_claude_model(model)
                    or canonical_model(model) ==
                    canonical_model(self.server.claude_model)):
                text = claude_query(prompt, max_tokens, canonical_model(model),
                                    self.server.timeout,
                                    self.server.claude_base_url)
                backend = "claude"
            else:
                text, backend = generate(self.server, prompt, max_tokens)
        except Exception as e:
            # ollama reports failures as a plain {"error": ...}; clients written
            # against it check for that key, not for our native shape.
            self._send(502, {"error": str(e)})
            return
        dt = time.time() - t0
        if self.server.verbose:
            sys.stderr.write(f"[bridge] /api/generate {model} -> {backend}: "
                             f"{len(text)} chars in {dt:.1f}s\n")

        body = {
            "model": model,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "response": text,
            "done": True,
            "done_reason": "stop",
            "total_duration": int(dt * 1e9),   # ollama reports nanoseconds
        }
        # stream defaults to TRUE in ollama when the key is absent, so a client
        # that never sets it is expecting newline-delimited JSON. Answer with a
        # stream of exactly one object rather than making them special-case us.
        # (chiron.cpp does send stream:false, but chibi and friends may not.)
        if req.get("stream", True) is False:
            self._send(200, body)
        else:
            raw = (json.dumps(body) + "\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=11436)
    ap.add_argument("--socket", default=DEFAULT_SOCKET, dest="socket_path")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--backend", default="auto",
                    help="auto (synapd,llamacpp,ollama), one name, or a "
                         "comma-separated chain tried left to right. "
                         "claude is never in auto -- name it. "
                         "e.g. --backend claude,synapd")
    ap.add_argument("--llamacpp-url", default=DEFAULT_LLAMACPP)
    ap.add_argument("--ollama-url", default=DEFAULT_OLLAMA)
    ap.add_argument("--ollama-model", default=None,
                    help="default: whatever ollama lists first")
    ap.add_argument("--claude-model", default=DEFAULT_CLAUDE_MODEL,
                    help=f"claude only (default: {DEFAULT_CLAUDE_MODEL})")
    ap.add_argument("--claude-base-url", default=None,
                    help="point the claude backend at another server speaking "
                         "the Anthropic Messages API instead of at Anthropic. "
                         "ollama 0.14+ does: --claude-base-url http://127.0.0.1:11434 "
                         "--claude-model qwen3")
    ap.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE,
                    help="llamacpp and ollama only; synapd and claude ignore it")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    # Parse the chain before binding anything, so a typo is a usage error at
    # startup rather than a backend that is silently never tried.
    if args.backend == "auto":
        chain = list(LOCAL_CHAIN)
    else:
        chain = [n.strip() for n in args.backend.split(",") if n.strip()]
    bad = [n for n in chain if n not in ALL_BACKENDS]
    if bad or not chain:
        sys.stderr.write(
            f"unknown backend {', '.join(bad) or '(empty)'}; "
            f"choose from auto, {', '.join(ALL_BACKENDS)}\n")
        return 2

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
    srv.chain = chain
    srv.llamacpp_url = args.llamacpp_url
    srv.ollama_url = args.ollama_url
    srv.ollama_model = args.ollama_model
    srv.claude_model = args.claude_model
    srv.claude_base_url = args.claude_base_url
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

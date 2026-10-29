#!/usr/bin/env python3
"""Matkassa helper: lets the web app's "Koble til REMA" button start things on THIS Mac. Stdlib only.

    python3 ingest/helper.py serve          # what launchd runs (ingest/launchd/install-helper.sh)
    python3 ingest/helper.py pair           # show the pairing code (made on first use); paste it in the app once
    python3 ingest/helper.py pair --new     # make a new code (the old one stops working)

A web page cannot run programs on your Mac, so the app talks to this small server instead. It is the "mac-helper"
login provider in js/chains/ (see js/chains/index.js for the interface; an iOS app would swap in its own provider).

Endpoints (http://127.0.0.1:47321 only, never the network):
    GET  /status        {helper, version, rema: {state, lastSync, lastSyncOk, message}, syncing}
    POST /rema/login    starts `rema auth login` (rema1000-cli): REMA's OWN login opens in your browser and YOU log
                        in there (phone number, reCAPTCHA, code). We never see or bypass any of it.
    POST /rema/logout   `rema auth logout` (deletes the REMA tokens on this Mac) = "Koble fra"
    POST /sync          runs ingest/sync.sh (fetch receipts and deliver them to your account / private data repo)

Security:
    * binds to 127.0.0.1 only, and rejects any Host header but 127.0.0.1/localhost (DNS rebinding);
    * every request needs "Authorization: Bearer <pairing code>"; wrong codes are rate limited;
    * a request with an Origin header must come from the allow-list: the GitHub Pages site of this repo's owner
      (from `git remote get-url origin`, e.g. github.com/<user>/matkassa → https://<user>.github.io), or
      MATKASSA_APP_ORIGIN, plus MATKASSA_HELPER_ORIGINS for local tests; CORS headers only go to those origins;
    * never returns or logs tokens: the REMA tokens stay in ~/.rema1000/ (rema1000-cli), the pairing code in
      ~/.matkassa/helper-pair.json (0600). The log has method, path and status code only.
"""
import argparse
import datetime as dt
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
DEFAULT_PORT = 47321
LOGIN_TIMEOUT = 10 * 60
SYNC_TIMEOUT = 30 * 60
MAX_FAILS = 10  # wrong pairing codes per minute before we answer 429
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L, U: easy to read and type

# Mask anything token-shaped before it can reach a reply (same patterns as launchd/run-sync.sh).
_MASKS = [
    (re.compile(r"(github_pat_|ghp_|gho_|ghs_|ghu_)[A-Za-z0-9_]+"), r"\1***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+"), "eyJ***"),
    (re.compile(r"AMf-v[A-Za-z0-9_-]+"), "AMf-v***"),
    (re.compile(r"(?i)(token|secret|key|password|passord)([\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1\2***"),
]


def mask(s):
    for rx, rep in _MASKS:
        s = rx.sub(rep, s)
    return s


def now_iso():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Config:
    def __init__(self, env=os.environ):
        home = os.path.expanduser("~")
        self.port = int(env.get("MATKASSA_HELPER_PORT") or DEFAULT_PORT)
        self.state_dir = env.get("MATKASSA_HELPER_DIR") or os.path.join(home, ".matkassa")
        self.rema_tokens = os.path.join(home, ".rema1000", "tokens.json")
        self.rema_bin = env.get("MATKASSA_REMA_BIN") or shutil.which("rema") or os.path.join(home, ".local", "bin", "rema")
        self.sync_cmd = env.get("MATKASSA_HELPER_SYNC") or os.path.join(HERE, "sync.sh")
        extra = {o.strip().rstrip("/") for o in (env.get("MATKASSA_HELPER_ORIGINS") or "").split(",") if o.strip()}
        app = (env.get("MATKASSA_APP_ORIGIN") or pages_origin()).rstrip("/")
        self.origins = ({app} if app else set()) | extra
        self.login_timeout = float(env.get("MATKASSA_HELPER_LOGIN_TIMEOUT") or LOGIN_TIMEOUT)
        self.cloud_session = env.get("MATKASSA_CLOUD_SESSION") or os.path.join(home, ".matkassa", "supabase_session.json")
        self.cloud_cmd = env.get("MATKASSA_HELPER_CLOUD") or os.path.join(HERE, "cloud.py")

    @property
    def pair_file(self):
        return os.path.join(self.state_dir, "helper-pair.json")

    @property
    def state_file(self):
        return os.path.join(self.state_dir, "helper-state.json")


def pages_origin(repo_dir=os.path.dirname(HERE)):
    """https://<user>.github.io for the GitHub repo this folder was cloned from ('' if none)."""
    try:
        url = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"github\.com[:/]([A-Za-z0-9-]+)/", url)
    return f"https://{m.group(1).lower()}.github.io" if m else ""


def write_private(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".helper.")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def normalize_code(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def new_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(16))  # ~78 bits
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def pairing_code(cfg, rotate=False):
    j = read_json(cfg.pair_file, {})
    if rotate or not j.get("code"):
        j = {"code": new_code(), "created": now_iso()}
        write_private(cfg.pair_file, j)
    return j["code"]


class Helper:
    """State shared by the request threads: the running login/sync and what happened last."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.login_proc = None
        self.syncing = False
        self.fails = []
        self.state = read_json(cfg.state_file, {})  # {"rema": {...}}, no secrets in here
        self.code = normalize_code(pairing_code(cfg))

    # ---- persistence ----
    def _rema(self):
        return self.state.setdefault("rema", {})

    def _save(self):
        write_private(self.cfg.state_file, self.state)

    # ---- auth ----
    def authorized(self, header):
        now = time.monotonic()
        self.fails = [t for t in self.fails if now - t < 60]
        if len(self.fails) >= MAX_FAILS:
            return "limited"
        m = re.match(r"Bearer\s+(.+)", header or "")
        given = normalize_code(m.group(1)) if m else ""
        # The code file may have been rotated (`pair --new`) while we run: re-read it.
        self.code = normalize_code(read_json(self.cfg.pair_file, {}).get("code")) or self.code
        if given and hmac.compare_digest(given.encode(), self.code.encode()):
            return "ok"
        self.fails.append(now)
        return "no"

    # ---- account status (optional) ----
    def report(self, *args):
        """If this Mac is logged in to a Matkassa account (cloud.py login), tell it the REMA status (never a token),
        so the app on the phone can show "Koblet via Mac-en". Best effort, in the background."""
        if not os.path.isfile(self.cfg.cloud_session):
            return
        cmd = [self.cfg.cloud_cmd, "report", "rema", *args]
        if self.cfg.cloud_cmd.endswith(".py"):
            cmd = [sys.executable, "-I", *cmd]

        def run():
            try:
                subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
            except (OSError, subprocess.TimeoutExpired):
                pass
        threading.Thread(target=run, daemon=True).start()

    # ---- REMA status ----
    def rema_status(self):
        with self.lock:
            r = dict(self._rema())
            connecting = self.login_proc is not None
            syncing = self.syncing
        has_tokens = os.path.isfile(self.cfg.rema_tokens)
        if connecting:
            state = "connecting"
        elif not has_tokens:
            state = "disconnected"
        elif r.get("expired") and (r.get("expiredAt") or 0) >= _mtime(self.cfg.rema_tokens):
            state = "expired"
        else:
            state = "connected"
        msg = r.get("message") if state in ("disconnected", "expired") or r.get("lastSyncOk") is False else None
        return {
            "state": state,
            "lastSync": r.get("lastSync"),
            "lastSyncOk": r.get("lastSyncOk"),
            "message": msg,
        }, syncing

    def status(self):
        rema, syncing = self.rema_status()
        return {"helper": "matkassa", "version": VERSION, "rema": rema, "syncing": syncing}

    # ---- actions ----
    def start_login(self):
        with self.lock:
            if self.login_proc is not None:
                return True
            if not (os.path.isfile(self.cfg.rema_bin) and os.access(self.cfg.rema_bin, os.X_OK)):
                self._rema()["message"] = "Fant ikke rema1000-cli (rema). Se ingest/README.md."
                self._save()
                return False
            # stdin closed: the login happens in the browser, never in a hidden prompt. Output is discarded (it is
            # rema1000-cli's own and could mention the phone number); only the exit code counts.
            self.login_proc = subprocess.Popen([self.cfg.rema_bin, "auth", "login"], stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            proc = self.login_proc
        threading.Thread(target=self._wait_login, args=(proc,), daemon=True).start()
        return True

    def _wait_login(self, proc):
        try:
            rc = proc.wait(timeout=self.cfg.login_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = "timeout"
        with self.lock:
            self.login_proc = None
            r = self._rema()
            if rc == 0 and os.path.isfile(self.cfg.rema_tokens):
                r.update(expired=False, expiredAt=None, message=None, connectedAt=now_iso())
                self.report("connected")
            elif rc == "timeout":
                r["message"] = "Innloggingen tok for lang tid. Prøv igjen."
            else:
                r["message"] = "Innloggingen ble ikke fullført. Prøv igjen."
            self._save()

    def logout(self):
        with self.lock:
            if self.login_proc is not None:
                self.login_proc.kill()
        ok = True
        if os.path.isfile(self.cfg.rema_bin) and os.access(self.cfg.rema_bin, os.X_OK):
            try:
                ok = subprocess.run([self.cfg.rema_bin, "auth", "logout"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=30).returncode == 0
            except subprocess.TimeoutExpired:
                ok = False
        with self.lock:
            self.state["rema"] = {}
            self._save()
        self.report("disconnected")
        return ok and not os.path.isfile(self.cfg.rema_tokens)

    def start_sync(self):
        with self.lock:
            if self.syncing:
                return False
            self.syncing = True
        threading.Thread(target=self._run_sync, daemon=True).start()
        return True

    def _run_sync(self):
        try:
            p = subprocess.run([self.cfg.sync_cmd], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=SYNC_TIMEOUT, cwd=os.path.dirname(HERE))
            rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            rc, out = -1, f"Synken startet ikke eller tok for lang tid ({type(e).__name__})."
        lines = [mask(x.strip()) for x in out.splitlines() if x.strip()]
        rema_failed = bool(re.search(r"(?i)feilet:.*\bREMA\b", out))
        expired = rema_failed and bool(re.search(r"(?i)HTTP 40[013]|INVALID_REFRESH_TOKEN|TOKEN_EXPIRED|USER_DISABLED|Fant ingen REMA-innlogging", out))
        with self.lock:
            self.syncing = False
            r = self._rema()
            r["lastSync"] = now_iso()
            r["lastSyncOk"] = rc == 0
            r["message"] = None if rc == 0 else (lines[-1][:200] if lines else f"Synken feilet (kode {rc}).")
            if expired:
                r.update(expired=True, expiredAt=time.time(), message="REMA-innloggingen er utløpt. Logg inn på nytt.")
            self._save()
        if expired:
            self.report("expired", "--error", "REMA-innloggingen er utløpt")
        elif rc == 0:
            self.report("connected", "--synced")
        elif rema_failed:
            self.report("failing", "--error", "REMA-henting feilet")


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0


def make_handler(helper):
    cfg = helper.cfg
    hosts = {f"127.0.0.1:{cfg.port}", f"localhost:{cfg.port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "MatkassaHelper"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass  # see log_request: method, path, status only

        def log_request(self, code="-", size="-"):
            path = self.path.split("?")[0][:60]
            sys.stderr.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {self.command} {path} {code}\n")

        def _origin_ok(self):
            o = self.headers.get("Origin")
            return o is None or o.rstrip("/") in cfg.origins

        def _send(self, code, body=None, extra=()):
            raw = json.dumps(body if body is not None else {}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            o = self.headers.get("Origin")
            if o and o.rstrip("/") in cfg.origins:
                self.send_header("Access-Control-Allow-Origin", o)
                self.send_header("Vary", "Origin")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _gate(self):
            """Common checks. Returns True when the request may go on (else a reply was sent)."""
            if (self.headers.get("Host") or "") not in hosts:
                self._send(421, {"error": "host"})
                return False
            if not self._origin_ok():
                self._send(403, {"error": "origin"})
                return False
            if int(self.headers.get("Content-Length") or 0) > 1024:
                self._send(413, {"error": "too large"})
                return False
            a = helper.authorized(self.headers.get("Authorization"))
            if a == "limited":
                self._send(429, {"error": "too many attempts"}, [("Retry-After", "60")])
                return False
            if a != "ok":
                self._send(401, {"error": "unpaired", "helper": "matkassa"})
                return False
            return True

        def do_OPTIONS(self):
            if (self.headers.get("Host") or "") not in hosts or not self.headers.get("Origin") or not self._origin_ok():
                self._send(403, {"error": "origin"})
                return
            extra = [("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                     ("Access-Control-Allow-Headers", "Authorization, Content-Type"),
                     ("Access-Control-Max-Age", "600")]
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                extra.append(("Access-Control-Allow-Private-Network", "true"))  # Chrome's local network access
            self._send(204, None, extra)

        def do_GET(self):
            if not self._gate():
                return
            if self.path.split("?")[0] == "/status":
                return self._send(200, helper.status())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._gate():
                return
            path = self.path.split("?")[0]
            if path == "/rema/login":
                if not helper.start_login():
                    return self._send(500, helper.status())
                return self._send(202, helper.status())
            if path == "/rema/logout":
                helper.logout()
                return self._send(200, helper.status())
            if path == "/sync":
                if not helper.start_sync():
                    return self._send(409, helper.status())
                return self._send(202, helper.status())
            self._send(404, {"error": "not found"})

        def do_PUT(self):
            self._send(405, {"error": "method"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def serve(cfg):
    helper = Helper(cfg)
    srv = ThreadingHTTPServer((HOST, cfg.port), make_handler(helper))
    srv.daemon_threads = True
    sys.stderr.write(f"Matkassa-hjelper lytter på http://{HOST}:{cfg.port} (bare denne Mac-en). Godtar: {', '.join(sorted(cfg.origins)) or 'ingen nettsider'}\n")
    sys.stderr.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Matkassa-hjelper (se ingest/README.md)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    p = sub.add_parser("pair")
    p.add_argument("--new", action="store_true", help="lag en ny kode (den gamle slutter å virke)")
    args = ap.parse_args(argv)
    cfg = Config()
    if args.cmd == "pair":
        code = pairing_code(cfg, rotate=args.new)
        print("Parkoblingskode for Matkassa (lim inn i appen under Mer → Kjeder, bare én gang):\n")
        print(f"    {code}\n")
        print("Koden virker bare på denne Mac-en. Del den ikke. Ny kode: python3 ingest/helper.py pair --new")
        return 0
    serve(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

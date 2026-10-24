#!/usr/bin/env python3
"""Tests for ingest/ (Trumf, merge, Mac -> account upload, sync.sh) against FAKE local servers. Stdlib only.

No real Trumf, REMA or Supabase is contacted: trumf.no and Supabase are small fakes on 127.0.0.1, HOME is a temp
folder, and all data is from test/fake/*-FAKE.*. Run: python3 test/ingest.test.py
"""
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FAKE = os.path.join(ROOT, "test", "fake")
results = []


def ok(cond, name, detail=""):
    results.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'} {name}{' — ' + str(detail) if detail and not cond else ''}")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class Fake(http.server.BaseHTTPRequestHandler):
    """trumf.no + Supabase in one: routes by path. State lives on the server object."""

    def log_message(self, *a):
        pass

    def send(self, code, body="", ctype="application/json", headers=()):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def cookie(self):
        return dict(p.strip().split("=", 1) for p in (self.headers.get("Cookie") or "").split(";") if "=" in p)

    def do_GET(self):
        s = self.server
        s.log.append(("GET", self.path, dict(self.headers)))
        sess = self.cookie().get("next-auth.session-token")
        valid = sess in s.valid_sessions
        if self.path == "/api/auth/session":
            return self.send(200, json.dumps({"accessToken": "FAKE-ACCESS", "user": {"name": "FAKE"}} if valid else {}))
        if self.path.startswith("/trumf-profil/kvitteringer"):
            if not valid:
                return self.send(302, "", headers=[("Location", "https://id.trumf.no/connect/authorize?FAKE")])
            if self.path == "/trumf-profil/kvitteringer":
                s.list_calls += 1
                if s.list_calls == 1:
                    return self.send(503, "busy (FAKE)")  # first try fails: the script must retry
                s.valid_sessions.add("FAKE-SESSION-2")
                return self.send(200, read(os.path.join(FAKE, "trumf-rsc-list-FAKE.txt")), "text/x-component",
                                 [("Set-Cookie", "next-auth.session-token=FAKE-SESSION-2; Path=/; Max-Age=2592000; HttpOnly")])
            if self.path.endswith("FAKE-B1001"):
                return self.send(200, read(os.path.join(FAKE, "trumf-rsc-detail-FAKE.txt")), "text/x-component")
            return self.send(200, '0:["$","div",null,{}]\n', "text/x-component")
        if self.path.startswith("/rest/v1/"):
            return self.send(200, "[]")
        self.send(404, "{}")

    def do_POST(self):
        s = self.server
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        s.log.append(("POST", self.path, dict(self.headers), body))
        if self.headers.get("apikey") != "FAKE-anon-key":
            return self.send(401, '{"message":"bad key"}')
        if self.path.startswith("/auth/v1/token?grant_type=refresh_token"):
            if json.loads(body).get("refresh_token") != s.refresh:
                return self.send(400, '{"error_description":"Invalid Refresh Token"}')
            s.refresh = f"FAKE-RT-{len(s.log)}"
            return self.send(200, json.dumps({"access_token": "FAKE-AT", "refresh_token": s.refresh, "expires_in": 3600}))
        if self.path.startswith("/rest/v1/receipts"):
            if self.headers.get("Authorization") != "Bearer FAKE-AT":
                return self.send(401, '{"message":"JWT"}')
            s.uploaded += json.loads(body)
            return self.send(201, "")
        self.send(404, "{}")


def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    srv.log, srv.valid_sessions, srv.list_calls, srv.refresh, srv.uploaded = [], {"FAKE-SESSION-1"}, 0, "FAKE-RT-0", []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def env_for(home, srv):
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    e = {k: v for k, v in os.environ.items() if not k.startswith(("MATKASSA_", "REMA_"))}
    e.update(HOME=home, MATKASSA_TRUMF_BASE=base, MATKASSA_CLOUD_URL=base, MATKASSA_CLOUD_ANON="FAKE-anon-key",
             MATKASSA_RETRY_BASE="0.05", MATKASSA_TRUMF_PAUSE="0", MATKASSA_DATA_REPO="", MATKASSA_ENV_FILE="/dev/null")
    return e


def write_state(home, session="FAKE-SESSION-1"):
    d = os.path.join(home, ".matkassa")
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "trumf_state.json")
    with open(p, "w") as f:
        json.dump({"saved": "FAKE", "cookies": [{"name": "next-auth.session-token", "value": session, "domain": "127.0.0.1", "path": "/", "expires": None}]}, f)
    os.chmod(p, 0o600)
    return p


def run(args, env):
    return subprocess.run([sys.executable, "-I", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


# ---------- Trumf parser on FAKE fixtures ----------
r = run(["ingest/trumf.py", "--parse", os.path.join(FAKE, "trumf-rsc-list-FAKE.txt"), os.path.join(FAKE, "trumf-rsc-detail-FAKE.txt")], dict(os.environ))
out = json.loads(r.stdout)["receipts"]
ok([x["id"] for x in out] == ["trumf-bFAKE-B1001", "trumf-bFAKE-B1003"], "trumf: grocery purchases only, duplicates once (Circle K skipped)", [x["id"] for x in out])
k = out[0]
ok(k["chain"] == "Kiwi" and k["source"] == "trumf" and k["total"] == 254.3 and k["date"] == "2026-10-02", "trumf: chain, source, total and date from the receipt", k)
ok(len(k["lines"]) == 3 and k["lines"][0]["ean"] == "2000000000015" and k["lines"][1]["ean"] is None and k["lines"][1]["unit"] == "kg", "trumf: product lines with barcodes; $undefined → no barcode; KG → kg")
ok(out[1]["total"] == 89.9, "trumf: Norwegian decimal comma in an amount")

# ---------- trumf.py against a FAKE trumf.no ----------
srv = server()
home = tempfile.mkdtemp(prefix="matkassa-ingest-test-")
try:
    env = env_for(home, srv)
    st = write_state(home)
    out_path = os.path.join(home, "trumf.json")
    r = run(["ingest/trumf.py", "--out", out_path], env)
    ok(r.returncode == 0, "trumf.py: runs against the fake site", r.stderr[-300:])
    got = json.loads(read(out_path))["receipts"]
    ok(len(got) == 2 and len(got[0]["lines"]) == 3, "trumf.py: writes spending.json with lines", len(got))
    ok(srv.list_calls == 2, "trumf.py: retries after a 503", srv.list_calls)
    ok(all(h.get("Rsc") == "1" or h.get("RSC") == "1" for m, p, h, *_ in srv.log if p.startswith("/trumf-profil")), "trumf.py: asks for RSC payloads (RSC: 1)")
    saved = json.loads(read(st))
    ok(saved["cookies"][0]["value"] == "FAKE-SESSION-2" and stat.S_IMODE(os.stat(st).st_mode) == 0o600, "trumf.py: keeps the rotated session cookie, file stays 0600")
    ok("FAKE-SESSION" not in r.stdout + r.stderr and "FAKE-ACCESS" not in r.stdout + r.stderr, "trumf.py: never prints cookies or tokens")
    n_detail = sum(1 for m, p, *_ in srv.log if p.startswith("/trumf-profil/kvitteringer/"))
    r = run(["ingest/trumf.py", "--out", out_path], env)
    n_detail2 = sum(1 for m, p, *_ in srv.log if p.startswith("/trumf-profil/kvitteringer/")) - n_detail
    ok(r.returncode == 0 and n_detail2 == 1, "trumf.py: next run reuses receipts it has (only re-asks the one without lines)", n_detail2)
    write_state(home, "FAKE-EXPIRED")
    r = run(["ingest/trumf.py", "--out", out_path], env)
    ok(r.returncode == 2 and "trumf-login.mjs" in r.stderr, "trumf.py: expired session → exit 2 with the login command", r.stderr[-200:])
    r = run(["ingest/trumf.py", "--check"], env)
    ok(r.returncode == 2, "trumf.py --check: reports an expired session")
    os.remove(st)
    r = run(["ingest/trumf.py", "--check"], env)
    ok(r.returncode == 2 and "trumf-login.mjs" in r.stderr, "trumf.py: no session saved → tells you how to log in")

    # ---------- merge.py: dedupe across sources ----------
    rema = {"receipts": [{"id": "rema-1", "source": "rema", "chain": "REMA 1000", "store": "REMA 1000 (FAKE)", "date": "2026-10-03", "time": "12:00", "total": 99.0, "lines": []}]}
    innsyn = {"receipts": [{"id": "trumf-123", "source": "trumf", "chain": "KIWI", "store": "KIWI 412 (FAKE)", "date": "2026-10-02", "time": "17:30", "total": 254.3, "lines": [{"name": "MELK", "amount": 254.3}]}]}
    for name, data in (("rema.json", rema), ("innsyn.json", innsyn)):
        with open(os.path.join(home, name), "w") as f:
            json.dump(data, f)
    merged = os.path.join(home, "merged.json")
    r = run(["ingest/merge.py", merged, os.path.join(home, "rema.json"), out_path, os.path.join(home, "innsyn.json"), os.path.join(home, "missing.json")], env)
    m = json.loads(read(merged))["receipts"]
    ids = sorted(x["id"] for x in m)
    ok(ids == ["rema-1", "trumf-bFAKE-B1001", "trumf-bFAKE-B1003"], "merge.py: REMA + Trumf, the innsyn copy of the same Kiwi purchase dropped (richer copy kept)", ids)

    # ---------- cloud.py upload + sync.sh end to end (FAKE Supabase) ----------
    write_state(home)
    srv.valid_sessions = {"FAKE-SESSION-1"}
    srv.list_calls = 1  # no 503 this time
    sess = os.path.join(home, ".matkassa", "supabase_session.json")
    with open(sess, "w") as f:
        json.dump({"refresh_token": "FAKE-RT-0", "user_id": "00000000-0000-0000-0000-00000000000a", "email": "ole-FAKE@example.invalid"}, f)
    os.chmod(sess, 0o600)
    r = subprocess.run(["bash", "ingest/sync.sh"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    ok(r.returncode == 0, "sync.sh: Trumf → merge → account upload, without GitHub", (r.stdout + r.stderr)[-400:])
    ok(len(srv.uploaded) == 2 and all(x["user_id"].endswith("0a") and x["id"].startswith("trumf-b") for x in srv.uploaded), "cloud.py: receipts go to the user's own rows", len(srv.uploaded))
    posts = [x for x in srv.log if x[0] == "POST" and x[1].startswith("/rest/v1/receipts")]
    ok(posts and all("ignore-duplicates" in (p[2].get("Prefer") or "") for p in posts), "cloud.py: never overwrites receipts already in the account")
    ok(json.loads(read(sess))["refresh_token"] == srv.refresh and stat.S_IMODE(os.stat(sess).st_mode) == 0o600, "cloud.py: rotated Supabase refresh token saved, file 0600")
    ok("FAKE-RT" not in r.stdout + r.stderr and "FAKE-AT" not in r.stdout + r.stderr and "FAKE-SESSION" not in r.stdout + r.stderr, "sync.sh: no tokens in the output")
    ok(not os.path.exists(os.path.join(ROOT, "data", "spending.json")) or "trumf-bFAKE" not in read(os.path.join(ROOT, "data", "spending.json")), "sync.sh: without a data repo nothing is written to data/")
    write_state(home, "FAKE-EXPIRED")
    r = subprocess.run(["bash", "ingest/sync.sh"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    ok(r.returncode != 0 and "trumf-login.mjs" in r.stderr, "sync.sh: an expired Trumf login fails loudly with the fix", r.stderr[-200:])
    os.remove(sess)
    r = subprocess.run(["bash", "ingest/sync.sh"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    ok(r.returncode == 1 and "cloud.py login" in r.stderr, "sync.sh: no account and no repo → says what to do")
finally:
    srv.shutdown()
    shutil.rmtree(home, ignore_errors=True)

print(f"\n{results.count(False)} FAILED" if not all(results) else f"\nAll {len(results)} ingest tests passed")
sys.exit(0 if all(results) else 1)

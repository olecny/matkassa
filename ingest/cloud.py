#!/usr/bin/env python3
"""Mac -> your own Matkassa account (Supabase). Replaces the GitHub repo + key for receipts.

    python3 ingest/cloud.py login                 # once: your Matkassa e-mail + password (typed, never shown)
    python3 ingest/cloud.py status
    python3 ingest/cloud.py upload spending.json  # new receipts go to YOUR rows (RLS); existing ones are left alone
    python3 ingest/cloud.py connect trumf|rema    # hand the chain session to the weekly server pull (Edge Function)
    python3 ingest/cloud.py logout

Uses the same public project URL + anon key as the app (js/cloud-config.js) and your own login, so row-level
security applies exactly as in the app. The service_role key is never used here. Your Supabase session (refresh
token) is saved in ~/.matkassa/supabase_session.json (chmod 600, outside the repo) and never printed.
"""
import getpass
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION = os.environ.get("MATKASSA_CLOUD_SESSION") or os.path.expanduser("~/.matkassa/supabase_session.json")
CHUNK = 200
RETRY_BASE = float(os.environ.get("MATKASSA_RETRY_BASE", "2"))


def config():
    with open(os.path.join(HERE, "..", "js", "cloud-config.js"), encoding="utf-8") as f:
        src = f.read()
    url = re.search(r"url:\s*'([^']*)'", src)
    key = re.search(r"anonKey:\s*'([^']*)'", src)
    url = os.environ.get("MATKASSA_CLOUD_URL") or (url.group(1) if url else "")
    key = os.environ.get("MATKASSA_CLOUD_ANON") or (key.group(1) if key else "")
    if not url or not key:
        raise SystemExit("Ingen Supabase-oppsett i js/cloud-config.js ennå (se SUPABASE.md).")
    return url.rstrip("/"), key


def save_json_private(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".cloud.")
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def call(method, url, key, token=None, body=None, prefer=None, tries=4):
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode()
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                raw = res.read().decode("utf-8") or "null"
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt * RETRY_BASE)
                continue
            try:
                j = json.loads(e.read().decode("utf-8", "replace"))
                msg = j.get("error_description") or j.get("msg") or j.get("message") or ""
            except ValueError:
                msg = ""
            raise SystemExit(f"Supabase svarte {e.code} på {url.split('?')[0].split('/v1/')[-1]}: {msg[:200]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise SystemExit(f"Nettverksfeil mot Supabase: {e}")
            time.sleep(2 ** attempt * RETRY_BASE)


def session(url, key):
    """A fresh access token from the saved refresh token (rotated on every use, saved back)."""
    try:
        with open(SESSION, encoding="utf-8") as f:
            s = json.load(f)
    except FileNotFoundError:
        raise SystemExit("Ikke logget inn. Kjør: python3 ingest/cloud.py login")
    j = call("POST", f"{url}/auth/v1/token?grant_type=refresh_token", key, body={"refresh_token": s["refresh_token"]})
    s["refresh_token"] = j["refresh_token"]
    save_json_private(SESSION, s)
    return j["access_token"], s["user_id"]


def upload(url, key, paths):
    token, uid = session(url, key)
    receipts = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        receipts += [r for r in (j.get("receipts", []) if isinstance(j, dict) else j) if isinstance(r, dict) and r.get("id")]
    rows = [{"user_id": uid, "id": r["id"], "data": r, "deleted": False} for r in receipts]
    # ignore-duplicates: a receipt already in the account (maybe edited in the app) is never overwritten.
    for i in range(0, len(rows), CHUNK):
        call("POST", f"{url}/rest/v1/receipts?on_conflict=user_id,id", key, token, rows[i:i + CHUNK], prefer="resolution=ignore-duplicates,return=minimal")
    print(f"Lastet opp {len(rows)} kvitteringer til kontoen (nye legges til, eksisterende røres ikke).", file=sys.stderr)


def connect(url, key, chain):
    """Send the chain session to the `connect` Edge Function, which stores it encrypted in Vault for the weekly pull."""
    if chain == "trumf":
        path = os.environ.get("MATKASSA_TRUMF_STATE") or os.path.expanduser("~/.matkassa/trumf_state.json")
        if not os.path.exists(path):
            raise SystemExit("Logg inn hos Trumf først: node ingest/trumf-login.mjs")
        with open(path, encoding="utf-8") as f:
            secret = json.dumps({"cookies": json.load(f)["cookies"]})
    elif chain == "rema":
        store = os.path.expanduser("~/.rema1000/tokens.json")
        if not os.path.exists(store):
            raise SystemExit("Logg inn hos REMA først: rema1000 login (rema1000-cli)")
        with open(store, encoding="utf-8") as f:
            t = json.load(f)
        secret = json.dumps({"refresh_token": (t.get("firebase") or {}).get("refresh_token", ""), "device_id": t.get("device_id") or ""})
    else:
        raise SystemExit("Kjede må være trumf eller rema (Coop: bruk innsyn)")
    token, _ = session(url, key)
    call("POST", f"{url}/functions/v1/connect", key, token, {"chain": chain, "secret": secret})
    print(f"{chain}: koblet til. Serveren henter nye kvitteringer hver søndag. 'Koble fra' i appen sletter økta.", file=sys.stderr)


def main(argv):
    if not argv or argv[0] not in ("login", "logout", "status", "upload", "connect"):
        print(__doc__, file=sys.stderr)
        return 1
    url, key = config()
    cmd = argv[0]
    if cmd == "login":
        email = input("E-post for Matkassa-kontoen: ").strip()
        pw = getpass.getpass("Passord (vises ikke): ")
        j = call("POST", f"{url}/auth/v1/token?grant_type=password", key, body={"email": email, "password": pw})
        save_json_private(SESSION, {"refresh_token": j["refresh_token"], "user_id": j["user"]["id"], "email": j["user"].get("email", "")})
        print(f"Logget inn som {j['user'].get('email', '')}. Økta er lagret i ~/.matkassa (bare for deg).", file=sys.stderr)
    elif cmd == "logout":
        try:
            os.remove(SESSION)
        except FileNotFoundError:
            pass
        print("Logget ut på denne Mac-en.", file=sys.stderr)
    elif cmd == "status":
        token, uid = session(url, key)
        n = call("GET", f"{url}/rest/v1/receipts?select=id&deleted=eq.false", key, token)
        conns = call("GET", f"{url}/rest/v1/chain_connections?select=chain,status,last_fetch_at", key, token)
        print(f"Innlogget. {len(n or [])} kvitteringer i kontoen. Kjeder: {', '.join(c['chain'] + '=' + c['status'] for c in conns or []) or 'ingen'}", file=sys.stderr)
    elif cmd == "upload":
        if len(argv) < 2:
            raise SystemExit("Bruk: python3 ingest/cloud.py upload spending.json")
        upload(url, key, argv[1:])
    elif cmd == "connect":
        if len(argv) < 2:
            raise SystemExit("Bruk: python3 ingest/cloud.py connect trumf|rema")
        connect(url, key, argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

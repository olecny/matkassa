#!/usr/bin/env python3
"""REMA 1000 -> Matkassa spending.json (schema matkassa.spending/1).

UNTESTED against a live account: written from the endpoint documentation in
github.com/Alfredvc/rema1000-cli (API.md, captured 2026-04-06). Unofficial API,
own data only. Token lives in ingest/.env (git-ignored), never in code or git.

Usage:
    python3 rema.py --out spending-rema.json [--since 2026-09-01] [--limit 200]
    python3 rema.py --dump-heads
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.rema.no"
# Public app keys from the REMA app (documented in rema1000-cli). Not secrets of Ole's.
BELLA_KEY = "fb5e24884b504d0bad761098f77e6605"
FIREBASE_API_KEY = "AIzaSyBi9PlJsUo5FAqljPHuh0WQCsaOSW4rFQs"
FIREBASE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
APP_VERSION = "3.13.0.1181"
HERE = os.path.dirname(os.path.abspath(__file__))


def load_env(path=os.path.join(HERE, ".env")):
    env = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("REMA_")})
    # Fall back to the token store written by `rema auth login` (rema1000-cli).
    store = os.path.expanduser("~/.rema1000/tokens.json")
    if not env.get("REMA_FIREBASE_REFRESH_TOKEN") and os.path.exists(store):
        with open(store, encoding="utf-8") as f:
            tokens = json.load(f)
        fb = tokens.get("firebase") or {}
        env["REMA_FIREBASE_REFRESH_TOKEN"] = fb.get("refresh_token", "")
        env.setdefault("REMA_DEVICE_ID", tokens.get("device_id") or "")
        if fb.get("phone_number"):
            env.setdefault("REMA_PHONE", fb["phone_number"])
    return env


def http(method, url, headers=None, data=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"HTTP {e.code} for {url}: {detail}")


def id_token(env):
    """Exchange the long-lived Firebase refresh token for a short-lived ID token."""
    refresh = env.get("REMA_FIREBASE_REFRESH_TOKEN")
    if not refresh:
        raise SystemExit("Mangler REMA_FIREBASE_REFRESH_TOKEN i ingest/.env (se README.md).")
    res = http("POST", f"{FIREBASE_TOKEN_URL}?key={FIREBASE_API_KEY}",
               {"Content-Type": "application/x-www-form-urlencoded"},
               {"grant_type": "refresh_token", "refresh_token": refresh})
    new_refresh = res.get("refresh_token")
    if new_refresh and new_refresh != refresh:
        print("Merk: Firebase ga nytt refresh token. Oppdater .env hvis det gamle slutter å virke.", file=sys.stderr)
    return res["id_token"]


def headers(token, env):
    h = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": BELLA_KEY,
        "X-App": "Bella",
        "X-Platform": "iOS",
        "X-App-Version": APP_VERSION,
        "X-Device-ID": env.get("REMA_DEVICE_ID") or str(uuid.uuid4()).upper(),
        "X-Correlation-ID": str(uuid.uuid4()).upper(),
        "Accept-Language": "no",
        "Accept": "application/json",
    }
    if env.get("REMA_PHONE"):
        h["X-Mobile-NR"] = env["REMA_PHONE"]
    return h


def first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def parse_when(v):
    """ISO string or epoch ms -> (YYYY-MM-DD, HH:MM)."""
    if v is None:
        return None, None
    if isinstance(v, (int, float)):
        t = dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v)
    else:
        s = str(v).replace("Z", "+00:00")
        try:
            t = dt.datetime.fromisoformat(s)
        except ValueError:
            return s[:10], None
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def unit_name(u):
    return {"EA": "stk", "Kg": "kg", "KG": "kg"}.get(u, u)


def to_receipt(head, rows):
    tid = first(head, "id", "transactionId", "transactionID", "receiptId")
    date, tm = parse_when(first(head, "purchaseDate", "transactionDate", "date", "timestamp", "created"))
    store = first(head, "storeName", "store", "storeDescription") or "REMA 1000"
    if isinstance(store, dict):
        store = first(store, "name", "description") or "REMA 1000"
    lines = []
    for r in (rows or {}).get("rows", []):
        lines.append({
            "name": (first(r, "productDescription", "prodtxt1") or "Ukjent vare").strip(),
            "ean": first(r, "prodtxt3") if str(first(r, "prodtxt3") or "").isdigit() else None,
            "qty": first(r, "volume") if r.get("unit") in ("Kg", "KG") else first(r, "pieces"),
            "unit": unit_name(r.get("unit")),
            "amount": float(r.get("amount") or 0),
            "discount": float(r.get("discount") or 0),
            "deposit": float(r.get("deposit") or 0),
            "group": first(r, "productGroupDescription"),
            "category": None,
        })
    payments = [p for p in (rows or {}).get("transactionPayments", []) if p.get("meansOfPaymentDesc") != "Rounding"]
    total = first(head, "amount", "totalAmount", "purchaseAmount", "total")
    if total is None and payments:
        total = sum(float(p.get("amount") or 0) for p in payments)
    if total is None:
        total = sum(line["amount"] for line in lines)
    return {
        "id": f"rema-{tid}",
        "source": "rema",
        "chain": "REMA 1000",
        "store": store,
        "date": date,
        "time": tm,
        "total": round(float(total), 2),
        "currency": "NOK",
        "category": None,
        "lines": lines,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "spending-rema.json"))
    ap.add_argument("--since", help="YYYY-MM-DD, hopp over eldre kjøp")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--dump-heads", action="store_true", help="skriv rå svar fra /heads og avslutt")
    args = ap.parse_args()

    env = load_env()
    h = headers(id_token(env), env)
    heads = http("GET", f"{API}/v1/bella/transaction/v2/heads", h)
    if args.dump_heads:
        json.dump(heads, sys.stdout, ensure_ascii=False, indent=2)
        return
    txs = heads.get("transactions", []) if isinstance(heads, dict) else heads or []
    print(f"{len(txs)} transaksjoner fra REMA", file=sys.stderr)

    receipts = []
    for head in txs[: args.limit]:
        tid = first(head, "id", "transactionId", "transactionID", "receiptId")
        if tid is None:
            print(f"Hopper over transaksjon uten id: {list(head)[:8]}", file=sys.stderr)
            continue
        date, _ = parse_when(first(head, "purchaseDate", "transactionDate", "date", "timestamp", "created"))
        if args.since and date and date < args.since:
            continue
        rows = http("GET", f"{API}/v1/bella/transaction/v2/rows/{tid}", h)
        receipts.append(to_receipt(head, rows))
        time.sleep(0.5)  # be gentle with an unofficial API

    out = {
        "schema": "matkassa.spending/1",
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "rema",
        "receipts": [r for r in receipts if r["date"]],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Skrev {len(out['receipts'])} kvitteringer til {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

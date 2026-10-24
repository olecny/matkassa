#!/usr/bin/env python3
"""REMA 1000 -> Matkassa spending.json (schema matkassa.spending/1) and rema-offers.json (matkassa.offers/1).

Endpoints from github.com/Alfredvc/rema1000-cli (API.md). Unofficial API, the user's own data only.
Each user logs in with their own phone number (`rema auth login`); the token stays in ~/.rema1000/ or
ingest/.env (both outside git) and is never printed.

Usage:
    python3 rema.py --out spending-rema.json [--since 2026-09-01] [--limit 200]
    python3 rema.py --offers rema-offers.json      # REMA "Superpris" campaign with barcodes (GTIN)
    python3 rema.py --dump-heads
"""
import argparse
import re
import shutil
import subprocess
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
CAMPAIGN_KEY = "e8494ceb23754fc4911c81b166e0a97f"
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


def unbrotli(raw):
    """The campaign endpoint always answers brotli-compressed; Python's stdlib can't decode that."""
    try:
        import brotli  # pip install brotli (optional)
        return brotli.decompress(raw)
    except ImportError:
        pass
    exe = shutil.which("brotli")  # brew install brotli (free)
    if not exe:
        raise SystemExit("REMA svarer brotli-komprimert. Installer brotli (`brew install brotli`) for å hente tilbudene.")
    return subprocess.run([exe, "-d", "-c"], input=raw, capture_output=True, check=True).stdout


def http(method, url, headers=None, data=None):
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read()
                if res.headers.get("Content-Encoding") == "br":
                    raw = unbrotli(raw)
                return json.loads(raw.decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            raise SystemExit(f"HTTP {e.code} for {url.split('?')[0]}: {detail}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # Transient network drops happen during long runs (100+ calls); back off and retry.
            if attempt == 3:
                raise SystemExit(f"Nettverksfeil mot {url.split('?')[0]}: {e}")
            time.sleep(2 ** attempt * 2)


def id_token(env):
    """Exchange the long-lived Firebase refresh token for a short-lived ID token."""
    refresh = env.get("REMA_FIREBASE_REFRESH_TOKEN")
    if not refresh:
        raise SystemExit("Fant ingen REMA-innlogging. Kjør `rema auth login` (rema1000-cli) først, se ingest/README.md.")
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


def price_of(o):
    try:
        return round(int(o.get("prisKroner") or 0) + int(o.get("prisOerer") or 0) / 100, 2)
    except ValueError:
        return None


def unit_price(text):
    m = re.search(r"(\d+[.,]\d{2})\s*PR\.?\s*(KG|L)\b", text or "", re.I)
    return (float(m.group(1).replace(",", ".")), m.group(2).lower()) if m else (None, None)


def campaign_offers(h):
    """REMA's Superpris campaign (the only REMA offer feed with GTINs) -> matkassa.offers/1."""
    ch = dict(h, **{"Ocp-Apim-Subscription-Key": CAMPAIGN_KEY})
    campaigns = http("GET", f"{API}/v1/papirflycampaign/campaigns?type=SP&includeOffers=true&feed=true", ch) or []
    offers = []
    for c in campaigns:
        if not c.get("active"):
            continue
        for o in (c.get("offers") or {}).get("offers") or []:
            price = price_of(o)
            gtins = sorted({str(g) for p in o.get("products") or [] for g in p.get("gtin") or [] if str(g).isdigit()})
            if price is None or not o.get("title"):
                continue
            dates = (o.get("validDates") or [{}])[0]
            up, unit = unit_price(o.get("undertekst"))
            before = o.get("beforePrice") or None
            offers.append({
                "id": f"rema-sp-{c.get('campaignId')}-{o.get('productId')}",
                "title": o["title"].strip(),
                "desc": (o.get("undertekst") or "").strip(),
                "price": price,
                "prePrice": before if o.get("hasBeforePrice") and before else None,
                "unitPrice": up,
                "unit": unit,
                "from": dates.get("from") or c.get("validFrom"),
                "till": dates.get("to") or c.get("validTo"),
                "img": o.get("imageUrl"),
                "eans": gtins,
                "group": o.get("cohort"),
            })
    return offers


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "spending-rema.json"))
    ap.add_argument("--since", help="YYYY-MM-DD, hopp over eldre kjøp")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--dump-heads", action="store_true", help="skriv rå svar fra /heads og avslutt")
    ap.add_argument("--offers", metavar="FIL", help="hent REMA Superpris-tilbud med strekkoder (GTIN) til FIL og avslutt")
    args = ap.parse_args()

    env = load_env()
    h = headers(id_token(env), env)
    if args.offers:
        offers = campaign_offers(h)
        out = {
            "schema": "matkassa.offers/1",
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "rema-campaign",
            "chain": "REMA 1000",
            "offers": offers,
        }
        with open(args.offers, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        n = sum(1 for o in offers if o["eans"])
        print(f"Skrev {len(offers)} REMA-tilbud ({n} med strekkode) til {args.offers}", file=sys.stderr)
        return
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

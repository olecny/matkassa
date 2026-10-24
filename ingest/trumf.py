#!/usr/bin/env python3
"""Trumf (Kiwi, Meny, Spar, Joker) -> Matkassa spending.json (schema matkassa.spending/1), source "trumf".

How it works: you log in to trumf.no yourself, once, with `node ingest/trumf-login.mjs` (a normal Chrome window,
your own phone number, password and SMS code). That saves your trumf.no session to ~/.matkassa/trumf_state.json
(chmod 600, outside the repo). This script then reads the same pages trumf.no shows you under "Mine kvitteringer"
(as React Server Component payloads, header `RSC: 1`) and turns them into receipts with product lines and barcodes.

Unofficial: Trumf has no public API. Only your own data, at most one request per second, nothing is bypassed (no
captcha, no app interception). Never prints cookies or tokens. Approach and field names from public open-source
projects (holdude/TrumfScraper, palhatlem/grocious, ttyridal/trumf-data-fetch); no code copied.

Usage:
    python3 ingest/trumf.py --out spending-trumf.json [--since 2026-01-01] [--limit 300]
    python3 ingest/trumf.py --check                 # is the saved session still valid? (exit 0/2)
    python3 ingest/trumf.py --parse LIST.txt [DETAIL.txt ...]   # parse saved payloads (tests, FAKE fixtures)
Exit codes: 0 ok, 2 not logged in / session expired (run trumf-login.mjs again), 1 other errors.
"""
import argparse
import bisect
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = os.environ.get("MATKASSA_TRUMF_BASE", "https://www.trumf.no")  # override only for the FAKE test server
HOST = BASE.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
LIST_PATHS = ["/trumf-profil/kvitteringer", "/profil/kvitteringer"]  # trumf.no moved the page in 2026
STATE = os.environ.get("MATKASSA_TRUMF_STATE") or os.path.expanduser("~/.matkassa/trumf_state.json")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
RETRY_BASE = float(os.environ.get("MATKASSA_RETRY_BASE", "3"))  # seconds; tests set it low
PAUSE = float(os.environ.get("MATKASSA_TRUMF_PAUSE", "1.0"))  # between receipt pages: gentle on trumf.no
CHAINS = [("EUROSPAR", "Eurospar"), ("SPAR", "Spar"), ("KIWI", "Kiwi"), ("MENY", "Meny"), ("JOKER", "Joker"),
          ("NÆRBUTIKKEN", "Nærbutikken"), ("KJØPMANNSHUSET", "Kjøpmannshuset"), ("ODA", "Oda")]


class SessionExpired(Exception):
    pass


# ---------- local session (cookies) ----------
def load_state(path=STATE):
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        raise SessionExpired("Ingen Trumf-økt lagret. Kjør: node ingest/trumf-login.mjs")
    if not isinstance(st, dict) or not isinstance(st.get("cookies"), list):
        raise SessionExpired("Trumf-økta er ugyldig. Kjør: node ingest/trumf-login.mjs")
    return st


def save_state(st, path=STATE):
    """Atomic write, owner-only (0600) in an owner-only folder (0700)."""
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".trumf_state.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cookie_header(st, host=HOST):
    now = time.time()
    out = []
    for c in st["cookies"]:
        dom = str(c.get("domain", "")).lstrip(".")
        if not (host == dom or host.endswith("." + dom)):
            continue
        exp = c.get("expires")
        if isinstance(exp, (int, float)) and 0 < exp < now:
            continue
        out.append(f"{c['name']}={c['value']}")
    return "; ".join(out)


def apply_set_cookies(st, headers):
    """Keep rotated session cookies (NextAuth refreshes them) so the session lives on between weekly runs."""
    changed = False
    for raw in headers.get_all("Set-Cookie") or []:
        part = raw.split(";", 1)[0]
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        attrs = {k.strip().lower(): v.strip() for k, _, v in (a.partition("=") for a in raw.split(";")[1:])}
        dom = attrs.get("domain", HOST).lstrip(".")
        expires = None
        if "max-age" in attrs and attrs["max-age"].lstrip("-").isdigit():
            expires = time.time() + int(attrs["max-age"])
        for c in st["cookies"]:
            if c["name"] == name and str(c.get("domain", "")).lstrip(".") == dom:
                if c["value"] != value or expires:
                    c["value"] = value
                    if expires:
                        c["expires"] = expires
                    changed = True
                break
        else:
            st["cookies"].append({"name": name, "value": value, "domain": dom, "path": attrs.get("path", "/"), "expires": expires})
            changed = True
    return changed


# ---------- HTTP with retries ----------
class NoLoginRedirect(urllib.request.HTTPRedirectHandler):
    """Follow trumf.no's own redirects, but a redirect to the login server means the session is gone."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if "id.trumf.no" in newurl or "/logg-inn" in newurl or "/api/auth/signin" in newurl:
            raise SessionExpired("Trumf-økta er utløpt. Kjør: node ingest/trumf-login.mjs")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(NoLoginRedirect)


def fetch(st, path, rsc=True, tries=4):
    url = BASE + path
    for attempt in range(tries):
        headers = {"User-Agent": UA, "Cookie": cookie_header(st), "Accept": "*/*" if rsc else "application/json"}
        if rsc:
            headers["RSC"] = "1"
        req = urllib.request.Request(url, headers=headers)
        try:
            with _opener.open(req, timeout=30) as res:
                if apply_set_cookies(st, res.headers):
                    st["dirty"] = True
                return res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SessionExpired("Trumf avviste økta (utløpt). Kjør: node ingest/trumf-login.mjs")
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 ** attempt * RETRY_BASE)
                continue
            raise RuntimeError(f"HTTP {e.code} fra trumf.no{path.split('?')[0]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == tries - 1:
                raise RuntimeError(f"Nettverksfeil mot trumf.no: {e}")
            time.sleep(2 ** attempt * RETRY_BASE)


def logged_in(st):
    """NextAuth session endpoint: has an access token while the login is valid. The token is never printed."""
    try:
        j = json.loads(fetch(st, "/api/auth/session", rsc=False) or "null")
    except ValueError:
        return False
    return bool(isinstance(j, dict) and (j.get("accessToken") or j.get("user")))


# ---------- RSC payload parsing ----------
def json_objects(text, key):
    """Every JSON object in an RSC payload that has `key` as a direct field (string-aware brace matching)."""
    needle = f'"{key}"'
    hits = [m.start() for m in re.finditer(re.escape(needle), text)]
    if not hits:
        return []
    out, stack, in_str, esc = [], [], False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            k = bisect.bisect_left(hits, start)
            if k < len(hits) and hits[k] < i:
                try:
                    obj = json.loads(text[start:i + 1])
                except ValueError:
                    continue
                if isinstance(obj, dict) and key in obj:
                    out.append(obj)
    return out


def rsc_value(v):
    """RSC encodes dates as "$D2026-10-02T15:31:00.000Z" and missing values as "$undefined"."""
    if v == "$undefined":
        return None
    if isinstance(v, str) and v.startswith("$D"):
        return v[2:]
    return v


def num(v):
    v = rsc_value(v)
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace("kr", "").replace(",", "."))
    except ValueError:
        return None


def local_when(v):
    v = rsc_value(v)
    if not v:
        return None, None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(v))
        return (m.group(1), None) if m else (None, None)
    if t.tzinfo:
        t = t.astimezone()  # the Mac's time zone (Norway)
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def chain_of(text):
    up = str(text or "").upper()
    for key, name in CHAINS:
        if re.search(r"\b" + key + r"\b", up):
            return name
    return None


def parse_list(text):
    """Transactions on "Mine kvitteringer": {batchId, harKvittering, belop, beskrivelse, transaksjonsTidspunkt}."""
    seen, out = set(), []
    for o in json_objects(text, "batchId"):
        bid = rsc_value(o.get("batchId"))
        if bid in (None, "") or bid in seen:
            continue
        seen.add(bid)
        out.append({
            "batchId": str(bid),
            "receipt": bool(rsc_value(o.get("harKvittering"))),
            "total": num(o.get("belop")),
            "text": str(rsc_value(o.get("beskrivelse")) or "").strip(),
            "when": o.get("transaksjonsTidspunkt"),
        })
    return out


def parse_detail(text):
    """Product lines of one receipt: varelinjer [{produktBeskrivelse, ean, antall, enhetsType, belop}]."""
    lines = []
    for o in json_objects(text, "varelinjer"):
        for v in o.get("varelinjer") or []:
            if not isinstance(v, dict):
                continue
            ean = rsc_value(v.get("ean"))
            ean = str(ean) if ean is not None and re.fullmatch(r"\d{8,14}", str(ean)) else None
            unit = str(rsc_value(v.get("enhetsType")) or "").lower()
            lines.append({
                "name": str(rsc_value(v.get("produktBeskrivelse")) or "Ukjent vare").strip(),
                "ean": ean,
                "qty": num(v.get("antall")),
                "unit": "kg" if unit.startswith("kg") or unit == "kilo" else "stk" if unit else None,
                "amount": num(v.get("belop")) or 0.0,
                "group": None,
                "category": None,
            })
        if lines:
            break
    return lines


def to_receipt(tx, lines):
    date, tm = local_when(tx["when"])
    store = tx["text"].title() if tx["text"].isupper() else tx["text"]
    total = tx["total"] if tx["total"] is not None else sum(l["amount"] for l in lines)
    return {
        "id": f"trumf-b{tx['batchId']}",
        "source": "trumf",
        "chain": chain_of(tx["text"]) or store or "Trumf",
        "store": store or "Trumf",
        "date": date,
        "time": tm,
        "total": round(abs(float(total)), 2),
        "currency": "NOK",
        "category": None,
        "lines": lines,
    }


def wanted(tx):
    """Grocery purchases only: digital receipts, or a known NorgesGruppen chain. Bonus/partner rows are skipped."""
    return (tx["receipt"] or chain_of(tx["text"])) and tx["total"] is not None and tx["total"] > 0


# ---------- main ----------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "spending-trumf.json"))
    ap.add_argument("--since", help="YYYY-MM-DD, hopp over eldre kjøp")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--check", action="store_true", help="sjekk bare om den lagrede økta virker")
    ap.add_argument("--parse", nargs="+", metavar="FIL", help="les lagrede RSC-svar (liste først, så detaljer) og skriv JSON til stdout")
    args = ap.parse_args(argv)

    if args.parse:
        with open(args.parse[0], encoding="utf-8") as f:
            txs = [t for t in parse_list(f.read()) if wanted(t)]
        details = []
        for p in args.parse[1:]:
            with open(p, encoding="utf-8") as f:
                details.append(parse_detail(f.read()))
        receipts = [to_receipt(t, details[i] if i < len(details) else []) for i, t in enumerate(txs)]
        json.dump({"schema": "matkassa.spending/1", "source": "trumf", "receipts": receipts}, sys.stdout, ensure_ascii=False, indent=2)
        return 0

    try:
        st = load_state()
        if not logged_in(st):
            raise SessionExpired("Trumf-økta er utløpt. Kjør: node ingest/trumf-login.mjs")
        if args.check:
            print("Trumf-økta virker.", file=sys.stderr)
            return 0
        text, used = None, None
        for p in LIST_PATHS:
            try:
                text = fetch(st, p)
                used = p
                break
            except RuntimeError as e:
                if "HTTP 404" not in str(e):
                    raise
        if text is None:
            raise RuntimeError("Fant ikke kvitteringssiden på trumf.no (har de flyttet den?)")
        txs = [t for t in parse_list(text) if wanted(t)]
        if not txs and "batchId" not in text:
            raise RuntimeError("Kvitteringssiden hadde ingen transaksjoner i et format vi kjenner igjen (trumf.no kan ha endret siden)")
        print(f"{len(txs)} kjøp fra Trumf", file=sys.stderr)

        # Reuse receipts we already have with lines: weekly runs only fetch details for new purchases.
        known = {}
        try:
            with open(args.out, encoding="utf-8") as f:
                known = {r["id"]: r for r in json.load(f).get("receipts", []) if r.get("lines")}
        except (OSError, ValueError):
            pass
        receipts = []
        for tx in txs[: args.limit]:
            date, _ = local_when(tx["when"])
            if args.since and date and date < args.since:
                continue
            rid = f"trumf-b{tx['batchId']}"
            if rid in known:
                receipts.append(known[rid])
                continue
            lines = []
            if tx["receipt"]:
                lines = parse_detail(fetch(st, f"{used}/{tx['batchId']}"))
                time.sleep(PAUSE)  # gentle: at most one page per second
            receipts.append(to_receipt(tx, lines))
        out = {
            "schema": "matkassa.spending/1",
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "trumf",
            "receipts": [r for r in receipts if r["date"]],
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        n = sum(1 for r in out["receipts"] if r["lines"])
        print(f"Skrev {len(out['receipts'])} Trumf-kvitteringer ({n} med varelinjer) til {args.out}", file=sys.stderr)
        return 0
    except SessionExpired as e:
        print(str(e), file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"Trumf: {e}", file=sys.stderr)
        return 1
    finally:
        if "st" in locals() and st.pop("dirty", False):
            save_state(st)


if __name__ == "__main__":
    sys.exit(main())

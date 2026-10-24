#!/usr/bin/env python3
"""Merge several spending.json files (REMA, Trumf, ...) into one, without duplicates.

Same rules as the app (js/spending.js dedupeReceipts): first by id, then the same purchase from two sources
(same day, chain and total; times within 3 minutes when both are known) is kept once, the copy with the most
barcodes/lines wins.

Usage: python3 ingest/merge.py OUT.json IN1.json [IN2.json ...]   (missing inputs are skipped)
"""
import datetime as dt
import json
import os
import re
import sys

CHAIN_KEYS = ["rema", "kiwi", "meny", "eurospar", "spar", "joker", "extra", "obs", "prix", "mega", "coop", "bunnpris", "oda"]


def chain_key(r):
    s = f"{r.get('chain') or ''} {r.get('store') or ''}".lower()
    for k in CHAIN_KEYS:
        if k in s:
            return k
    return re.sub(r"[^a-zæøå]", "", s)[:10]


def richness(r):
    lines = r.get("lines") or []
    return sum(1 for l in lines if l.get("ean")) * 1000 + len(lines) * 10 + (0 if r.get("source") == "manual" else 1)


def minutes(t):
    return int(t[:2]) * 60 + int(t[3:5]) if isinstance(t, str) and re.match(r"^\d{2}:\d{2}", t) else None


def dedupe(receipts):
    by_id = {}
    for r in receipts:
        if r.get("id") and r.get("date"):
            by_id[r["id"]] = r
    groups = {}
    for r in by_id.values():
        try:
            k = (r["date"], round(float(r["total"]) * 100), chain_key(r))
        except (TypeError, ValueError, KeyError):
            continue
        groups.setdefault(k, []).append(r)
    drop = set()
    for g in groups.values():
        kept = []
        for r in sorted(g, key=richness, reverse=True):
            twin = any(minutes(k.get("time")) is None or minutes(r.get("time")) is None
                       or abs(minutes(k["time"]) - minutes(r["time"])) <= 3 for k in kept)
            if twin:
                drop.add(r["id"])
            else:
                kept.append(r)
    out = [r for r in by_id.values() if r["id"] not in drop]
    out.sort(key=lambda r: (r["date"], r.get("time") or ""), reverse=True)
    return out, len(drop)


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    out_path, inputs = argv[0], argv[1:]
    receipts, used = [], []
    for p in inputs:
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        rs = j.get("receipts", []) if isinstance(j, dict) else j
        receipts.extend(r for r in rs if isinstance(r, dict))
        used.append(os.path.basename(p))
    merged, dupes = dedupe(receipts)
    sources = sorted({r.get("source", "import") for r in merged})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "schema": "matkassa.spending/1",
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "+".join(sources) or "none",
            "receipts": merged,
        }, f, ensure_ascii=False, indent=2)
    print(f"Slo sammen {', '.join(used) or 'ingenting'}: {len(merged)} kvitteringer ({dupes} dobbelt fjernet)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

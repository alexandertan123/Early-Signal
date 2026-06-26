#!/usr/bin/env python3
"""
fetch-signals.py — pull REAL café signals from OpenStreetMap (keyless, free) and
bake them into index.html's MEASURED block.

The "latte line" signal in Early Signal is otherwise modelled from a hand-set
maturity number. This script replaces it with a measured café count per place,
queried live from the OpenStreetMap Overpass API. No API key, no billing.

Usage:
    python3 scripts/fetch-signals.py                # refresh every place
    python3 scripts/fetch-signals.py "Granada"      # refresh one place (name match)

Notes:
  * Overpass is a shared free service — be polite: this script spaces requests
    out and sets a User-Agent. Refreshing all ~100 places takes a few minutes.
  * It only measures café COUNT/DENSITY. Review quality ("good reviews") and
    "new in last N months" are NOT in OSM — those need a keyed source (Foursquare/
    Yelp/Google) or repeated snapshots over time. See README/notes.
"""
import json, re, sys, time, urllib.request, urllib.parse, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"
RADIUS_M = 1500          # 1.5 km around each place centre
SLEEP_S = 4              # gap between Overpass calls (rate-limit friendly)
ASOF = time.strftime("%Y-%m-%d")
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "EarlySignal/0.9 (gentrification map; contact javier@arnocap.com)"


def parse_places(html: str):
    """Pull {name, area, lat, lon} from the PLACES array in index.html."""
    places = []
    for m in re.finditer(
        r'\{n:"(?P<n>[^"]+)",a:"(?P<a>[^"]+)",lat:(?P<lat>-?[\d.]+),lon:(?P<lon>-?[\d.]+)',
        html,
    ):
        places.append((m["n"], m["a"], float(m["lat"]), float(m["lon"])))
    return places


def overpass(query: str):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": UA})
    return json.load(urllib.request.urlopen(req, timeout=80))


def cafe_counts(lat: float, lon: float):
    """Return (total cafés, specialty coffee shops) within RADIUS_M."""
    q = (
        f"[out:json][timeout:60];("
        f'node["amenity"="cafe"](around:{RADIUS_M},{lat},{lon});'
        f'node["shop"="coffee"](around:{RADIUS_M},{lat},{lon});'
        f'node["cuisine"~"coffee"](around:{RADIUS_M},{lat},{lon});'
        f");out tags;"
    )
    for attempt in range(4):
        try:
            els = overpass(q)["elements"]
            seen, uniq = set(), []
            for e in els:
                if e.get("id") in seen:
                    continue
                seen.add(e.get("id"))
                uniq.append(e)
            specialty = sum(
                1
                for e in uniq
                if e.get("tags", {}).get("shop") == "coffee"
                or "coffee" in e.get("tags", {}).get("cuisine", "")
            )
            return len(uniq), specialty
        except Exception as exc:  # rate-limited / transient — back off and retry
            print(f"    retry {attempt+1}: {exc}")
            time.sleep(SLEEP_S * 3)
    return None, None


def build_measured_block(rows: dict):
    lines = ["/* MEASURED:START — real signals pulled from OpenStreetMap (keyless). Refresh with scripts/fetch-signals.py */",
             "const MEASURED={"]
    for key, v in rows.items():
        lines.append(
            f' "{key}":{{cafes:{v["cafes"]},specialty:{v["specialty"]},'
            f'radiusKm:{RADIUS_M/1000:g},asof:"{v["asof"]}",src:"OpenStreetMap"}},'
        )
    lines.append("};")
    lines.append("/* MEASURED:END */")
    return "\n".join(lines)


def read_existing(html: str):
    """Keep places already measured so a single-place run doesn't wipe the rest."""
    rows = {}
    block = re.search(r"const MEASURED=\{(.*?)\};", html, re.S)
    if not block:
        return rows
    for m in re.finditer(
        r'"(?P<key>[^"]+)":\{cafes:(?P<c>\d+),specialty:(?P<s>\d+),radiusKm:[\d.]+,asof:"(?P<asof>[^"]+)"',
        block[1],
    ):
        rows[m["key"]] = {"cafes": int(m["c"]), "specialty": int(m["s"]), "asof": m["asof"]}
    return rows


def main():
    html = INDEX.read_text()
    places = parse_places(html)
    only = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if only:
        places = [p for p in places if only in p[0].lower()]
        if not places:
            sys.exit(f"No place matching '{sys.argv[1]}'")

    rows = read_existing(html)
    print(f"Fetching café signals for {len(places)} place(s)…")
    for n, a, lat, lon in places:
        total, spec = cafe_counts(lat, lon)
        if total is None:
            print(f"  ✗ {n}, {a}: failed (left unchanged)")
            continue
        rows[f"{n}|{a}"] = {"cafes": total, "specialty": spec, "asof": ASOF}
        print(f"  ✓ {n}, {a}: {total} cafés ({spec} specialty)")
        time.sleep(SLEEP_S)

    new_block = build_measured_block(rows)
    html = re.sub(
        r"/\* MEASURED:START.*?/\* MEASURED:END \*/",
        new_block,
        html,
        flags=re.S,
    )
    INDEX.write_text(html)
    print(f"\nWrote {len(rows)} measured place(s) into index.html ({ASOF}).")


if __name__ == "__main__":
    main()

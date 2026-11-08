#!/usr/bin/env python3
"""
Opening hours from Lausanne Tourisme (the city's official tourism office) for places
that have no hours in OpenStreetMap.

Reads the site's place pages listed in its sitemap (robots.txt allows this), takes the
schema.org openingHoursSpecification each page publishes, converts the hours valid today
to OpenStreetMap opening_hours syntax, and matches each listing to a place on the map
(within 150 m and with a similar name). Writes data/lt_hours.js keyed by OpenStreetMap id.
Polite: one request at a time with a short pause. Standard library only.
"""
import json
import math
import re
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = "https://www.lausanne-tourisme.ch/fr/poi-sitemap.xml"
UA = "lausanne-sunday-map/1.0 (personal opening-hours map; +https://github.com/adamshankins-svg/lausanne-sunday-map)"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
OSM_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
TODAY = date.today()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr-CH,fr"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


STOP = set("le la les l de du des d et au aux sa sarl the chez lausanne cafe restaurant ristorante bar boulangerie patisserie tea room tearoom salon club cuisine take away hotel concept store shop".split())


def tokens(s):
    return set(t for t in re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", fold(s))) if t not in STOP)


def name_score(a, b):
    """Share of distinctive words in common, measured from both names (so "Café Beau-Rivage" ≠ "Pic au Beau-Rivage Palace")."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    common = len(ta & tb)
    return min(common / len(ta), common / len(tb))


def haversine(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def parse_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:  # noqa: BLE001
        return None


def to_osm(specs):
    """Convert openingHoursSpecification entries valid today into OSM syntax, or None."""
    current = []
    for s in specs if isinstance(specs, list) else [specs]:
        if not isinstance(s, dict):
            continue
        vf, vt = parse_date(s.get("validFrom")), parse_date(s.get("validThrough"))
        if (vf and vf > TODAY) or (vt and vt < TODAY):
            continue
        days = s.get("dayOfWeek") or []
        days = [d.rsplit("/", 1)[-1] for d in (days if isinstance(days, list) else [days])]
        o, c = (s.get("opens") or "")[:5], (s.get("closes") or "")[:5]
        if not re.match(r"\d\d:\d\d$", o) or not re.match(r"\d\d:\d\d$", c):
            continue
        if c == "00:00" or c == "23:59":
            c = "24:00"
        if o == c == "00:00":
            continue
        for d in days:
            if d in DAYS:
                current.append((DAYS.index(d), o, c))
    if not current:
        return None
    for d, o, c in current:
        if c < o and c > "06:00":      # e.g. 18:30-10:00 is a typo, not an all-night opening
            return None
    per_day = {i: sorted({(o, c) for d, o, c in current if d == i}) for i in range(7)}
    # Group consecutive days with identical intervals.
    groups, i = [], 0
    while i < 7:
        j = i
        while j + 1 < 7 and per_day[j + 1] == per_day[i]:
            j += 1
        groups.append((i, j, per_day[i]))
        i = j + 1
    rules = []
    for a, b, iv in groups:
        days = OSM_DAYS[a] if a == b else (f"{OSM_DAYS[a]},{OSM_DAYS[b]}" if b == a + 1 else f"{OSM_DAYS[a]}-{OSM_DAYS[b]}")
        rules.append(f"{days} " + (",".join(f"{o}-{c}" for o, c in iv) if iv else "off"))
    out = "; ".join(rules)
    if out == "Mo-Su 00:00-24:00":      # placeholder used on many listings (theatres, offices)
        return None
    return out


def read_page(url):
    try:
        html = get(url)
    except Exception as ex:  # noqa: BLE001
        return {"url": url, "error": str(ex)[:100]}
    finally:
        time.sleep(0.4)
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html):
        try:
            j = json.loads(block)
        except Exception:  # noqa: BLE001
            continue
        for o in (j if isinstance(j, list) else j.get("@graph", [j])):
            if not isinstance(o, dict) or not o.get("geo") or not o.get("name"):
                continue
            g = o["geo"]
            try:
                lat, lon = float(g["latitude"]), float(g["longitude"])
            except Exception:  # noqa: BLE001
                continue
            return {"url": url, "name": o["name"], "type": o.get("@type"), "lat": lat, "lon": lon,
                    "oh": to_osm(o.get("openingHoursSpecification") or [])}
    return {"url": url, "error": "no structured data"}


def main():
    sm = get(SITEMAP)
    urls = re.findall(r"<loc>([^<]+)</loc>", sm)
    print(f"{len(urls)} Lausanne Tourisme place pages")
    with ThreadPoolExecutor(max_workers=1) as ex:
        pages = list(ex.map(read_page, urls))
    failed = [p["url"] for p in pages if p.get("error") and p["error"] != "no structured data"]
    if failed:
        print(f"Retrying {len(failed)} pages slowly")
        time.sleep(20)
        retry = {}
        for u in failed:
            retry[u] = read_page(u)
            time.sleep(1.5)
        pages = [retry.get(p["url"], p) for p in pages]
    lt = [p for p in pages if p.get("oh")]
    print(f"{len(lt)} with current opening hours, {sum(1 for p in pages if p.get('error'))} errors")

    s = (ROOT / "data" / "osm_snapshot.js").read_text(encoding="utf-8")
    els = json.loads(s[s.index("{"):s.rindex("}") + 1])["els"]
    out = {}
    for oid, lat, lon, t in els:
        if t.get("tourism") == "attraction":       # monuments and clocks, not businesses
            continue
        best, bs = None, 0
        for p in lt:
            d = haversine(lat, lon, p["lat"], p["lon"])
            if d > 150:
                continue
            sc = name_score(t.get("name"), p["name"])
            need = 0.5 if d <= 25 else 0.7
            if sc >= need and sc > bs:
                best, bs = p, sc
        if best:
            out[oid] = {"name": t.get("name"), "lt_name": best["name"], "oh": best["oh"], "url": best["url"]}
    print(f"Matched {len(out)} map places to Lausanne Tourisme listings "
          f"({sum(1 for oid, _, _, t in els if oid in out and not t.get('opening_hours'))} of them have no hours in OpenStreetMap)")
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    (ROOT / "data" / "lt_hours.js").write_text(
        "// Generated monthly by scripts/fetch_lausanne_tourisme.py from Lausanne Tourisme listings\n"
        "// (https://www.lausanne-tourisme.ch). Keyed by OpenStreetMap id. Used only where OpenStreetMap has no hours.\n"
        "window.LT_HOURS = " + json.dumps({"ts": now, "places": out}, ensure_ascii=False, indent=0) + ";\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()

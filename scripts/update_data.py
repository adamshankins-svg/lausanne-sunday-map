#!/usr/bin/env python3
"""
Weekly data job for the Lausanne opening-hours map (runs on GitHub Actions).

1. Downloads places within RADIUS_M of Place Bel-Air from OpenStreetMap (Overpass)
   and writes data/osm_snapshot.js, so the map opens instantly even before its
   own download finishes.
2. Fills missing opening hours for chain branches from All the Places
   (https://www.alltheplaces.xyz, CC0): chains' own store-finder data.
   Writes data/chain_hours.js keyed by OpenStreetMap id.
3. Writes data/hours_todo.json: places still without hours that have a website,
   for manual research (results go in data/researched_hours.js).

Standard library only.
"""
import json
import math
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CENTER = (46.5216, 6.6303)
RADIUS_M = 5000
UA = "lausanne-sunday-map/1.0 (+https://github.com/adamshankins-svg/lausanne-sunday-map)"
OVERPASS = ["https://overpass.osm.ch/api/interpreter", "https://overpass-api.de/api/interpreter"]
ATP = "https://alltheplaces-data.openaddresses.io/runs/"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_SPIDER_BYTES = 80_000_000
MATCH_M = 120

KEEP = ["name", "amenity", "shop", "tourism", "leisure", "sport", "cuisine", "opening_hours", "website",
        "contact:website", "phone", "contact:phone", "addr:street", "addr:housenumber", "addr:postcode",
        "addr:city", "brand", "brand:wikidata", "emergency", "access", "check_date:opening_hours", "check_date",
        "contact:instagram", "contact:facebook"]


def log(*a):
    print(*a, flush=True)


def get(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def haversine(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


STOP = set("le la les l de du des d et sa sarl gmbh ag the chez lausanne cafe restaurant pharmacie musee cinema station shop".split())


def fold(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def tokens(s):
    return [t for t in re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", fold(s))) if t not in STOP]


def name_score(a, b):
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    if ta <= tb or tb <= ta:
        return 0.9
    return len(ta & tb) / max(len(ta), len(tb))


def slug(s):
    return "_".join(re.findall(r"[a-z0-9]+", fold(s)))


# ---------------------------------------------------------------- OpenStreetMap
def overpass_query():
    a = f"around:{RADIUS_M},{CENTER[0]},{CENTER[1]}"
    return f"""[out:json][timeout:120];(
  nwr({a})["amenity"~"^(restaurant|cafe|bar|pub|biergarten|fast_food|ice_cream|food_court)$"];
  nwr({a})["shop"]["opening_hours"];
  nwr({a})["shop"~"^(convenience|supermarket|bakery|pastry|kiosk|newsagent|tobacco|florist|deli|greengrocer|confectionery|ice_cream|chocolate)$"];
  nwr({a})["amenity"~"^(pharmacy|hospital|cinema|theatre|arts_centre|fuel|ferry_terminal|car_rental|marketplace)$"];
  nwr({a})["amenity"~"^(clinic|doctors)$"]["opening_hours"];
  nwr({a})["tourism"~"^(museum|gallery|attraction|zoo|aquarium)$"];
  nwr({a})["leisure"~"^(sports_centre|fitness_centre|swimming_pool|ice_rink|bowling_alley|trampoline_park|miniature_golf|escape_game|water_park|amusement_arcade)$"];
  nwr({a})["sport"="climbing"]["leisure"];
  nwr({a})["shop"="laundry"];
);out center tags;"""


def fetch_osm():
    body = urllib.parse.urlencode({"data": overpass_query()}).encode()
    for ep in OVERPASS:
        try:
            log(f"Overpass: {ep}")
            j = json.loads(get(ep, body, timeout=180))
            els = []
            for e in j["elements"]:
                t = e.get("tags") or {}
                if not t.get("name"):
                    continue
                c = e.get("center") or e
                els.append([e["type"][0] + str(e["id"]), round(c["lat"], 6), round(c["lon"], 6),
                            {k: t[k] for k in KEEP if t.get(k)}])
            if len(els) < 500:
                raise RuntimeError(f"only {len(els)} places")
            log(f"  {len(els)} named places")
            return els
        except Exception as ex:  # noqa: BLE001
            log(f"  failed: {ex}")
            time.sleep(10)
    sys.exit("Could not download OpenStreetMap data")


# ---------------------------------------------------------------- All the Places
def atp_features(wanted_slugs):
    latest = json.loads(get(ATP + "latest.json"))
    run = latest["run_id"]
    results = json.loads(get(f"{ATP}{run}/stats/_results.json"))["results"]
    spiders = []
    for r in results:
        s = r["spider"]
        if not r.get("features"):
            continue
        base = re.sub(r"_[a-z]{2}$", "", s)
        country = s[len(base) + 1:] if base != s else ""
        if country == "ch" or s.endswith(("_eu", "_europe")):
            spiders.append(s)
        elif not country and any(base == w or base.startswith(w + "_") for w in wanted_slugs):
            spiders.append(s)
    log(f"All the Places run {run}: {len(spiders)} spiders to check")
    feats = []
    lat0, lon0 = CENTER
    dlat, dlon = RADIUS_M / 111000 * 1.1, RADIUS_M / 76500 * 1.1
    for s in sorted(set(spiders)):
        url = f"{ATP}{run}/output/{s}.geojson"
        try:
            raw = get(url, timeout=180)
            if len(raw) > MAX_SPIDER_BYTES:
                log(f"  {s}: too large, skipped")
                continue
            fc = json.loads(raw)
        except Exception as ex:  # noqa: BLE001
            log(f"  {s}: {ex}")
            continue
        n = 0
        for f in fc.get("features", []):
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            if abs(lat - lat0) > dlat or abs(lon - lon0) > dlon:
                continue
            p = f.get("properties") or {}
            if not p.get("opening_hours"):
                continue
            feats.append({"lat": lat, "lon": lon, "spider": s, "name": p.get("name") or p.get("brand") or "",
                          "brand": p.get("brand") or "", "wd": p.get("brand:wikidata") or "",
                          "oh": p["opening_hours"], "url": p.get("website") or p.get("@source_uri") or "",
                          "collected": (fc.get("dataset_attributes") or {}).get("spider:collection_time", "")[:10]})
            n += 1
        if n:
            log(f"  {s}: {n} locations with hours nearby")
    return run, feats


def main():
    DATA.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    els = fetch_osm()
    (DATA / "osm_snapshot.js").write_text(
        "// Generated weekly by scripts/update_data.py. Places © OpenStreetMap contributors, ODbL.\n"
        "window.OSM_SNAPSHOT = " + json.dumps({"ts": now, "els": els}, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")

    missing = [e for e in els if not e[3].get("opening_hours")]
    wanted = set()
    for _, _, _, t in missing:
        for v in (t.get("brand"), t.get("name")):
            if v and slug(v):
                wanted.add(slug(v))
    run, feats = atp_features(wanted)

    chain = {}
    for oid, lat, lon, t in missing:
        best, bd = None, MATCH_M + 1
        for f in feats:
            d = haversine(lat, lon, f["lat"], f["lon"])
            if d > MATCH_M or d >= bd:
                continue
            same_wd = t.get("brand:wikidata") and t.get("brand:wikidata") == f["wd"]
            score = max(name_score(t.get("name"), f["name"]), name_score(t.get("brand") or t.get("name"), f["brand"]))
            if same_wd or score >= 0.8:
                best, bd = f, d
        if best:
            chain[oid] = {"name": t.get("name"), "oh": best["oh"], "brand": best["brand"] or best["name"],
                          "spider": best["spider"], "url": best["url"], "collected": best["collected"], "dist_m": round(bd)}
    log(f"Matched chain hours for {len(chain)} of {len(missing)} places without hours")
    (DATA / "chain_hours.js").write_text(
        "// Generated weekly by scripts/update_data.py from All the Places (CC0), chains' own store data.\n"
        "window.CHAIN_HOURS = " + json.dumps({"ts": now, "run": run, "places": chain}, ensure_ascii=False, indent=0) + ";\n",
        encoding="utf-8")

    todo = []
    for oid, lat, lon, t in missing:
        if oid in chain:
            continue
        site = t.get("website") or t.get("contact:website") or t.get("contact:instagram") or t.get("contact:facebook")
        if not site:
            continue
        kind = t.get("amenity") or t.get("shop") or t.get("tourism") or t.get("leisure") or ""
        addr = " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x)
        todo.append({"id": oid, "name": t["name"], "kind": kind, "website": site, "address": addr,
                     "dist_m": round(haversine(CENTER[0], CENTER[1], lat, lon))})
    todo.sort(key=lambda x: x["dist_m"])
    (DATA / "hours_todo.json").write_text(json.dumps(todo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log(f"{len(todo)} places left to research (have a website)")


if __name__ == "__main__":
    main()

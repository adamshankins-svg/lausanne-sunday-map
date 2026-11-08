#!/usr/bin/env python3
"""
Fetch opening-hours text from the websites of places that have no hours in OpenStreetMap.

Reads data/hours_todo.json (written by update_data.py), visits each place's own website
plus up to three likely sub-pages (horaires, contact, infos…), and keeps only the text
around day names and opening-hours words, plus any schema.org openingHours data.
Writes research/snippets.json for a person (or Claude) to turn into opening_hours.
Standard library only.
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_KINDS = {"theatre", "arts_centre", "cinema", "ferry_terminal", "hospital"}
UA = "Mozilla/5.0 (compatible; lausanne-sunday-map/1.0; +https://github.com/adamshankins-svg/lausanne-sunday-map)"
DAYS = r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|lun\.?|mar\.?|mer\.?|jeu\.?|ven\.?|sam\.?|dim\.?|monday|tuesday|wednesday|thursday|friday|saturday|sunday|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)"
HOURS_WORDS = r"(horaire|heures d.ouverture|ouvert|ferm[ée]|opening hours|open daily|7/7|7j/7|tous les jours|öffnungszeiten)"
LINK_WORDS = re.compile(r"horaire|hours|contact|info|acces|access|about|a-propos|apropos|visit|ouverture|practical|pratique|kontakt", re.I)
TIME = re.compile(r"\b([01]?\d|2[0-4])\s?[h:.]\s?([0-5]\d)?\b")


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fr-CH,fr;q=0.9,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if "html" not in (r.headers.get("Content-Type") or "html"):
            return r.geturl(), ""
        return r.geturl(), r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


def text_of(doc):
    doc = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", doc)
    doc = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|td|th|dt|dd|span)>", "\n", doc)
    doc = html.unescape(re.sub(r"<[^>]+>", " ", doc))
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in doc.split("\n")]
    return [l for l in lines if l]


def jsonld_hours(doc):
    out = []
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', doc):
        for key in ("openingHours", "openingHoursSpecification"):
            for m in re.finditer(r'"%s"\s*:\s*(\[.*?\]|"[^"]*"|\{.*?\})' % key, block, re.S):
                out.append(m.group(1)[:600])
    return out


def snippets(lines):
    keep = set()
    for i, l in enumerate(lines):
        low = l.lower()
        if (re.search(DAYS, low) and TIME.search(low)) or re.search(HOURS_WORDS, low):
            keep.update(range(max(0, i - 2), min(len(lines), i + 6)))
    picked = [lines[i] for i in sorted(keep) if len(lines[i]) < 300]
    text = "\n".join(picked)
    return text[:2500]


def research(place):
    site = place["website"]
    if not re.match(r"https?://", site):
        site = "https://" + site.lstrip("/")
    result = {**place, "pages": [], "jsonld": [], "error": None}
    try:
        final, doc = get(site)
    except Exception as ex:  # noqa: BLE001
        result["error"] = f"{type(ex).__name__}: {str(ex)[:120]}"
        return result
    pages = [(final, doc)]
    host = urllib.parse.urlparse(final).netloc
    links = []
    for href, label in re.findall(r'(?is)<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', doc):
        u = urllib.parse.urljoin(final, html.unescape(href))
        if urllib.parse.urlparse(u).netloc == host and (LINK_WORDS.search(u) or LINK_WORDS.search(re.sub("<[^>]+>", "", label))):
            if u not in links and u != final:
                links.append(u)
    for u in links[:3]:
        try:
            pages.append(get(u))
        except Exception:  # noqa: BLE001
            pass
    for url, d in pages:
        if not d:
            continue
        s = snippets(text_of(d))
        j = jsonld_hours(d)
        if s or j:
            result["pages"].append({"url": url, "text": s})
            result["jsonld"] += j
    return result


def main():
    todo = [p for p in json.loads((ROOT / "data" / "hours_todo.json").read_text()) if p["kind"] not in SKIP_KINDS]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(research, todo))
    out = ROOT / "research"
    out.mkdir(exist_ok=True)
    (out / "snippets.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    got = sum(1 for r in results if r["pages"] or r["jsonld"])
    print(f"{len(results)} places, {got} with hours-like text, {sum(1 for r in results if r['error'])} unreachable")


if __name__ == "__main__":
    sys.exit(main())

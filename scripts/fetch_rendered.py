#!/usr/bin/env python3
"""
Read opening-hours text from websites with a real browser (handles JavaScript-built sites).

Input:  research/fetch_list.json  -> [{"id", "name", "url"}]
Output: research/rendered.json    -> [{"id", "name", "url", "pages": [{"url", "text"}], "error"}]

For each site: render the page, keep the lines around day names and opening-hours words,
then follow up to two same-site links that look like hours/contact/info pages.
"""
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
DAYS = re.compile(r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|\blun\b|\bmar\b|\bmer\b|\bjeu\b|\bven\b|\bsam\b|\bdim\b|monday|tuesday|wednesday|thursday|friday|saturday|sunday|horaire|ouvert|ferm[ée]|7/7|7j/7|tous les jours|opening)", re.I)
TIME = re.compile(r"\d{1,2}\s?[h:.]\s?\d{0,2}")
LINK = re.compile(r"horaire|hours|contact|info|acces|about|ouverture|propos|pratique|visit", re.I)


def pick(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    keep = set()
    for i, l in enumerate(lines):
        if DAYS.search(l) and (TIME.search(l) or TIME.search(lines[i + 1] if i + 1 < len(lines) else "") or re.search(r"horaire|ouvert|ferm", l, re.I)):
            keep.update(k for k in range(i - 1, i + 5) if 0 <= k < len(lines) and len(lines[k]) < 200)
    return "\n".join(lines[k] for k in sorted(keep))[:2500]


async def read(ctx, item, sem):
    async with sem:
        out = {**item, "pages": [], "error": None}
        page = await ctx.new_page()
        try:
            await page.goto(item["url"], timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(2500)
            host = urlparse(page.url).netloc
            text = await page.inner_text("body")
            if pick(text):
                out["pages"].append({"url": page.url, "text": pick(text)})
            links = await page.eval_on_selector_all("a[href]", "as => as.map(a => [a.href, a.textContent || ''])")
            seen, follow = {page.url}, []
            for href, label in links:
                if urlparse(href).netloc == host and href not in seen and (LINK.search(href) or LINK.search(label)):
                    seen.add(href)
                    follow.append(href)
            for href in follow[:2]:
                try:
                    await page.goto(href, timeout=25000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1500)
                    t = pick(await page.inner_text("body"))
                    if t:
                        out["pages"].append({"url": page.url, "text": t})
                except Exception:  # noqa: BLE001
                    pass
        except Exception as ex:  # noqa: BLE001
            out["error"] = f"{type(ex).__name__}: {str(ex)[:120]}"
        finally:
            await page.close()
        return out


async def main():
    items = json.loads((ROOT / "research" / "fetch_list.json").read_text())
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(locale="fr-CH", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        sem = asyncio.Semaphore(6)
        results = await asyncio.gather(*(read(ctx, it, sem) for it in items))
        await browser.close()
    (ROOT / "research" / "rendered.json").write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(results)} sites, {sum(1 for r in results if r['pages'])} with hours-like text, {sum(1 for r in results if r['error'])} failed")


if __name__ == "__main__":
    asyncio.run(main())

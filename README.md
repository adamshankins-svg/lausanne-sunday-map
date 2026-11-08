# Open in Lausanne

A map of everything open within 5 km of Place Bel-Air, at any time on any day. It's built for Sundays.

## Opening it

Double-click `index.html`. There's nothing to install and no terminal to use.

The first time it opens, the page downloads about 2,200 places from OpenStreetMap through the Swiss Overpass server, which takes a few seconds. It keeps a copy in the browser and refreshes it every three days. To refresh now, click **Update now** at the bottom of the side panel.

## Using it

- **Search** (top left, or press `/`). Search covers every place, including ones that are closed or have no hours. Picking a result zooms to it and opens its details.
- **Category chips:** clicking one chip while all categories are shown narrows the map to just that category. Click others to add them back.
- **Timeline** (bottom): the bars show how many places are open in each half-hour. Drag the slider or click a bar to change the time. Use the day menu to check another day. Public holidays in Vaud are marked and handled.
- **Dots:**
  - A filled dot is open.
  - A ring has no hours listed in OpenStreetMap. Rings are shown for food and drink by default; use "No hours listed" in the side panel to show them for everything or hide them.
  - A grey dot is closed, and only appears when "Show closed places" is ticked.
- **Side panel:** lists what's open in the visible part of the map, nearest the centre first. Click a place for its full week, directions, website and a link to fix it on OpenStreetMap.
- **Background menu** (top right): Light (the default), swisstopo light, Colourful, or the classic swisstopo grey. None of them need an API key.

## Wrong or missing hours?

Most data comes from OpenStreetMap volunteers. If a place shows wrong hours, use **Fix on OpenStreetMap** in its details. Your fix appears here after the next update.

`data/curated.js` holds about 85 hand-researched places, such as station shops, museums and Christmas markets, with notes and source badges. Edit it in any text editor and reload the page. Hours use [OpenStreetMap syntax](https://wiki.openstreetmap.org/wiki/Key:opening_hours).

## Where the hours come from

1. **OpenStreetMap** (most places). A GitHub job refreshes `data/osm_snapshot.js` every Monday, and the page can also download fresh data itself ("Update now").
2. **All the Places** (chain branches with no hours in OpenStreetMap, such as Denner, k kiosk, Brezelkönig, avec and petrol stations). This is chains' own store-finder data, released under CC0. The same weekly job matches it to the map and writes `data/chain_hours.js`.
3. **Website research** (`data/researched_hours.js`): hours read from about 60 independent places' own websites on 8 November 2026. Each entry links to the page it came from. These hours don't update themselves, so recheck them now and then. A second job, `fetch-snippets.yml`, collects hours text from places' websites into `research/snippets.json` to make that easier. Run it from the repository's Actions tab.

4. **Lausanne Tourisme** (`data/lt_hours.js`): hours from the tourism office's listings, read once a month by `lausanne-tourisme.yml`, and used only when sources 1–3 have nothing.

A place's details always say which source its hours came from. Hours from 2–4 only fill gaps; they never override OpenStreetMap.

## Files

- `index.html`: the whole app
- `data/curated.js`: the researched places
- `vendor/`: MapLibre GL JS 5, opening_hours.js and SunCalc, bundled so nothing loads from a CDN

## Credits

- Places: © OpenStreetMap contributors (ODbL), via overpass.osm.ch.
- Background maps: OpenFreeMap / OpenMapTiles, and © swisstopo.
- Libraries: MapLibre GL JS (BSD-3), opening_hours.js (LGPL-3.0), SunCalc (BSD-2).

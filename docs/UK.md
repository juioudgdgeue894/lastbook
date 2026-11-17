# Building a UK map (Scotland first)

The map tools were written for the United States. This page builds the detailed map for a UK region
from open data. Scotland is the worked example; England and Wales follow the same steps.

## Sources

| File | From | Licence | Gives |
|---|---|---|---|
| `scotland-latest-free.gpkg.zip` | download.geofabrik.de/europe/united-kingdom/ | ODbL 1.0 | Streets, water, land use, buildings, places, help points |
| `scotland-latest.osm.pbf` | the same | ODbL 1.0 | Coastline, so the sea can be drawn |
| `opname_csv_gb.zip` | Ordnance Survey Data Hub, OS Open Names (CSV, GB) | Open Government Licence v3.0 | Towns, villages, postcodes, named roads, hills, lochs (English and Gaelic names) |

Contains OS data © Crown copyright and database right. Map data © OpenStreetMap contributors.

## Steps

```bash
DATA=/path/to/LastbookData            # the app's data folder
SRC=/path/to/sources                  # where the downloads were saved
unzip -p "$SRC/scotland-latest-free.gpkg.zip" '*.gpkg' > "$SRC/scotland.gpkg"
python3 tools/build_map.py "$SRC/scotland.gpkg" "$DATA/derived/geo/map.sqlite" --region Scotland --country GB --as-of <Geofabrik date>
python3 tools/build_coast.py "$SRC/scotland-latest.osm.pbf" "$DATA/derived/geo/map.sqlite" --land-border 54.4
python3 tools/build_places_uk.py "$SRC/opname_csv_gb.zip" --data "$DATA" --country Scotland --region Scotland
```

`build_coast.py` needs `osmium`, `build_places_uk.py` needs `pyproj`.

## What changes in the app

- The detailed area is read from `map.sqlite` (`meta.bounds`), not a fixed Southern California box.
- A map built with `--country GB` uses UK words in search (town, village, postcode) and lists UK sources.
- Postcodes can be typed with or without the space (`KY1 1AA` or `KY11AA`).

## Not yet for the UK

- Full address search: there is no free UK address list. Postcode search is the nearest open equivalent.
- Elevation and contours (OS Terrain 50 would replace USGS 3DEP), building heights, dams and crops.
- The US base map of main roads (`national.sqlite`) is not used: outside the region only the world outline shows.

## Local AI: Qwen3.6 35B A3B uncensored

`llm_local.py` speaks Qwen3.6's chat format (from Qwen/Qwen3.6-35B-A3B's `chat_template.jinja`, thinking off) and reads its
`<tool_call><function=...>` calls. The model is llmfan46's Heretic build, `Qwen3.6-35B-A3B-uncensored-heretic-Q4_K_M.gguf`
(21.2 GB, SHA-256 in `llm_local.py` and `packaging/manifest-uk.json`). `LASTBOOK_MODEL_FAMILY=gemma` switches back to upstream's
Gemma 4. Measured on an M4 Pro with 48 GB: 22.2 GB in memory, about 14 s to load, first words in about 1 s, about 50 tokens a
second. The model starts loading when the Chat page opens.

## Library: Medium, trimmed, plus survival videos from All

- `tools/zip_pick.py` takes single files out of `Lastbook-All.zip` with range requests (its table of contents is at the end),
  so 425 survival videos (Corporals Corner knots, rope, water, fire, shelter, traps, navigation, first aid; the rest of
  Primitive Technology; water safety; hunting; field medicine) come without the 388 GB download.
- `tools/merge_pick.py` adds them to `catalog.json` and `search.sqlite`, drops the Honda lawn mower, snow blower and garden
  tool videos, and swaps the US map files for the Scotland map.
- Setup's map choice defaults to "No US map (outside the US)".

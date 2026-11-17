#!/usr/bin/env python3
"""Build the offline place finder (derived/geo/places.sqlite) for a UK map from Ordnance Survey OS Open Names
(Open Government Licence v3.0) and named OpenStreetMap places/points from derived/geo/map.sqlite (ODbL).

OS Open Names holds every GB settlement, postcode, named road, hill and loch, in British National Grid
(EPSG:27700). Rows are converted to WGS84 with pyproj and kept only for the countries asked for.
The source zip is read, never modified.

  python3 tools/build_places_uk.py <opname_csv_gb.zip> --data <data folder> --country Scotland

Needs: pyproj. Writes <data>/derived/geo/places.sqlite (replaced).
"""
import argparse, csv, io, re, sqlite3, struct, zipfile
from pathlib import Path

from pyproj import Transformer

# Column order of the OS Open Names CSV (the data files have no header row; Doc/OS_Open_Names_Header.csv has it).
COLS = ['ID', 'NAMES_URI', 'NAME1', 'NAME1_LANG', 'NAME2', 'NAME2_LANG', 'TYPE', 'LOCAL_TYPE', 'GEOMETRY_X', 'GEOMETRY_Y',
        'MOST_DETAIL_VIEW_RES', 'LEAST_DETAIL_VIEW_RES', 'MBR_XMIN', 'MBR_YMIN', 'MBR_XMAX', 'MBR_YMAX', 'POSTCODE_DISTRICT',
        'POSTCODE_DISTRICT_URI', 'POPULATED_PLACE', 'POPULATED_PLACE_URI', 'POPULATED_PLACE_TYPE', 'DISTRICT_BOROUGH',
        'DISTRICT_BOROUGH_URI', 'DISTRICT_BOROUGH_TYPE', 'COUNTY_UNITARY', 'COUNTY_UNITARY_URI', 'COUNTY_UNITARY_TYPE',
        'REGION', 'REGION_URI', 'COUNTRY', 'COUNTRY_URI', 'RELATED_SPATIAL_OBJECT', 'SAME_AS_DBPEDIA', 'SAME_AS_GEONAMES']
SETTLEMENT = {'City', 'Town', 'Village', 'Hamlet', 'Other Settlement', 'Suburban Area'}
ROAD = {'Named Road', 'Numbered Road'}
# Lower rank sorts first in the finder: towns, then postcodes, then roads and natural features.
RANK = {'populatedPlace': 1, 'other': 3, 'transportNetwork': 3, 'hydrography': 3, 'landform': 3, 'landcover': 4}


def header(z):
    doc = next((n for n in z.namelist() if n.lower().endswith('header.csv')), None)
    if doc:
        with z.open(doc) as f:
            cols = next(csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig')))
            if 'NAME1' in cols and 'COUNTRY' in cols:
                return [c.strip() for c in cols]
    return COLS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('zip', help='opname_csv_gb.zip from the OS Data Hub (read only)')
    ap.add_argument('--data', required=True, help='Lastbook data folder (holds derived/)')
    ap.add_argument('--country', action='append', help='Keep only these countries (Scotland, England, Wales). Default: all')
    ap.add_argument('--region', default='', help='Name for OpenStreetMap rows, e.g. Scotland')
    a = ap.parse_args()
    keep = set(a.country or [])
    data = Path(a.data)
    out = data / 'derived/geo/places.sqlite'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    db = sqlite3.connect(out)
    db.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);
      CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');''')
    ins = 'INSERT INTO place(name,kind,detail,lat,lon,rank,source) VALUES (?,?,?,?,?,?,?)'
    to_wgs = Transformer.from_crs('EPSG:27700', 'EPSG:4326', always_xy=True)
    counts = {}
    with zipfile.ZipFile(a.zip) as z:
        cols = header(z)
        members = sorted(n for n in z.namelist() if re.search(r'DATA/.*\.csv$', n, re.I))
        for m in members:
            with z.open(m) as f:
                for row in csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace')):
                    r = dict(zip(cols, row))
                    if keep and r.get('COUNTRY') not in keep:
                        continue
                    t, lt = r.get('TYPE', ''), r.get('LOCAL_TYPE', '')
                    if t == 'transportNetwork' and lt not in ROAD:
                        continue
                    try:
                        lon, lat = to_wgs.transform(float(r['GEOMETRY_X']), float(r['GEOMETRY_Y']))
                    except (KeyError, ValueError):
                        continue
                    area = r.get('COUNTY_UNITARY') or r.get('DISTRICT_BOROUGH') or ''
                    place = r.get('POPULATED_PLACE') or ''
                    if lt == 'Postcode':
                        code = r['NAME1'].strip()
                        # "KY11AA" finds "KY1 1AA": the squashed form goes in the searchable detail
                        detail = ', '.join(v for v in (place, area) if v) + ' · ' + code.replace(' ', '')
                        db.execute(ins, (code, 'Postcode', detail, lat, lon, 2, 'Ordnance Survey OS Open Names'))
                    else:
                        where = ', '.join(v for v in (place if place != r['NAME1'] else '', area) if v)
                        rank = 1 if lt in SETTLEMENT else RANK.get(t, 3)
                        for name in {r['NAME1'], r.get('NAME2', '')} - {''}:  # Gaelic and English names both find the place
                            db.execute(ins, (name, lt, where, lat, lon, rank, 'Ordnance Survey OS Open Names'))
                    counts[lt] = counts.get(lt, 0) + 1
    n = sum(counts.values())
    m = data / 'derived/geo/map.sqlite'
    if m.exists():  # named help points (hospitals, chemists...) and OSM places, as the US builder does
        label = f'{a.region} (OpenStreetMap)' if a.region else 'OpenStreetMap'
        src = sqlite3.connect(f'file:{m}?mode=ro', uri=True)
        for cls, name, lon, lat in src.execute("SELECT cls,name,lon,lat FROM poi WHERE name IS NOT NULL AND name<>''"):
            db.execute(ins, (name, cls.replace('_', ' '), label, lat, lon, 4, 'OpenStreetMap'))
            n += 1
        for cls, name, g in src.execute("SELECT cls,name,geom FROM feat WHERE layer='place' AND name IS NOT NULL"):
            _, _, x, y = struct.unpack_from('<iiii', g)
            db.execute(ins, (name, cls, label, y / 1e6, x / 1e6, 5, 'OpenStreetMap'))  # after OS names: same towns, OS has the area
            n += 1
    db.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
    db.commit()
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f'{v:>9,}  {k}')
    print('places', n)


main()

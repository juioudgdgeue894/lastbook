#!/usr/bin/env python3
"""Add an ocean polygon to the offline map. The Geofabrik "free" GeoPackage has no coastline, so this reads
natural=coastline ways from the SoCal .osm.pbf (read only) with pyosmium, joins them into chains, and closes
the open mainland chain out to sea. Islands are stored as land rings drawn on top of the ocean.

  derived/buildenv/bin/python tools/build_coast.py library-data/geography/openstreetmap/socal-latest.osm.pbf derived/geo/map.sqlite

A region whose coast ends at a land border (Scotland, at England) has sea on both sides, so closing out to the
west does not work. --land-border LAT instead draws the sea as one box around the region and closes the
mainland chain overland, south of LAT, so it becomes a land ring drawn on top like an island:

  python3 tools/build_coast.py scotland-latest.osm.pbf derived/geo/map.sqlite --land-border 54.4
"""
import argparse, sqlite3
import osmium

_ap = argparse.ArgumentParser()
_ap.add_argument('pbf')
_ap.add_argument('dst')
_ap.add_argument('--land-border', type=float, help='latitude south of the region, overland, to close the mainland through')
ARGS = _ap.parse_args()
PBF, DST = ARGS.pbf, ARGS.dst


class Coast(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []

    def way(self, w):
        if w.tags.get('natural') == 'coastline':
            try:
                self.ways.append(([n.ref for n in w.nodes], [(n.lon, n.lat) for n in w.nodes]))
            except osmium.InvalidLocationError:
                pass


def chains(ways):
    by_start = {}
    for refs, pts in ways:
        by_start.setdefault(refs[0], []).append((refs, pts))
    used = set()
    out = []
    for refs, pts in ways:
        if id(pts) in used:
            continue
        used.add(id(pts))
        r, p = list(refs), list(pts)
        while r[-1] != r[0]:
            nxt = [w for w in by_start.get(r[-1], []) if id(w[1]) not in used]
            if not nxt:
                break
            used.add(id(nxt[0][1]))
            r += nxt[0][0][1:]
            p += nxt[0][1][1:]
        out.append((r[0] == r[-1], p))
    # join open chains whose start is another chain's end (pieces processed out of order)
    merged = True
    while merged:
        merged = False
        opens = [c for c in out if not c[0]]
        for a in opens:
            for b in opens:
                if a is not b and a[1][-1] == b[1][0]:
                    out.remove(a); out.remove(b)
                    out.append((a[1][0] == b[1][-1], a[1] + b[1][1:]))
                    merged = True
                    break
            if merged:
                break
    return out


def pack(parts):
    from array import array
    a = array('i', [len(parts)])
    for p in parts:
        a.append(len(p))
        lx = ly = 0
        for x, y in p:
            x, y = int(round(x * 1e6)), int(round(y * 1e6))
            a.append(x - lx); a.append(y - ly)
            lx, ly = x, y
    return a.tobytes()


h = Coast()
h.apply_file(PBF, locations=True, idx='flex_mem')
cs = chains(h.ways)
closed = [p for c, p in cs if c]
opened = sorted([p for c, p in cs if not c], key=len, reverse=True)
print('coast ways', len(h.ways), 'closed rings', len(closed), 'open chains', [len(p) for p in opened[:5]])
db = sqlite3.connect(DST)
db.execute("DELETE FROM feat_idx WHERE id IN (SELECT id FROM feat WHERE layer IN ('ocean','island'))")
db.execute("DELETE FROM feat WHERE layer IN ('ocean','island')")
nid = db.execute('SELECT max(id) FROM feat').fetchone()[0] + 1
rings = []
if ARGS.land_border is not None:
    # Sea: one box around everything, drawn first. Land: the mainland chain closed overland to the south, plus islands.
    xs = [x for p in opened + closed for x, _ in p]; ys = [y for p in opened + closed for _, y in p]
    w, e, s, n = min(xs) - 2, max(xs) + 2, ARGS.land_border, max(ys) + 2
    rings.append([(w, s), (e, s), (e, n), (w, n), (w, s)])
    if opened:
        main = opened[0]  # the longest open chain is the mainland coast, cut where the region meets its land border
        closed.append(main + [(main[-1][0], s), (main[0][0], s), main[0]])
        print('mainland closed overland; other open chains left out:', [len(p) for p in opened[1:]])
else:
    W = -125.0  # well out to sea
    for p in opened:
        # land is on the left of coastline direction; close each open chain through the sea to the west.
        rings.append(p + [(W, p[-1][1]), (W, p[0][1]), p[0]])
for ring in rings:
    xs = [x for x, _ in ring]; ys = [y for _, y in ring]
    db.execute('INSERT INTO feat VALUES (?,?,?,?,?,?)', (nid, 'ocean', 'ocean', None, 0, pack([ring])))
    db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (nid, min(xs), max(xs), min(ys), max(ys), 0, 30))
    nid += 1
for ring in closed:
    xs = [x for x, _ in ring]; ys = [y for _, y in ring]
    # OSM closed coastline rings around land run counter-clockwise; water "holes" (lakes on islands) are rare here.
    db.execute('INSERT INTO feat VALUES (?,?,?,?,?,?)', (nid, 'island', 'island', None, 0, pack([ring])))
    db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (nid, min(xs), max(xs), min(ys), max(ys), 0, 30))
    nid += 1
db.commit()
print('stored', len(rings), 'ocean rings', len(closed), 'islands')

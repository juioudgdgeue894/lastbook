#!/usr/bin/env python3
"""Make an installed library the UK fork's: add records picked from another pack, drop unwanted categories, swap the map.

  python3 tools/merge_pick.py <LastbookData> --add <picked-records.json> <files root> \
      --drop-category lawn-mower --drop-category snow-blower --drop-category garden-power-equipment \
      --map <folder with map.sqlite and places.sqlite> --map-name Scotland

--add copies each record's files (path, text_path) from <files root>/LastbookData/library-data into the library, adds the
records to catalog.json and adds a search row for each video (its transcript, or its title and notes).
--drop-category removes those records, their files and their search rows.
--map replaces the US map files in derived/geo with the given map.sqlite and places.sqlite; the US ones are deleted.
catalog.json and search.sqlite are rewritten in place (a .bak copy of catalog.json is kept beside it).
"""
import argparse, json, os, shutil, sqlite3
from pathlib import Path

US_GEO = ('buildings.sqlite', 'crops.sqlite', 'map.sqlite', 'national.sqlite', 'national-status.json', 'places.sqlite',
          'socal-cells.json', 'terrain.sqlite', 'water.sqlite', 'terrain-detail.sqlite', 'aerial.sqlite')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data')
    ap.add_argument('--add', nargs=2, metavar=('RECORDS', 'ROOT'))
    ap.add_argument('--drop-category', action='append', default=[])
    ap.add_argument('--map')
    ap.add_argument('--map-name', default='')
    a = ap.parse_args()
    data = Path(a.data)
    lib = data / 'library-data'
    cat_path = lib / 'catalog.json'
    cat = json.loads(cat_path.read_text(encoding='utf-8'))
    shutil.copy2(cat_path, cat_path.with_suffix('.json.bak'))
    db = sqlite3.connect(lib / 'search.sqlite')

    # -- drop
    drop = set(a.drop_category)
    gone = {r['id'] for r in cat if r.get('category') in drop}
    gone |= {r['id'] for r in cat if r['kind'] == 'metadata' and r['id'].replace('metadata-', '', 1) in gone}
    freed = 0
    for r in cat:
        if r['id'] in gone:
            for k in ('path', 'text_path'):
                p = lib / r[k] if r.get(k) else None
                if p and p.is_file():
                    freed += p.stat().st_size
                    p.unlink()
    db.executemany('DELETE FROM pages WHERE doc_id=?', [(i,) for i in gone])
    cat = [r for r in cat if r['id'] not in gone]
    print(f'dropped {len(gone)} records, {freed / 1e9:.1f} GB')

    # -- add
    if a.add:
        recs = json.loads(Path(a.add[0]).read_text(encoding='utf-8'))
        src = Path(a.add[1]) / 'LastbookData' / 'library-data'
        have = {r['id'] for r in cat}
        added, missing = 0, 0
        for r in recs:
            if r['id'] in have:
                continue
            files = [r[k] for k in ('path', 'text_path') if r.get(k)]
            if not all((src / f).is_file() for f in files):
                missing += 1
                continue
            for f in files:
                (lib / f).parent.mkdir(parents=True, exist_ok=True)
                os.replace(src / f, lib / f)
            cat.append(r)
            have.add(r['id'])
            added += 1
            if r['kind'] == 'video':
                t = lib / r['text_path'] if r.get('text_path') else None
                body = t.read_text(encoding='utf-8', errors='replace') if t and t.is_file() else f"{r['title']}\n{r.get('notes', '')}"
                db.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?)',
                           (r['id'], r['title'], r.get('collection', ''), r.get('category', ''), r['path'], 1, body))
        print(f'added {added} records, {missing} left out (files missing)')

    db.execute("INSERT INTO pages(pages) VALUES('optimize')")
    db.commit()
    db.close()
    tmp = cat_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(cat, indent=1, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, cat_path)

    # -- pack description and map
    pj = data / 'pack.json'
    pack = json.loads(pj.read_text(encoding='utf-8'))
    counts = {}
    for r in cat:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    pack['counts'] = dict(sorted(counts.items()))
    pack['add_ons'] = sorted(set(pack.get('add_ons') or []) | ({'uk-survival-videos'} if a.add else set()))
    if a.map:
        geo = data / 'derived' / 'geo'
        geo.mkdir(parents=True, exist_ok=True)
        for f in US_GEO:
            if (geo / f).exists():
                (geo / f).unlink()
        for f in ('map.sqlite', 'places.sqlite'):
            shutil.copy2(Path(a.map) / f, geo / f)
        pack['map'] = a.map_name or 'base'
        print('map:', pack['map'])
    pj.write_text(json.dumps(pack, indent=1, ensure_ascii=False), encoding='utf-8')
    print('records now', len(cat), counts)


if __name__ == '__main__':
    main()

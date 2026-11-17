#!/usr/bin/env python3
"""Take chosen files out of a pack zip on the download server without downloading the whole zip.

The zip's table of contents (central directory) sits at its end; each file can then be fetched with an HTTP range request
and unpacked on its own. Lastbook-All.zip is 388 GB; a few hundred videos from it are a few GB.

  python3 tools/zip_pick.py list  <url> <size>                     prints every member: name, compressed size, size
  python3 tools/zip_pick.py get   <url> <size> <dest> <names.txt>  writes each listed member under <dest> (path as in the zip)

Each member's CRC-32 is checked after unpacking. Nothing is written for a member that fails the check.
"""
import json, os, struct, sys, urllib.request, zlib
from pathlib import Path


def fetch(url, start, end):
    req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{end}', 'User-Agent': 'Lastbook-UK-zip-pick/1'})
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status != 206:
            raise RuntimeError(f'server did not send a range ({r.status})')
        return r.read()


def directory(url, size):
    tail = fetch(url, max(0, size - 65_557), size - 1)
    i = tail.rfind(b'PK\x05\x06')
    if i < 0:
        raise RuntimeError('no end of central directory')
    cd_size, cd_off = struct.unpack_from('<II', tail, i + 12)
    entries = struct.unpack_from('<H', tail, i + 10)[0]
    if cd_off == 0xFFFFFFFF or entries == 0xFFFF:       # zip64
        j = tail.rfind(b'PK\x06\x07', 0, i)
        z64 = struct.unpack_from('<Q', tail, j + 8)[0]
        rec = fetch(url, z64, z64 + 55)
        entries, cd_size, cd_off = struct.unpack_from('<QQQ', rec, 32)
    cd = fetch(url, cd_off, cd_off + cd_size - 1)
    out, p = [], 0
    while p < len(cd) and cd[p:p + 4] == b'PK\x01\x02':
        method, = struct.unpack_from('<H', cd, p + 10)
        crc, csize, usize = struct.unpack_from('<III', cd, p + 16)
        nlen, xlen, clen = struct.unpack_from('<HHH', cd, p + 28)
        off, = struct.unpack_from('<I', cd, p + 42)
        name = cd[p + 46:p + 46 + nlen].decode('utf-8', 'replace')
        extra = cd[p + 46 + nlen:p + 46 + nlen + xlen]
        q = 0
        while q + 4 <= len(extra):                         # zip64 extra field: the 0xFFFFFFFF values, in order
            hid, hlen = struct.unpack_from('<HH', extra, q)
            if hid == 1:
                vals, r = [], q + 4
                for v in (usize, csize, off):
                    if v == 0xFFFFFFFF:
                        vals.append(struct.unpack_from('<Q', extra, r)[0]); r += 8
                    else:
                        vals.append(v)
                usize, csize, off = vals
            q += 4 + hlen
        out.append({'name': name, 'method': method, 'crc': crc, 'csize': csize, 'size': usize, 'off': off})
        p += 46 + nlen + xlen + clen
    return out


def get_member(url, m, dest):
    head = fetch(url, m['off'], m['off'] + 29)
    nlen, xlen = struct.unpack_from('<HH', head, 26)
    start = m['off'] + 30 + nlen + xlen
    target = Path(dest) / m['name']
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.part')
    crc, pos, step = 0, start, 16 * 2**20
    d = zlib.decompressobj(-15) if m['method'] == 8 else None
    mode = 'wb'
    if d is None and tmp.is_file() and 0 < tmp.stat().st_size <= m['size']:   # stored member: carry on from what is there
        with open(tmp, 'rb') as f:
            while chunk := f.read(16 * 2**20):
                crc = zlib.crc32(chunk, crc)
        pos, mode = start + tmp.stat().st_size, 'ab'
    with open(tmp, mode) as f:
        while pos < start + m['csize']:
            chunk = fetch(url, pos, min(pos + step, start + m['csize']) - 1)
            pos += len(chunk)
            data = d.decompress(chunk) if d else chunk
            crc = zlib.crc32(data, crc)
            f.write(data)
        if d:
            rest = d.flush(); crc = zlib.crc32(rest, crc); f.write(rest)
    if crc != m['crc'] or tmp.stat().st_size != m['size']:
        tmp.unlink()
        raise RuntimeError(f'{m["name"]}: check failed')
    os.replace(tmp, target)


def main():
    cmd, url, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
    members = directory(url, size)
    if cmd == 'list':
        for m in members:
            print(json.dumps(m, ensure_ascii=False))
        return
    dest, wanted = sys.argv[4], set(Path(sys.argv[5]).read_text(encoding='utf-8').split('\n')) - {''}
    by = {m['name']: m for m in members}
    missing = wanted - set(by)
    if missing:
        print('not in the zip:', len(missing), sorted(missing)[:5], flush=True)
    done = 0
    for name in sorted(wanted & set(by)):
        t = Path(dest) / name
        if t.is_file() and t.stat().st_size == by[name]['size']:
            done += 1
            continue
        for attempt in range(30):
            try:
                get_member(url, by[name], dest)
                break
            except Exception as e:
                print('retry', name, type(e).__name__, e, flush=True)
        done += 1
        print(f'{done}/{len(wanted)} {name}', flush=True)


if __name__ == '__main__':
    main()

# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-online: firmware catalogue from aixun-updates.github.io (read-only; never flashes).

    t3x-online list --product T3BS              # versions the site lists, newest first
    t3x-online get T3BS 1.16 --dest firmware    # download, check, compare, save (+ .source.json)
    t3x-online get T3BS latest --dest firmware
    t3x-online compare firmware --product T3BS  # are my files the same bytes as the site's?
"""

from __future__ import annotations

import argparse
import sys

from ..core import online


def _catalog(a) -> online.Catalog:
    return online.fetch_catalog(cache_dir=a.cache_dir, refresh=a.refresh)


def _header(cat: online.Catalog) -> None:
    print(f"Site      : {cat.site}")
    print(f"Data host : {cat.data_host}  (named by the site's own config.js; the site's download links point here)")
    print(f"List      : {cat.note}")


def _timings(a) -> None:
    if a.verbose and online.FETCH_LOG:
        print("\nRequests:")
        for f in online.FETCH_LOG:
            print(f"  {f.describe()}")


def cmd_list(a) -> int:
    cat = _catalog(a)
    _header(cat)
    products = [a.product] if a.product else cat.products()
    if a.product and a.product not in cat.entries:
        print(f"\nThe site lists no product called {a.product}. Products: {', '.join(cat.products())}")
        return 2
    for p in products:
        es = cat.for_product(p)
        print(f"\n{p}  ({len(es)} versions)")
        if not a.product:
            continue
        for e in es:
            note = e.notes.splitlines()[0] if e.notes else ""
            print(f"  {e.version:<7} {e.date:<11} {e.file_name or '(no file)':<24} {note[:60]}")
    _timings(a)
    return 0


def cmd_get(a) -> int:
    cat = _catalog(a)
    _header(cat)
    es = cat.for_product(a.product)
    if not es:
        print(f"The site lists no product called {a.product}.")
        return 2
    e = es[0] if a.version == "latest" else cat.find(a.product, a.version)
    if not e:
        print(f"{a.product} {a.version} is not listed. Listed: {', '.join(x.version for x in es)}")
        return 2
    print(f"\nDownloading {e.product} {e.version} ({e.date}) from {e.mirror_url}")
    d = online.download(e, a.dest, cross_check=not a.no_cross_check, catalog=cat)
    print(f"  size       : {d.size} bytes")
    print(f"  SHA-256    : {d.sha256}")
    print(f"  compared   : {d.cross_check}" + (f"  (second address: {e.vendor_url})" if e.vendor_url else ""))
    print(f"  result     : {d.status}" + (f" -> {d.path}" if d.path else ""))
    if d.ok:
        print("  Image checks (header, size, CRC, vectors, product, version): PASS")
    _timings(a)
    return 0 if d.ok else 2


def cmd_compare(a) -> int:
    cat = _catalog(a)
    _header(cat)
    rows = online.compare_local(a.directory, cat, a.product)
    if not rows:
        print("\nNo valid images found to compare.")
        return 1
    print()
    for r in rows:
        print(f"  {r.file:<26} {r.product:<6} {r.version:<6} {r.result}")
        print(f"      SHA-256 {r.sha256}")
    _timings(a)
    return 2 if any(r.result.startswith("DIFFERENT") for r in rows) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Firmware catalogue from aixun-updates.github.io (never flashes)")
    ap.add_argument("--cache-dir", help="keep the last version list here and reuse it (e.g. results/online)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--refresh", action="store_true",
                        help="read the version list again even if a saved one is recent")
    common.add_argument("-v", "--verbose", action="store_true",
                        help="show what each request cost (size, time, IPv4/IPv6)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", parents=[common], help="products, or the versions of one product")
    p.add_argument("--product", help="e.g. T3BS (the product your station reports)")
    p = sub.add_parser("get", parents=[common], help="download one version into a folder")
    p.add_argument("product")
    p.add_argument("version", help="e.g. 1.16, or 'latest'")
    p.add_argument("--dest", required=True, help="folder to save into (e.g. firmware)")
    p.add_argument("--no-cross-check", action="store_true",
                   help="don't compare with the second address the site records for the file")
    p = sub.add_parser("compare", parents=[common], help="compare local images with the site's copies")
    p.add_argument("directory")
    p.add_argument("--product")
    a = ap.parse_args(argv)
    try:
        code = {"list": cmd_list, "get": cmd_get, "compare": cmd_compare}[a.cmd](a)
    except online.OnlineError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()

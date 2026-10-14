# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-image: inspect AiXun update files offline (no station needed).

    t3x-image info JC_M_T3BS_1.16.bin [more.bin ...]
    t3x-image scan ~/Downloads/aixun --product T3BS
    t3x-image diff JC_M_T3B_1.16.bin JC_M_T3BS_1.16.bin
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from ..core import image as fw


def _row(img: fw.FirmwareImage) -> dict:
    return {
        "file": img.path, "product": img.product_str, "version": img.version_str,
        "header": img.header_name.decode(errors="replace"), "size": img.size, "chunks": img.n_chunks,
        "crc": f"{img.crc_calc:04X}", "sha256": hashlib.sha256(img.data).hexdigest(),
        "stack_pointer": f"0x{img.stack_pointer:08X}", "reset_handler": f"0x{img.reset_handler:08X}",
        "valid": img.valid, "checks": {c.name: {"ok": c.ok, "detail": c.detail} for c in img.checks},
    }


def cmd_info(a) -> int:
    rows, ok = [], True
    for path in a.files:
        try:
            img = fw.load(path)
        except fw.ImageError as e:
            print(f"{path}: ERROR {e}", file=sys.stderr)
            ok = False
            continue
        r = _row(img)
        rows.append(r)
        ok &= img.valid
        if not a.json:
            print(f"\n{path}")
            for k in ("product", "version", "header", "size", "chunks", "crc", "sha256",
                      "stack_pointer", "reset_handler"):
                print(f"  {k:<14}: {r[k]}")
            for c in img.checks:
                print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name:<8} {c.detail}")
    if a.json:
        print(json.dumps(rows, indent=2))
    return 0 if ok else 2


def cmd_scan(a) -> int:
    imgs = fw.scan_directory(a.directory)
    if a.product:
        imgs = [i for i in imgs if i.product_str == a.product]
    if a.json:
        print(json.dumps([_row(i) for i in imgs], indent=2))
        return 0
    if not imgs:
        print("No update images found.")
        return 1
    print(f"{'file':<34} {'product':<8} {'version':<8} {'size':>8}  {'crc':<4}  status")
    for i in imgs:
        bad = ", ".join(c.name for c in i.checks if not c.ok)
        name = (i.path or "").split("/")[-1]
        print(f"{name:<34} {i.product_str:<8} {i.version_str:<8} {i.size:>8}  {i.crc_calc:04X}  "
              f"{'OK' if i.valid else 'INVALID: ' + bad}")
    return 0


def cmd_diff(a) -> int:
    x, y = fw.load(a.a), fw.load(a.b)
    d = fw.diff_images(x, y)
    if a.json:
        print(json.dumps({"a": _row(x), "b": _row(y), "same_size": d.same_size,
                          "differing_bytes": d.differing_bytes, "differing_pct": round(d.differing_pct, 1),
                          "strings_only_in_a": d.only_in_a, "strings_only_in_b": d.only_in_b}, indent=2))
        return 0
    print(f"A: {a.a}  ({x.product_str} v{x.version_str}, {x.size} B)")
    print(f"B: {a.b}  ({y.product_str} v{y.version_str}, {y.size} B)")
    print(f"Payload bytes differing: {d.differing_bytes} / {d.compared_bytes} ({d.differing_pct:.1f}%)")
    print(f"Identity strings only in A: {', '.join(d.only_in_a) or '-'}")
    print(f"Identity strings only in B: {', '.join(d.only_in_b) or '-'}")
    if x.product != y.product:
        print("\nDifferent product lines: do not cross-flash.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspect AiXun T3x update images offline")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="header, CRC, vector table and checks")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("scan", help="list valid images in a directory")
    p.add_argument("directory")
    p.add_argument("--product", help="only this product line, e.g. T3BS")
    p = sub.add_parser("diff", help="compare two images")
    p.add_argument("a")
    p.add_argument("b")
    a = ap.parse_args(argv)
    sys.exit({"info": cmd_info, "scan": cmd_scan, "diff": cmd_diff}[a.cmd](a))


if __name__ == "__main__":
    main()

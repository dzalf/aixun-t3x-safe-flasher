# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-probe: read-only communication test (same output as t3x_probe.py)."""

from __future__ import annotations

import argparse
import json
import sys
import time

import serial

from ..core import image as fwimage
from ..core.link import DeviceLost
from ..core.probe import (PortUnavailable, ProbeError, ProbeReport, ProbeSession, Reply, find_station,
                          usb_details)
from ..core.protocol import READ_ONLY_COMMANDS

say = print   # replaced by a no-op in --json mode


def hexdump(data: bytes, indent: str = "      ") -> str:
    if not data:
        return indent + "(no bytes)"
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{indent}{i:04X}  {hx:<47}  {asc}")
    return "\n".join(lines)


def section(title: str) -> None:
    say(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def print_fw(path: str):
    """Offline image check. Returns the parsed image (or None if unreadable)."""
    section("Firmware file (offline check, nothing sent)")
    try:
        img = fwimage.load(path)
    except fwimage.ImageError as e:
        say(f"  ERROR: {e}")
        return None
    say(f"  File            : {path}")
    say(f"  Size            : {img.size} bytes")
    if not img.check("magic").ok:
        say("  FAIL: header is not 'JCID' -> not an update file.")
        return img
    say("  Magic           : JCID (update file)")
    s = img.check("size")
    if s is None:
        return img
    say(f"  Declared size   : {img.declared_size} bytes -> {'OK' if s.ok else 'MISMATCH'}")
    say(f"  CRC16           : file {img.crc_file:04X}, calc {img.crc_calc:04X} -> "
          f"{'OK' if img.check('crc').ok else 'MISMATCH'}")
    say(f"  Header name     : {img.header_name!r}")
    say(f"  Product         : {img.product_str}")
    say(f"  Version         : {img.version_str}")
    say(f"  Vector table    : {img.vector_text()}")
    return img


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only probe for AiXun T3x stations")
    ap.add_argument("--port", help="serial port (default: auto-detect by USB serial number)")
    ap.add_argument("--repeat", type=int, default=3, help="query repetitions (default 3)")
    ap.add_argument("--fw", help="optional update .bin to pre-check against the station")
    ap.add_argument("--hardware", action="store_true",
                    help="also send JC_hardware (believed to be a read-only query; opt-in)")
    ap.add_argument("--reader-test", type=int, default=0, metavar="N",
                    help="repeat each query N times using the ORIGINAL updater read method")
    ap.add_argument("--json", action="store_true", help="print a machine-readable JSON report only")
    ap.add_argument("--json-out", metavar="FILE",
                    help="also write the JSON report of this same run to FILE")
    ap.add_argument("--wait", type=float, default=0, metavar="S",
                    help="keep looking for the station for up to S seconds (default 0)")
    args = ap.parse_args(argv)

    global say
    out = print
    # human report off in JSON mode; reset every call so state never leaks between runs
    say = (lambda *a, **k: None) if args.json else print

    try:
        p = find_station(args.port, wait=args.wait)
    except ProbeError as e:
        out(f"ERROR: {e}")
        sys.exit(1)

    rep = ProbeReport(p, usb_details(p), hardware_allowed=args.hardware)
    section("USB / host side")
    for label, value in rep.usb:
        say(f"  {label:<16}: {value}")

    if args.fw:
        rep.image = print_fw(args.fw)

    section("Serial session (115200 8N1, same as updater)")
    try:
        session = ProbeSession(p.device, allow_hardware=args.hardware)
    except (PortUnavailable, serial.SerialException) as e:
        out(f"  ERROR opening port: {e}")
        out("  Hint: is your user in the 'dialout' group?  sudo usermod -aG dialout $USER")
        out("  If the station was plugged in a moment ago, wait a few seconds and try again.")
        sys.exit(1)

    try:
        _session(session, args, rep)
    except DeviceLost as e:
        out(f"  ERROR: {e}")
        out("  Check the cable and that the station is switched on, then run the probe again.")
        sys.exit(1)
    _report(args, rep, out)


def _session(session, args, rep):
    with session as s:
        time.sleep(0.2)
        rep.unsolicited = s.listen(1.0)
        say(f"  Unsolicited data in 1 s: {len(rep.unsolicited)} bytes")
        if rep.unsolicited:
            say(hexdump(rep.unsolicited))

        for i in range(args.repeat):
            for cmd in s.allowed:
                rx, lat = s.query(cmd)
                rep.replies.append(Reply(i + 1, cmd, rx, lat))
                lat_s = f"{lat:.1f} ms" if lat is not None else "TIMEOUT"
                say(f"\n  [{i + 1}/{args.repeat}] TX {cmd.decode():<12} -> {len(rx)} bytes, first byte after {lat_s}")
                say(f"      RX: {rx!r}")
                say(hexdump(rx))
            time.sleep(0.2)

        if args.reader_test:
            section(f"Reader test: original read(1)+read_all, {args.reader_test}x per query")
            rep.reader_test_n = args.reader_test
            ref = {c: rep.answers(c)[0] for c in READ_ONLY_COMMANDS}
            for i in range(args.reader_test):
                for cmd in READ_ONLY_COMMANDS:
                    rx = s.query_original_reader(cmd)
                    if rx != ref[cmd]:
                        rep.reader_mismatches.append((i + 1, cmd, rx))
                        say(f"  MISMATCH #{i + 1} {cmd.decode()}: {rx!r}")
                    time.sleep(0.05)
            say(f"  {rep.reader_total - len(rep.reader_mismatches)}/{rep.reader_total} "
                  "replies complete and identical")
        rep.sent = list(s.sent)


def _report(args, rep, out):
    section("Decoded")
    if args.hardware:
        hw = rep.hardware or b""
        say(f"  Hardware        : {hw!r}"
              + ("  (no reply - command probably not in this firmware)" if not hw else ""))
    v = rep.version
    say(f"  Identity        : {rep.identity!r} -> {rep.mode}")
    say(f"  Version string  : {v.raw!r}")
    say(f"  Fields ('_')    : {[x.decode(errors='replace') for x in v.raw.split(b'_')]}")
    say(f"  Product (field2): {v.product.decode(errors='replace') if v.product else 'n/a'}")
    say(f"  FW version      : {v.version.decode(errors='replace') if v.version else 'n/a'}")

    section("Verdict")
    checks = rep.checks()
    for c in checks:
        say(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}")
    img = rep.image
    if img is not None and img.version and v.version:
        same = img.version == v.version
        down = fwimage.version_key(img.version) < fwimage.version_key(v.version)
        say(f"\n  Station v{v.version.decode(errors='replace')} vs file v{img.version_str}"
              + ("  (same version - flashing would be a re-flash)" if same else "")
              + ("  (DOWNGRADE)" if down else ""))
        if down:
            say("  DOWNGRADE: older firmware may read the newer one's settings differently (unverified);")
            say("  if you flash it, check the station's settings and temperature afterwards.")
    if rep.ok:
        say("\n  All checks passed. Communication looks safe to proceed.")
    elif rep.identity == b"JC_boot" and all(c.ok for c in checks if "application mode" not in c.name):
        say("\n  Station is waiting in its BOOTLOADER: a previous update was probably interrupted.")
        say("  Do not power it off. Finish the update with t3x-update and a matching image.")
    else:
        say("\n  One or more checks FAILED - do not flash yet.")

    if args.json:
        out(json.dumps(rep.to_dict(), indent=2))
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(rep.to_dict(), f, indent=2)
    sys.exit(0 if rep.ok else 2)


if __name__ == "__main__":
    main()

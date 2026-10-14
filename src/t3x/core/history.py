# SPDX-License-Identifier: GPL-2.0-or-later
"""Flash history: one JSON line per update attempt in <results>/history.jsonl.

Written by both the GUI and t3x-update. Local file only; it contains the station's
USB serial number (like the flash logs), so don't publish it.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import time
from typing import Dict, List, Optional

from .image import FirmwareImage

FILE_NAME = "history.jsonl"


def _txt(b: Optional[bytes]) -> Optional[str]:
    return b.decode(errors="replace") if b is not None else None


def make_record(result, image: FirmwareImage, *, tool: str, log_path: Optional[str],
                simulated: bool, usb_serial: Optional[str] = None) -> Dict:
    pf = result.preflight
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(result.started_at or time.time())),
        "tool": tool,
        "simulated": simulated,
        "ok": bool(result.ok),
        "stage": getattr(result.stage, "name", str(result.stage)),
        "message": result.message,
        "port": pf.port if pf else None,
        "usb_serial": usb_serial,
        "before_identity": _txt(pf.identity) if pf else None,
        "before_version": _txt(pf.station.raw) if pf else None,
        "bootloader": _txt(result.bootloader.raw) if result.bootloader else None,
        "after_version": _txt(result.after.raw) if result.after else None,
        "file": os.path.basename(image.path or "?"),
        "product": image.product_str,
        "version": image.version_str,
        "size": image.size,
        "sha256": hashlib.sha256(image.data).hexdigest(),
        "chunks_acked": result.chunks_acked,
        "n_chunks": result.n_chunks,
        "wrote_anything": bool(result.wrote_anything),
        "duration_s": round(result.duration, 1) if result.finished_at else None,
        "transfer_s": round(result.transfer_seconds, 1) if result.transfer_seconds else None,
        "log": os.path.basename(log_path) if log_path else None,
    }


def append(results_dir: str, record: Dict) -> str:
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, FILE_NAME)
    with open(path, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def load(results_dir: str) -> List[Dict]:
    """All records, oldest first. Unreadable lines are skipped, never fatal."""
    path = os.path.join(results_dir, FILE_NAME)
    out: List[Dict] = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        out.append(rec)
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def summary(rec: Dict) -> str:
    """One line, e.g. '2026-10-11 23:51:02  T3BS 1.15 → 1.16  OK  82/82  16.7 s'."""
    before = rec.get("before_version") or "?"
    frm = before.rsplit("version", 1)[-1] if "version" in before else before
    res = "OK" if rec.get("ok") else ("FAILED" if rec.get("wrote_anything") else "not written")
    t = f"  {rec['transfer_s']} s" if rec.get("transfer_s") else ""
    return (f"{rec.get('time', '?')}  {rec.get('product', '?')} {frm} → {rec.get('version', '?')}  {res}  "
            f"{rec.get('chunks_acked', 0)}/{rec.get('n_chunks', 0)}{t}")


# ---------------------------------------------------------------- import from logs
_TS = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d{3}) ")
_RE = {
    "file": re.compile(r"Update file: (\S+) v(\S+) \((\d+) bytes"),
    "before": re.compile(r"Station: identity b'([^']*)', version string b'([^']*)'"),
    "boot": re.compile(r"Bootloader version string: b'([^']*)'"),
    "after": re.compile(r"After flash: identity b'([^']*)', version b'([^']*)'"),
    "port": re.compile(r"\[initial\] (\S+) .*?SER=(\S+)"),
}


def _secs(line: str) -> Optional[float]:
    m = _TS.match(line)
    if not m:
        return None
    h, mi, se, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + se + ms / 1000


def record_from_log(path: str) -> Optional[Dict]:
    """Rebuild a history record from a flash log (logs from t3x-update, the GUI, or the
    original t3xupdate_safe.py). Fields a log doesn't contain (file name, SHA-256) are None."""
    from .logfile import is_simulated_log, parse_log
    if is_simulated_log(path):
        return None
    with open(path, errors="replace") as f:
        lines = f.read().splitlines()
    found: Dict[str, re.Match] = {}
    for ln in lines:
        for k, rx in _RE.items():
            if k not in found:
                m = rx.search(ln)
                if m:
                    found[k] = m
    if "file" not in found:
        return None                                   # not a flash log, or stopped before reading the file
    s = parse_log(path)
    ok = s.outcome == "success"
    stamps = [t for t in (_secs(ln) for ln in lines) if t is not None]
    t_send = next((_secs(ln) for ln in lines if "Sending firmware..." in ln), None)
    t_end = next((_secs(ln) for ln in lines if "Device dropped after last chunk" in ln
                  or "No ACK on last chunk" in ln), None)
    if t_send is not None and t_end is None:
        acks = [_secs(ln) for ln in lines if "b'ack_jcxx'" in ln]
        t_end = acks[-1] if acks else None
    span = lambda a, b: round((b - a) % 86400, 1) if a is not None and b is not None else None  # noqa: E731
    m = re.search(r"t3x_flash_(\d{8})_(\d{6})", os.path.basename(path))
    when = (f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} "
            f"{m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}") if m else None
    f = found["file"]
    n = (int(f.group(3)) + 2047) // 2048
    return {
        "time": when, "tool": "imported from log", "simulated": False, "ok": ok,
        "stage": "DONE" if ok else s.outcome.upper(), "message": s.describe(),
        "port": found["port"].group(1) if "port" in found else None,
        "usb_serial": found["port"].group(2) if "port" in found else None,
        "before_identity": found["before"].group(1) if "before" in found else None,
        "before_version": found["before"].group(2) if "before" in found else None,
        "bootloader": found["boot"].group(1) if "boot" in found else None,
        "after_version": found["after"].group(2) if "after" in found else None,
        "file": None, "product": f.group(1), "version": f.group(2), "size": int(f.group(3)), "sha256": None,
        "chunks_acked": n if ok else s.chunks_acked, "n_chunks": n,
        "wrote_anything": any("update_jcxx" in ln for ln in lines),
        "duration_s": span(stamps[0], stamps[-1]) if stamps else None,
        "transfer_s": span(t_send, t_end),
        "log": os.path.basename(path),
    }


def import_logs(results_dir: str, log_dir: Optional[str] = None) -> Dict[str, List[str]]:
    """Add records for flash logs in log_dir (default: results_dir) that history doesn't know yet.
    Simulator logs and logs already recorded are skipped. Returns {added, skipped}."""
    log_dir = log_dir or results_dir
    known = {r.get("log") for r in load(results_dir)}
    out: Dict[str, List[str]] = {"added": [], "skipped": []}
    new = []
    for path in sorted(glob.glob(os.path.join(log_dir, "t3x_flash_*.log"))):
        name = os.path.basename(path)
        if name in known:
            out["skipped"].append(f"{name}: already in history")
            continue
        rec = record_from_log(path)
        if rec is None:
            out["skipped"].append(f"{name}: simulator log or not a flash log")
            continue
        new.append(rec)
        out["added"].append(f"{name}: {summary(rec)}")
    if new:
        merged = sorted(load(results_dir) + new, key=lambda r: r.get("time") or "")
        os.makedirs(results_dir, exist_ok=True)
        path = os.path.join(results_dir, FILE_NAME)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            for r in merged:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        os.replace(tmp, path)
    return out

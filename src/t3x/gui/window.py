# SPDX-License-Identifier: GPL-2.0-or-later
"""Main window: Connect → Verify → Flash → Done, plus Recovery.

Safety rules carried into the GUI (see docs/DEVELOPMENT_REPORT.md §3):
* All serial I/O runs in worker threads (workers.py); the window never blocks.
* "Flash firmware" is enabled only when every check passes AND the user ticks
  the confirmation box (Verify) or confirms a dialog (Recovery).
* Just before writing, the flash job re-checks that the station still matches
  what was verified (same identity + version string); otherwise nothing is sent.
* While a transfer runs, the window cannot be closed and no other action starts.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Qt
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHeaderView, QScrollArea, QGroupBox, QHBoxLayout, QLabel,
                               QMainWindow, QMessageBox, QProgressBar, QPushButton, QStackedWidget, QStatusBar,
                               QToolBar, QVBoxLayout, QWidget)

from ..core import changelog, environment, history, online
from ..core import events as ev
from ..core import image as fw
from ..core.flasher import FlashResult
from ..core.link import PortInfo, system_port_lister
from ..core.logfile import latest_log, parse_log
from ..core.probe import NoReply, PortUnavailable, ProbeCancelled, ProbeReport
from ..core.protocol import ID_APP, ID_BOOT
from . import theme as T
from .widgets import (Banner, ChunkMap, KeyValueBox, LogView, StepList, fill_table, h1, make_table, muted)
from .config import GuiConfig
from .workers import Expected, FlashJob, FuncJob, ProbeJob, start

STEP_CONNECT, STEP_VERIFY, STEP_FLASH, STEP_CONFIRM, STEP_ALL = range(5)


def _ok_color(s: str) -> Optional[str]:
    if s.startswith("⚠"):
        return T.WARN
    return T.OK if s.startswith(("PASS", "✔", "OK")) else (T.ERR if s.startswith(("FAIL", "✖")) else None)


@dataclass
class Settings:
    firmware_dir: str
    results_dir: str
    port_lister: Callable[[], List[PortInfo]] = system_port_lister
    link_factory: Optional[Callable] = None     # tests: simulator-backed SerialLink
    poll_ms: int = 1000
    auto_probe: bool = True
    reader_test: int = 10
    wait: float = 20
    config: Optional["GuiConfig"] = None   # preferences file in the workspace (None: remember nothing)
    simulated: bool = False        # --sim: logs and history go to results/sim, never mixed with real ones
    settle_s: float = 1.5          # a newly plugged station must be on USB this long before the auto-probe
    wake_window_s: float = 30.0    # keep retrying a silent / busy port this long after it appeared
    retry_gap_ms: int = 1500


# =============================================================== pages
class ConnectPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setSpacing(12)
        self.title = h1("Connect a station")
        v.addWidget(self.title)

        row = QHBoxLayout()
        self.badge = QLabel("—")
        self.badge.setObjectName("badge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setMinimumWidth(130)
        row.addWidget(self.badge)
        info = QVBoxLayout()
        self.line1 = muted("Plug the station into this computer with a USB data cable (no hub) and switch it on.")
        self.line2 = QLabel("")
        self.line3 = muted("")
        for w in (self.line1, self.line2, self.line3):
            info.addWidget(w)
        row.addLayout(info, 1)
        v.addLayout(row)

        self.note = Banner("", "info")
        self.error = Banner("", "errbox")
        v.addWidget(self.note)
        self.update_note = Banner("", "info")      # optional "newer version listed online" notice
        v.addWidget(self.update_note)
        v.addWidget(self.error)

        g = QGroupBox("Serial ports")
        gl = QVBoxLayout(g)
        self.ports = make_table(["Port", "USB ID", "Serial / description", "Status"])
        self.ports.setMinimumHeight(110)
        gl.addWidget(self.ports)
        v.addWidget(g)

        g2 = QGroupBox("Link test (read-only: only JC_identity and JC_version are sent)")
        self.link = QGridLayout(g2)
        self.link_vals = {}
        for i, k in enumerate(["JC_identity", "JC_version", "Reply latency", "Reader test"]):
            a = muted(k)
            b = QLabel("—")
            self.link_vals[k] = b
            self.link.addWidget(a, i // 2, (i % 2) * 2)
            self.link.addWidget(b, i // 2, (i % 2) * 2 + 1)
        v.addWidget(g2)
        v.addStretch()

        bt = QHBoxLayout()
        self.probe_btn = QPushButton("Probe again")
        self.probe_btn.clicked.connect(lambda: win.start_probe(manual=True))
        bt.addWidget(self.probe_btn)
        bt.addStretch()
        self.next_btn = QPushButton("Continue to Verify  →")
        self.next_btn.setObjectName("primary")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(win.go_verify)
        bt.addWidget(self.next_btn)
        v.addLayout(bt)

    def show_ports(self, ports: List[PortInfo]):
        rows = []
        for p in ports:
            vp = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "—"
            status = ("AiXun T3x" if p.is_t3x else ("FTDI ID, unknown serial" if p.is_ftdi_id else "ignored"))
            rows.append([p.device, vp, p.serial_number or p.description or p.product or "—", status])
        fill_table(self.ports, rows, {3: lambda s: T.OK if s.startswith("AiXun") else T.DIM})

    def show_waiting(self, text: str = ""):
        self.title.setText("Connect a station")
        self.badge.setText("—")
        self.line1.setText("Plug the station into this computer with a USB data cable (no hub) and switch it on.")
        self.line2.setText(text)
        self.line3.setText("")
        self.note.set("")
        self.update_note.set("")
        self.next_btn.setEnabled(False)
        for b in self.link_vals.values():
            b.setText("—")
            b.setObjectName("")
            b.setStyleSheet("")

    def show_report(self, rep: ProbeReport):
        v = rep.version
        self.error.set("")
        self.title.setText("Station detected")
        self.badge.setText(v.product_str if v.product else "?")
        mode = {ID_APP: "application", ID_BOOT: "BOOTLOADER"}.get(rep.identity, "unknown")
        self.line1.setText("Firmware line reported by the station itself (JC_version)")
        if rep.identity == ID_BOOT:
            self.line2.setText(f"Bootloader running · {rep.identity.decode(errors='replace')} · "
                               "a previous update was probably interrupted")
        else:
            self.line2.setText(f"{mode.capitalize()} running · firmware {v.version_str} · "
                               f"{rep.identity.decode(errors='replace')}")
        usb = dict(rep.usb)
        parts = [f"USB {usb.get('VID:PID', '?')}", f"serial {rep.port.serial_number}"]
        if usb.get("Kernel driver"):
            parts.append(f"driver {usb['Kernel driver']}")
        self.line3.setText(" · ".join(parts))
        usb_prod = (rep.port.product or "").replace("JCID_", "")
        if v.product and usb_prod and usb_prod != v.product_str:
            self.note.set(f"ℹ  The sticker, screen and USB name may say \"{usb_prod}\". The firmware line is "
                          f"taken from the station itself, so only {v.product_str} images will be offered.")
        else:
            self.note.set("")
        ids = rep.answers(b"JC_identity")
        vers = rep.answers(b"JC_version")
        lat = rep.latencies
        vals = {
            "JC_identity": (f"{rep.identity.decode(errors='replace')} · {ids.count(ids[0]) if ids else 0}/"
                            f"{len(ids)} consistent", bool(ids) and len(set(ids)) == 1),
            "JC_version": (f"{v.raw.decode(errors='replace')} · {len(vers)}/{len(vers)}",
                           bool(vers) and len(set(vers)) == 1),
            "Reply latency": (f"{min(lat):.1f} – {max(lat):.1f} ms" if lat else "no replies", bool(lat)),
            "Reader test": ((f"{rep.reader_total - len(rep.reader_mismatches)}/{rep.reader_total} complete")
                            if rep.reader_test_n else "not run", not rep.reader_mismatches),
        }
        for k, (text, ok) in vals.items():
            b = self.link_vals[k]
            b.setText(("✔  " if ok else "✖  ") + text)
            b.setStyleSheet(f"color: {T.OK if ok else T.ERR}")
        replies_ok = all(c.ok for c in rep.checks()[:4]) and not rep.reader_mismatches
        if rep.identity == ID_BOOT:
            self.next_btn.setText("Go to recovery  →")
        else:
            self.next_btn.setText("Continue to Verify  →")
        self.next_btn.setEnabled(replies_ok and rep.identity in (ID_APP, ID_BOOT))

    def show_error(self, text: str):
        self.error.set("✖  " + text)


class VerifyPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.images: List[fw.FirmwareImage] = []
        v = QVBoxLayout(self)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(h1("Pre-flight check"))
        top.addStretch()
        self.chip_from = QLabel("—")
        self.chip_from.setObjectName("chip")
        self.chip_to = QLabel("—")
        self.chip_to.setObjectName("chipNew")
        top.addWidget(self.chip_from)
        top.addWidget(QLabel(" → "))
        top.addWidget(self.chip_to)
        v.addLayout(top)

        lib = QGroupBox("Firmware library")
        ll = QVBoxLayout(lib)
        hr = QHBoxLayout()
        self.folder_lbl = muted("")
        hr.addWidget(self.folder_lbl, 1)
        b1 = QPushButton("Folder…")
        b1.clicked.connect(self.choose_folder)
        b2 = QPushButton("Add file…")
        b2.clicked.connect(self.choose_file)
        b3 = QPushButton("Check online…")
        b3.setToolTip("List the versions published on aixun-updates.github.io, compare your files with them, "
                      "download one into the firmware folder. Never flashes.")
        b3.clicked.connect(self.check_online)
        hr.addWidget(b1)
        hr.addWidget(b2)
        hr.addWidget(b3)
        ll.addLayout(hr)
        self.lib = make_table(["File", "Product", "Version", "Status"])
        self.lib.setFixedHeight(104)              # header + 2–3 rows; scrolls if the folder holds more
        self.lib.itemSelectionChanged.connect(self.on_select)
        ll.addWidget(self.lib)
        v.addWidget(lib)

        self.checking = muted("")                    # which file the checks below are for
        self.checking.setWordWrap(False)             # one line: the checks table must stay fully visible
        self.checking.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.checking)
        self.checks = make_table(["Check", "Detail", "Result"])
        self.checks.verticalHeader().setDefaultSectionSize(26)
        self.checks.setMinimumHeight(10 * 26 + 34)   # all checks visible without scrolling
        hh = self.checks.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.changes = QGroupBox("What changes")
        cl = QVBoxLayout(self.changes)
        self.changes_lbl = QLabel("")
        self.changes_lbl.setWordWrap(True)
        self.changes_lbl.setAlignment(Qt.AlignTop)
        sa = QScrollArea()
        sa.setWidget(self.changes_lbl)
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        cl.addWidget(sa)
        mid = QHBoxLayout()                           # checks | changelog side by side
        mid.addWidget(self.checks, 3)
        mid.addWidget(self.changes, 2)
        v.addLayout(mid, 1)

        self.banner = Banner("", "warn")
        v.addWidget(self.banner)
        bt = QHBoxLayout()
        self.confirm = QCheckBox("I understand: I won't unplug the cable or power off the station during the update")
        self.confirm.toggled.connect(self.update_gate)
        bt.addWidget(self.confirm)
        bt.addStretch()
        back = QPushButton("← Back")
        back.clicked.connect(win.go_connect)
        bt.addWidget(back)
        self.flash_btn = QPushButton("Flash firmware")
        self.flash_btn.setObjectName("primary")
        self.flash_btn.setEnabled(False)
        self.flash_btn.clicked.connect(win.start_flash)
        bt.addWidget(self.flash_btn)
        v.addLayout(bt)
        self.all_ok = False
        self._last_selected: Optional[str] = None

    # ---------------------------------------------------------- library
    def load_library(self, select_best: bool = True):
        d = self.win.s.firmware_dir
        self.folder_lbl.setText(f"Folder: {d}")
        self.images = fw.scan_directory(d) if os.path.isdir(d) else []
        extra = getattr(self.win, "extra_images", [])
        self.images += [i for i in extra if i.path not in {x.path for x in self.images}]
        st = self.win.report.version if self.win.report else None
        rows = []
        for img in self.images:
            if not img.valid:
                status = "✖ invalid: " + ", ".join(c.name for c in img.checks if not c.ok)
            elif st and st.product and img.product != st.product:
                status = f"✖ product mismatch (station is {st.product_str})"
            elif st and st.version == img.version:
                status = "✔ same version (re-flash)"
            elif st and st.version and fw.version_key(img.version) < fw.version_key(st.version):
                status = "⚠ downgrade"
            else:
                status = "✔ compatible"
            rows.append([os.path.basename(img.path or "?"), img.product_str, img.version_str, status])
        fill_table(self.lib, rows, {3: _ok_color})
        if not self.images:
            self.banner.set(f"No firmware images in {d}. Download the .bin for your station's product line "
                            "(see docs/WORKFLOW.md §2) and put it in that folder, or use “Add file…”.", "warn")
        if select_best and self.images:
            best = self._best_index()
            if best is not None:
                self.lib.selectRow(best)
        self.on_select()

    def _best_index(self) -> Optional[int]:
        st = self.win.report.version if self.win.report else None
        cands = [(i, img) for i, img in enumerate(self.images)
                 if img.valid and (not st or img.product == st.product)]
        if not cands:
            return None
        return max(cands, key=lambda c: fw.version_key(c[1].version))[0]

    def selected(self) -> Optional[fw.FirmwareImage]:
        rows = self.lib.selectionModel().selectedRows() if self.lib.selectionModel() else []
        return self.images[rows[0].row()] if rows else None

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Firmware folder", self.win.s.firmware_dir,
                                             QFileDialog.ShowDirsOnly | QFileDialog.DontUseNativeDialog)
        if d:
            self.win.s.firmware_dir = d
            self.win.cfg.firmware_dir = d            # remembered in the workspace's config/gui.json
            self.win.cfg.save()
            self.load_library()

    def choose_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Firmware image", self.win.s.firmware_dir, "AiXun update (*.bin)",
                                           options=QFileDialog.DontUseNativeDialog)
        if f:
            try:
                self.win.extra_images.append(fw.load(f))
            except fw.ImageError as e:
                QMessageBox.warning(self, "Firmware image", str(e))
            self.load_library(select_best=False)
            for i, img in enumerate(self.images):
                if img.path == f:
                    self.lib.selectRow(i)

    def check_online(self):
        rep = self.win.report
        product = rep.version.product_str if rep and rep.version.product else None
        self.online_dialog = OnlineDialog(self.win, product)
        self.online_dialog.show()

    def reload_keep_selection(self):
        cur = self.selected()
        self.load_library(select_best=cur is None)
        if cur is not None:
            for i, img in enumerate(self.images):
                if img.path == cur.path:
                    self.lib.selectRow(i)

    # ---------------------------------------------------------- checks
    def on_select(self):
        img = self.selected()
        key = (img.path, hashlib.sha256(img.data).hexdigest()) if img else None
        if key != self._last_selected:
            # a different file needs a fresh confirmation: never carry a tick over
            self.confirm.setChecked(False)
            self._last_selected = key
        if img:
            self.checking.setText(f"Checks for: {os.path.basename(img.path or '?')}  ·  {img.size:,} B  ·  "
                                  f"SHA-256 {key[1]}")
            self.checking.setToolTip(f"{img.path}\nSHA-256 {key[1]}")
        else:
            self.checking.setText("No image selected")
        self.win.image = img
        self.win.toolbar_fw.setText(img.path if img else "No image selected")
        rep = self.win.report
        rows = []
        if rep:
            for c in rep.checks():
                if "Update" in c.name:
                    continue
                rows.append([c.name, c.detail, "PASS" if c.ok else "FAIL"])
        if img:
            for c in img.checks:
                label = {"magic": "Image header (JCID)", "size": "Image size", "crc": "CRC16",
                         "vectors": "Vector table"}.get(c.name, c.name)
                rows.append([label, c.detail, "PASS" if c.ok else "FAIL"])
            st = rep.version if rep else None
            match = bool(st and st.product and img.product == st.product)
            rows.append(["Product match", f"file {img.product_str} / station {st.product_str if st else '?'}",
                         "PASS" if match else "FAIL"])
        else:
            rows.append(["Firmware image", "select an image in the library", "FAIL"])
        fill_table(self.checks, rows, {2: _ok_color})
        for r in range(self.checks.rowCount()):
            self.checks.setRowHeight(r, 26)
        self.all_ok = bool(rows) and all(r[2] == "PASS" for r in rows)

        st = rep.version if rep else None
        self.chip_from.setText(f"{st.product_str} {st.version_str}" if st else "—")
        self.chip_to.setText(f"{img.product_str} {img.version_str}" if img else "—")
        if img and st and st.version and img.version:
            entries = changelog.between(img.product_str, st.version_str, img.version_str)
            if entries:
                self.changes.setTitle(f"What changes since {st.version_str}")
                self.changes_lbl.setText("\n".join(f"•  {v}  {txt}" for v, _d, txt in entries)
                                         + f"\n\nSource: {changelog.SOURCE}")
            elif img.version == st.version:
                self.changes.setTitle("What changes")
                self.changes_lbl.setText("Nothing: the station already runs this version (re-flash).")
            else:
                self.changes.setTitle("What changes")
                self.changes_lbl.setText("No changelog entries known for this step "
                                         "(older version, or a product without a stored changelog).")
        self._update_banner(img, st)
        self.update_gate()

    def _update_banner(self, img, st):
        if not img:
            return
        msgs = []
        # measured on a T3BS (2026-10-11): ~0.2 s per chunk + ~8 s for the two USB restarts
        self.confirm.setText("I understand: I won't unplug the cable or power off the station during the update "
                             f"(about {img.n_chunks * 0.2 + 8:.0f} s)")
        if st and st.version and img.version and fw.version_key(img.version) < fw.version_key(st.version):
            msgs.append(f"DOWNGRADE {st.version_str} → {img.version_str}: older firmware may read the newer "
                        "one's settings differently (unverified); check settings and temperature afterwards.")
        if st and st.version and img.version != st.version:
            roll = [i for i in self.images if i.valid and i.product == st.product and i.version == st.version]
            msgs.append(f"Rollback image: {os.path.basename(roll[0].path)}" if roll else
                        f"No rollback image for v{st.version_str} in the firmware folder: the station's current "
                        "firmware cannot be read back, so consider downloading it first.")
        if self.win.mm_active:
            msgs.append("ModemManager is running: it may open the station's port during the update's two USB "
                        "restarts. Optional: sudo systemctl stop ModemManager (back at reboot).")
        self.banner.set("⚠  " + "  ".join(msgs) if msgs else "", "warn")

    def update_gate(self):
        busy = self.win.busy or self.win.probing
        self.flash_btn.setEnabled(self.all_ok and self.confirm.isChecked() and not busy)
        self.flash_btn.setToolTip("" if self.flash_btn.isEnabled() else
                                  "Needs: every check PASS, an image selected, and the confirmation box ticked")


class FlashPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        v = QVBoxLayout(self)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.big = QLabel("0%")
        self.big.setObjectName("big")
        top.addWidget(self.big)
        self.sub = muted("")
        self.sub.setWordWrap(False)
        top.addWidget(self.sub, 0, Qt.AlignBottom)
        top.addStretch()
        self.chip_from = QLabel("")
        self.chip_from.setObjectName("chip")
        self.chip_to = QLabel("")
        self.chip_to.setObjectName("chipNew")
        top.addWidget(self.chip_from)
        top.addWidget(QLabel(" → "))
        top.addWidget(self.chip_to)
        v.addLayout(top)
        self.stage = muted("")
        v.addWidget(self.stage)
        self.rate = muted("")
        self.rate.setWordWrap(False)
        v.addWidget(self.rate)
        self.bar = QProgressBar()
        v.addWidget(self.bar)
        g = QGroupBox("Chunk map  (2048 B each)")
        gl = QVBoxLayout(g)
        self.map = ChunkMap()
        gl.addWidget(self.map)
        v.addWidget(g)
        v.addWidget(Banner("⚠  Do not unplug USB or power off the station. If anything fails, the station stays in "
                           "its bootloader and the update can be resumed safely.", "warn"))
        self.log = LogView()
        v.addWidget(self.log, 1)
        bt = QHBoxLayout()
        bt.addStretch()
        self.abort = QPushButton("Abort")
        self.abort.setEnabled(False)
        self.abort.setToolTip("Disabled on purpose: stopping mid-transfer would leave the station in its bootloader")
        bt.addWidget(self.abort)
        v.addLayout(bt)
        self.t0 = 0.0
        self.t_first: Optional[float] = None
        self.per_chunk = 0.2

    def reset(self, img: fw.FirmwareImage, from_txt: str, per_chunk: float = 0.2, basis: str = ""):
        """per_chunk: expected seconds per chunk (from this station's earlier flashes when known)."""
        self.map.reset(img.n_chunks)
        self.bar.setRange(0, img.n_chunks)
        self.bar.setValue(0)
        self.bar.setFormat("%v / %m chunks")
        self.big.setText("0%")
        self.sub.setText(f"  0 of {img.n_chunks} chunks · 0 / {img.size:,} bytes")
        self.chip_from.setText(from_txt)
        self.chip_to.setText(f"{img.product_str} {img.version_str}")
        self.log.clear_all()
        self.stage.setText("Starting…")
        self.t0 = time.monotonic()
        self.t_first = None
        self.per_chunk = per_chunk
        self.rate.setText(f"Expected transfer: about {img.n_chunks * per_chunk:.0f} s ({basis or 'typical value'}), "
                          "plus a few seconds for the two USB restarts")

    def progress(self, e: ev.ProgressEvent):
        self.map.set_progress(e.index, sending=e.index < e.total)
        self.bar.setValue(e.index)
        self.big.setText(f"{e.percent}%")
        self.sub.setText(f"  {e.index} of {e.total} chunks · {e.bytes_done:,} / {e.bytes_total:,} bytes")
        now = time.monotonic()
        if self.t_first is None:          # the first ACK marks the start of the transfer proper
            self.t_first, self.first_index, self.first_bytes = now, e.index, e.bytes_done
            return
        dt = now - self.t_first
        if dt <= 0 or e.index <= self.first_index:
            return
        per = dt / (e.index - self.first_index)
        speed = (e.bytes_done - self.first_bytes) / dt / 1024
        if e.index < e.total:
            left = per * (e.total - e.index)
            self.rate.setText(f"Speed {speed:.1f} KB/s · {per * 1000:.0f} ms per chunk · about {left:.0f} s left, "
                              f"then the station restarts and the new version is read back")
        else:
            self.rate.setText(f"Transfer finished at {speed:.1f} KB/s ({per * 1000:.0f} ms per chunk)")


class DonePage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setSpacing(12)
        self.head = QHBoxLayout()
        self.icon = QLabel("✔")
        self.icon.setObjectName("bigok")
        self.head.addWidget(self.icon)
        hv = QVBoxLayout()
        self.title = h1("Update successful")
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        hv.addWidget(self.title)
        hv.addWidget(self.detail)
        self.head.addLayout(hv, 1)
        v.addLayout(self.head)
        g = QGroupBox("Transfer summary")
        self.grid = QGridLayout(g)
        self.vals = {}
        for i, k in enumerate(["Chunks", "Bytes", "Duration", "Station now", "Bootloader", "Log"]):
            a = muted(k)
            b = QLabel("—")
            b.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.vals[k] = b
            self.grid.addWidget(a, i // 3, (i % 3) * 2)
            self.grid.addWidget(b, i // 3, (i % 3) * 2 + 1)
        v.addWidget(g)
        cm = QGroupBox("Chunk map")
        cl = QVBoxLayout(cm)
        self.map = ChunkMap()
        cl.addWidget(self.map)
        v.addWidget(cm)
        self.next_box = QGroupBox("Post-flash checklist")
        self.next_lay = QVBoxLayout(self.next_box)
        v.addWidget(self.next_box)
        v.addStretch()
        bt = QHBoxLayout()
        self.retry = QPushButton("Resume / retry")
        self.retry.clicked.connect(lambda: win.start_probe(manual=True))
        bt.addWidget(self.retry)
        bt.addStretch()
        b1 = QPushButton("Open results folder")
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(win.s.results_dir)))
        b2 = QPushButton("Export report…")
        b2.clicked.connect(win.export_report)
        self.done_btn = QPushButton("Done")
        self.done_btn.setObjectName("primary")
        self.done_btn.clicked.connect(lambda: win.start_probe(manual=True))
        for b in (b1, b2, self.done_btn):
            bt.addWidget(b)
        v.addLayout(bt)

    def _set_list(self, title: str, items, checkable: bool):
        self.next_box.setTitle(title)
        while self.next_lay.count():
            w = self.next_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for t in items:
            self.next_lay.addWidget(QCheckBox(t) if checkable else QLabel("•  " + t))

    def show_result(self, r, img: fw.FirmwareImage, log_path: str, chunk_states: List[int]):
        ok = isinstance(r, FlashResult) and r.ok
        self.icon.setText("✔" if ok else "✖")
        self.icon.setObjectName("bigok" if ok else "bigerr")
        self.icon.style().unpolish(self.icon)
        self.icon.style().polish(self.icon)
        self.map.state = list(chunk_states)
        self.map._update_height()
        self.map.update()
        self.vals["Log"].setText(os.path.basename(log_path))
        self.vals["Log"].setToolTip(log_path)
        if isinstance(r, FlashResult):
            self.vals["Chunks"].setText(f"{r.chunks_acked} / {r.n_chunks}" + (" acknowledged" if ok else ""))
            sent = img.size if ok else min(img.size, r.chunks_acked * 2048)
            self.vals["Bytes"].setText(f"{sent:,} / {img.size:,}")
            self.vals["Duration"].setText(f"{r.duration:.1f} s (transfer {r.transfer_seconds:.1f} s)")
            self.vals["Station now"].setText(r.after.raw.decode(errors="replace") if r.after else "—")
            self.vals["Bootloader"].setText(r.bootloader.raw.decode(errors="replace") if r.bootloader else "—")
        if ok:
            self.title.setText("Update successful")
            self.detail.setText(f"Station read back: JC_User · {r.after.raw.decode(errors='replace')}")
            self.detail.setStyleSheet(f"color: {T.OK}")
            self._set_list("Post-flash checklist", [
                "Stand: lifting the handle wakes the station, docking it sleeps",
                "Tip detected and reaching the setpoint",
                "Settings and presets survived the update",
                "Overshoot checked on the curve screen"], True)
            self.retry.hide()
            return
        msg = (r.message if isinstance(r, FlashResult) else f"Unexpected error: {r!r}").replace(
            "re-run this script", "click “Resume / retry”")
        wrote = isinstance(r, FlashResult) and r.wrote_anything
        aborted = isinstance(r, FlashResult) and r.stage == ev.Stage.ABORTED
        self.title.setText("Update not completed" if not aborted else "Update cancelled")
        self.detail.setText(msg)
        self.detail.setStyleSheet(f"color: {T.ERR if not aborted else T.WARN}")
        if wrote:
            self._set_list("What to do now", [
                "Do NOT power off the station and do NOT unplug it.",
                "It is waiting in its bootloader; the firmware can be written again safely.",
                "Click “Resume / retry”: the station will be detected in recovery mode.",
                f"If it keeps failing, keep the log ({os.path.basename(log_path)}) and report it."], False)
        else:
            self._set_list("What to do now", [
                "Nothing was written: the station still runs its previous firmware.",
                "Check the cable (direct, no hub) and that the station is on, then retry."], False)
        self.retry.show()


class RecoveryPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.images: List[fw.FirmwareImage] = []
        v = QVBoxLayout(self)
        v.setSpacing(12)
        v.addWidget(h1("Station is in bootloader mode"))
        v.addWidget(Banner("⚠  The station answered JC_boot instead of JC_User: a previous update was probably "
                           "interrupted. This is recoverable: the bootloader is intact and waiting for an image. "
                           "Do not power it off.", "warn"))
        self.box = KeyValueBox("Bootloader", ["Identity", "Version string", "Product line", "Port"])
        v.addWidget(self.box)
        self.last = Banner("", "info")
        v.addWidget(self.last)
        g = QGroupBox("Image to write (matching product line only)")
        gl = QVBoxLayout(g)
        self.table = make_table(["File", "Product", "Version", "Checks"])
        self.table.itemSelectionChanged.connect(self.update_gate)
        gl.addWidget(self.table)
        v.addWidget(g, 1)
        bt = QHBoxLayout()
        back = QPushButton("Probe again")
        back.clicked.connect(lambda: win.start_probe(manual=True))
        bt.addWidget(back)
        bt.addStretch()
        self.go = QPushButton("Resume flash")
        self.go.setObjectName("primary")
        self.go.setEnabled(False)
        self.go.clicked.connect(self.resume)
        bt.addWidget(self.go)
        v.addLayout(bt)

    def populate(self, rep: ProbeReport):
        v = rep.version
        self.box.set(Identity=rep.identity.decode(errors="replace"), **{
            "Version string": v.raw.decode(errors="replace"),
            "Product line": v.product_str if v.product else "unknown",
            "Port": rep.port.device})
        last = latest_log(self.win.s.results_dir, include_simulated=self.win.s.simulated)
        if last:
            s = parse_log(last)
            self.last.set(f"ℹ  Last flash log {os.path.basename(last)}: {s.describe()}", "info")
        else:
            self.last.set("")
        d = self.win.s.firmware_dir
        self.images = [i for i in (fw.scan_directory(d) if os.path.isdir(d) else []) + self.win.extra_images]
        rows = []
        for img in self.images:
            if not img.valid:
                chk = "✖ invalid"
            elif v.product and img.product != v.product:
                chk = "✖ product mismatch"
            else:
                chk = "✔ header · CRC · vectors"
            rows.append([os.path.basename(img.path or "?"), img.product_str, img.version_str, chk])
        fill_table(self.table, rows, {3: _ok_color})
        best = [i for i, img in enumerate(self.images) if img.valid and img.product == v.product]
        if best:
            self.table.selectRow(max(best, key=lambda i: fw.version_key(self.images[i].version)))
        self.update_gate()

    def selected(self) -> Optional[fw.FirmwareImage]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.images[rows[0].row()] if rows else None

    def update_gate(self):
        img = self.selected()
        v = self.win.report.version if self.win.report else None
        ok = bool(img and img.valid and v and v.product and img.product == v.product) and not (self.win.busy or self.win.probing)
        self.go.setEnabled(ok)
        self.go.setText(f"Resume flash with {img.product_str} {img.version_str}" if img else "Resume flash")

    def resume(self):
        img = self.selected()
        if not img:
            return
        if self.win.confirm_dialog(
                "Resume the interrupted update?",
                f"The station is waiting in its bootloader.\n\nWrite {os.path.basename(img.path)} "
                f"({img.product_str} {img.version_str}, {img.n_chunks} chunks)?\n\n"
                "Keep USB connected and the station powered until it finishes."):
            self.win.image = img
            self.win.start_flash()


class OnlineDialog(QDialog):
    """Versions listed by aixun-updates.github.io for the station's product; compare and download."""

    COLS = ["Version", "Date", "Notes", "In your firmware folder"]

    def __init__(self, win: "MainWindow", product: Optional[str]):
        super().__init__(win)
        self.win, self.product = win, product
        self.catalog: Optional[online.Catalog] = None
        self.entries: List[online.Entry] = []
        self.local: Dict[str, str] = {}
        self.setWindowTitle(f"Firmware online · {product or 'all products'}")
        self.resize(980, 520)
        v = QVBoxLayout(self)
        self.source = muted(f"Reading {online.site_url()} …")
        self.source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.source)
        self.table = make_table(self.COLS)
        hh = self.table.horizontalHeader()
        for c in (0, 1, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.table, 1)
        self.xcheck = QCheckBox("Also compare each download with the second address the site records for "
                                "the file")
        self.xcheck.setChecked(win.cfg.cross_check)
        self.xcheck.toggled.connect(self._pref_changed)
        v.addWidget(self.xcheck)
        self.notice = QCheckBox("After each probe, check this site for a newer version of the station's "
                                "firmware and say so on the Connect page (uses the internet; off by default)")
        self.notice.setChecked(win.cfg.update_notice)
        self.notice.toggled.connect(self._pref_changed)
        v.addWidget(self.notice)
        self.status = Banner("", "info")
        v.addWidget(self.status)
        bt = QHBoxLayout()
        bt.addWidget(muted("Downloads go to the firmware folder with a .source.json record. Nothing is "
                           "overwritten and nothing is flashed."))
        bt.addStretch()
        self.get_btn = QPushButton("Download selected")
        self.get_btn.setObjectName("primary")
        self.get_btn.setEnabled(False)
        self.get_btn.clicked.connect(self.download_selected)
        bt.addWidget(self.get_btn)
        c = QPushButton("Close")
        c.clicked.connect(self.accept)
        bt.addWidget(c)
        v.addLayout(bt)
        self.busy = False
        self._refresh = False
        self.refresh_btn = QPushButton("Refresh list")
        self.refresh_btn.setToolTip("Read the version list from the site again instead of the saved copy")
        self.refresh_btn.clicked.connect(self.refresh)
        bt.insertWidget(2, self.refresh_btn)
        self._run(self._fetch, self._fetched)

    def _pref_changed(self, *_):
        self.win.cfg.cross_check = self.xcheck.isChecked()
        self.win.cfg.update_notice = self.notice.isChecked()
        self.win.cfg.save()

    def refresh(self):
        self._refresh = True
        self.source.setText(f"Reading {online.site_url()} …")
        self._run(self._fetch, self._fetched)

    # background work ------------------------------------------------
    def _run(self, fn, done):
        self.busy = True
        self._update_buttons()
        job = FuncJob(fn)
        assert isinstance(getattr(done, "__self__", None), QObject), "slot must be a QObject method (GUI thread)"
        job.finished.connect(done)
        th = start(job, self)
        self.win._threads.append((th, job))

    def _fetch(self):
        cat = online.fetch_catalog(cache_dir=os.path.join(self.win.s.results_dir, "online"),
                                   refresh=self._refresh)
        self._refresh = False
        local = {}
        if self.product and os.path.isdir(self.win.s.firmware_dir):
            for c in online.compare_local(self.win.s.firmware_dir, cat, self.product):
                local[c.version] = f"{c.file}: {c.result}"
        return cat, local

    def _fetched(self, res):
        self.busy = False
        if isinstance(res, Exception):
            self.source.setText(f"Could not read {online.site_url()}")
            self.status.set(f"✖  {res}. Check the internet connection; your firmware folder is unchanged.", "errbox")
            self._update_buttons()
            return
        self.catalog, self.local = res
        cat = self.catalog
        cost = "  ·  ".join(f.describe() for f in cat.fetches)
        self.source.setText(f"Source: {cat.site} (unofficial changelog). Its download links point to "
                            f"{cat.data_host}, the data host named in the site's own config.js.\n"
                            f"List: {cat.note}" + (f"  ·  {cost}" if cost else ""))
        self.entries = cat.for_product(self.product) if self.product else []
        hosts = sorted({urllib.parse.urlparse(e.vendor_url).hostname or "?" for e in self.entries if e.vendor_url})
        if hosts:
            self.xcheck.setText("Also compare each download with the second address the site records for the file "
                                f"({', '.join(hosts)}; plain http; owner not confirmed; used only for comparison)")
        self._render()
        if self.product and self.product not in cat.entries:
            self.status.set(f"The site lists no product called {self.product}.", "warn")
            return
        diff = [x for x in self.local.values() if "DIFFERENT" in x]
        if diff:
            self.status.set("⚠  " + "; ".join(diff) + ". A local file differs from the site's copy of the same "
                            "version: find out where it came from before flashing it.", "warn")
        elif self.local:
            self.status.set("✔  Your local images of this product are byte-identical to the site's copies.", "okbox")

    def _render(self):
        rows = []
        for e in self.entries:
            note = (e.notes.splitlines() or [""])[0]
            here = self.local.get(e.version, "—")
            if "matches the site" in here:
                here = "✔ " + here
            elif "DIFFERENT" in here:
                here = "⚠ " + here
            rows.append([e.version, e.date, note if e.downloadable else note + "  (no file listed)", here])
        fill_table(self.table, rows, {3: _ok_color})
        self._update_buttons()

    def selected_entry(self) -> Optional[online.Entry]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.entries[rows[0].row()] if rows else None

    def _update_buttons(self):
        e = self.selected_entry()
        self.get_btn.setEnabled(bool(e and e.downloadable and not self.busy))
        if hasattr(self, "refresh_btn"):
            self.refresh_btn.setEnabled(not self.busy)

    def download_selected(self):
        e = self.selected_entry()
        if not e:
            return
        dest, xc, cat = self.win.s.firmware_dir, self.xcheck.isChecked(), self.catalog
        self.status.set(f"Downloading {e.file_name} …", "info")
        self._run(lambda: online.download(e, dest, cross_check=xc, catalog=cat), self._downloaded)

    def _downloaded(self, d):
        self.busy = False
        if isinstance(d, Exception):
            self.status.set(f"✖  {d}", "errbox")
        elif d.ok:
            self.status.set(f"✔  {d.status}: {os.path.basename(d.path)} · SHA-256 {d.sha256} · compared with "
                            f"second address: {d.cross_check}. Image checks passed; select it in the library "
                            "to see the full pre-flight checks.", "okbox")
            self.local[d.entry.version] = f"{os.path.basename(d.path)}: matches the site"
            self._render()
            self.win.verify_page.reload_keep_selection()
        else:
            self.status.set(f"✖  {d.status} (compared: {d.cross_check}). Nothing was saved.", "errbox")
        self._update_buttons()


class HistoryDialog(QDialog):
    """Every update attempt recorded in <results>/history.jsonl, newest first."""

    def import_logs(self):
        r = history.import_logs(self.win.s.results_dir)
        self.win.show_history()                 # re-open with the new rows
        self.win.history_dialog.import_msg.setText(
            f"{len(r['added'])} log(s) added, {len(r['skipped'])} skipped "
            "(already listed, simulator, or not a flash log).")
        self.close()

    COLS = ["Time", "From", "To", "Result", "Chunks", "Transfer", "File", "Log"]

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.setWindowTitle("Flash history" + ("  [SIMULATED]" if win.s.simulated else ""))
        self.resize(1050, 420)
        v = QVBoxLayout(self)
        self.records = list(reversed(history.load(win.s.results_dir)))
        where = os.path.join(win.s.results_dir, history.FILE_NAME)
        v.addWidget(muted(f"{len(self.records)} update attempt(s) recorded in {where}. Hover a row for the "
                          "image's SHA-256 and the full message."))
        self.table = make_table(self.COLS)
        hh = self.table.horizontalHeader()
        for c in range(len(self.COLS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        rows = []
        for rec in self.records:
            before = rec.get("before_version") or "?"
            frm = before.split("version")[-1] if rec.get("before_identity") == "JC_User" else "bootloader"
            res = ("✔ OK" if rec.get("ok") else
                   ("✖ FAILED (written)" if rec.get("wrote_anything") else "✖ nothing written"))
            rows.append([rec.get("time", "?"), f"{rec.get('product', '?')} {frm}", rec.get("version", "?"), res,
                         f"{rec.get('chunks_acked', 0)}/{rec.get('n_chunks', 0)}",
                         f"{rec['transfer_s']} s" if rec.get("transfer_s") else "—",
                         rec.get("file") or ("(from log)" if rec.get("tool") == "imported from log" else "?"),
                         rec.get("log") or "—"])
        fill_table(self.table, rows, {3: _ok_color})
        for r_, rec in enumerate(self.records):
            tip = f"SHA-256 {rec.get('sha256', '?')}\n{rec.get('message') or ''}"
            for c in range(len(self.COLS)):
                self.table.item(r_, c).setToolTip(tip)
        v.addWidget(self.table, 1)
        self.win = win
        bt = QHBoxLayout()
        self.import_msg = muted("")
        bt.addWidget(self.import_msg, 1)
        imp = QPushButton("Import earlier logs")
        imp.setToolTip("Add flash logs from the results folder that the history doesn't list yet "
                       "(e.g. flashes made before the history existed). Simulator logs are skipped.")
        imp.clicked.connect(self.import_logs)
        bt.addWidget(imp)
        b = QPushButton("Open results folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(win.s.results_dir)))
        bt.addWidget(b)
        c = QPushButton("Close")
        c.clicked.connect(self.accept)
        bt.addWidget(c)
        v.addLayout(bt)


# =============================================================== window
class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.s = settings
        self.report: Optional[ProbeReport] = None
        self.image: Optional[fw.FirmwareImage] = None
        self.extra_images: List[fw.FirmwareImage] = []
        self.busy = False
        self.flashing = False
        self.last_result = None
        self.last_log: Optional[str] = None
        self._threads = []
        self._ports: List[PortInfo] = []
        self._probe_failed_for: Optional[str] = None
        self._probe = None                      # (QThread, ProbeJob, PortInfo) while a probe runs
        self._restart_manual: Optional[bool] = None
        self._retry_pending = False
        self._first_seen: Dict[str, float] = {}
        self._attempts: Dict[str, int] = {}
        self._cancelled_count = 0
        self.mm_active = False if settings.simulated else bool(environment.modemmanager_active())
        self.flash_stage = None
        self._chunk_tx = 0
        self.confirm_dialog = self._confirm_dialog      # tests replace these two
        self.warn_dialog = lambda title, text: QMessageBox.warning(self, title, text)
        self.setWindowTitle("T3x Safe Updater")
        self.resize(1200, 780)
        self.cfg = settings.config or GuiConfig()
        if self.cfg.geometry:
            x, y, w, h = self.cfg.geometry
            self.setGeometry(x, y, max(w, 900), max(h, 640))

        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addWidget(QLabel("  Port: "))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(330)
        tb.addWidget(self.port_combo)
        self.rescan = QPushButton("Rescan")
        self.rescan.clicked.connect(lambda: self.start_probe(manual=True))
        tb.addWidget(self.rescan)
        self.port_combo.activated.connect(lambda _i: self.start_probe(manual=True))   # user picked a port
        tb.addSeparator()
        tb.addWidget(QLabel("  Firmware: "))
        self.toolbar_fw = QLabel("No image selected")
        self.toolbar_fw.setObjectName("muted")
        tb.addWidget(self.toolbar_fw)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(14)
        left = QVBoxLayout()
        self.steps = StepList()
        left.addWidget(self.steps)
        self.station = KeyValueBox("Station", ["Product", "Firmware", "Mode", "Serial"])
        left.addWidget(self.station)
        left.addStretch()
        hist = QPushButton("Flash history")
        hist.clicked.connect(self.show_history)
        left.addWidget(hist)
        about = QPushButton("About")
        about.clicked.connect(self.about)
        left.addWidget(about)
        h.addLayout(left)

        self.stack = QStackedWidget()
        self.connect_page = ConnectPage(self)
        self.verify_page = VerifyPage(self)
        self.flash_page = FlashPage(self)
        self.done_page = DonePage(self)
        self.recovery_page = RecoveryPage(self)
        for p in (self.connect_page, self.verify_page, self.flash_page, self.done_page, self.recovery_page):
            self.stack.addWidget(p)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.status("Looking for a station…")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_ports)
        self.timer.start(self.s.poll_ms)
        QTimer.singleShot(50, self.poll_ports)

    # ---------------------------------------------------------- helpers
    def status(self, text: str):
        self.statusBar().showMessage(text)

    @property
    def probing(self) -> bool:
        return self._probe is not None

    def set_busy(self, busy: bool):
        """busy = a flash is running. Probes never lock the controls: Rescan or picking a
        port cancels a running probe and starts a new one."""
        self.busy = busy
        for w in (self.rescan, self.port_combo, self.connect_page.probe_btn):
            w.setEnabled(not busy)
        self.verify_page.update_gate()
        self.recovery_page.update_gate()

    def _confirm_dialog(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

    def show_history(self):
        self.history_dialog = HistoryDialog(self)
        self.history_dialog.show()

    def about(self):
        QMessageBox.about(self, "T3x Safe Updater",
                          "<b>T3x Safe Updater</b><br>Read-only probe and hardened firmware updater for AiXun "
                          "T3x soldering stations.<br><br>Protocol, file format and original updater: Michael "
                          "Niewöhner (c0d3z3r0).<br>Probe, hardened updater and GUI: Dr. Daniel Melendrez, "
                          "Ivory Electronics.<br><br>GPL-2.0-or-later. Not affiliated with AiXun/JCID.")

    # ---------------------------------------------------------- ports
    def poll_ports(self):
        if self.busy:
            return
        try:
            ports = self.s.port_lister()
        except Exception:      # noqa: BLE001
            ports = []
        devs = [p.device for p in ports]
        now = time.monotonic()
        for d in devs:
            self._first_seen.setdefault(d, now)
        for d in list(self._first_seen):
            if d not in devs:
                del self._first_seen[d]
                self._attempts.pop(d, None)
        if devs != [p.device for p in self._ports]:
            self._ports = ports
            cur = self.port_combo.currentData()
            self.port_combo.clear()
            for p in ports:
                label = f"{p.device}  —  {p.serial_number or p.description or 'unknown'}"
                self.port_combo.addItem(label, p.device)
            t3x = [p for p in ports if p.is_t3x]
            if cur in devs:
                self.port_combo.setCurrentIndex(devs.index(cur))
            elif t3x:
                self.port_combo.setCurrentIndex(devs.index(t3x[0].device))
            self.connect_page.show_ports(ports)
        t3x = [p for p in ports if p.is_t3x]
        page = self.stack.currentWidget()
        if self.report and self.report.port.device not in devs and page in (
                self.connect_page, self.verify_page, self.recovery_page):
            self.report = None
            self.station.clear()
            self.steps.set_step(STEP_CONNECT)
            self.stack.setCurrentWidget(self.connect_page)
            self.connect_page.show_waiting("The station was disconnected.")
            self.status("Station disconnected")
        if self.probing and self._probe[2].device not in devs:
            self._probe[1].cancel()                 # station unplugged mid-probe
        if not self.report and page is self.connect_page and not self.probing and not self._retry_pending:
            if not t3x:
                self.connect_page.show_waiting(
                    "No AiXun station found yet." if not ports else
                    "Serial ports found, but none identifies as an AiXun T3x station.")
                self._probe_failed_for = None
            elif self.s.auto_probe and self._probe_failed_for != t3x[0].device:
                dev = t3x[0].device
                if now - self._first_seen.get(dev, now) < self.s.settle_s:
                    # a just-plugged station needs a moment before it answers (and other
                    # programs may briefly open a new serial port); don't probe instantly
                    self.connect_page.show_waiting(f"Station found on {dev}; letting it start up…")
                else:
                    self.start_probe()

    def selected_port(self) -> Optional[PortInfo]:
        dev = self.port_combo.currentData()
        for p in self._ports:
            if p.device == dev:
                return p
        t3x = [p for p in self._ports if p.is_t3x]
        return t3x[0] if t3x else None

    # ---------------------------------------------------------- probe
    def start_probe(self, manual: bool = False):
        if self.busy:
            return
        if self.probing:                            # restart: stop the running probe first
            self._restart_manual = manual or bool(self._restart_manual)
            self._probe[1].cancel()
            self.connect_page.show_waiting("Stopping the current probe…")
            return
        if manual:
            self._attempts.clear()
            self._probe_failed_for = None
            try:
                ports = self.s.port_lister()
            except Exception:  # noqa: BLE001
                ports = []
            self._ports = ports
            self.connect_page.show_ports(ports)
            if not any(p.device == self.port_combo.currentData() for p in ports):
                self.port_combo.clear()
                for p in ports:
                    self.port_combo.addItem(f"{p.device}  —  {p.serial_number or p.description or 'unknown'}",
                                            p.device)
                t3x = [p for p in ports if p.is_t3x]
                if t3x:
                    self.port_combo.setCurrentIndex([p.device for p in ports].index(t3x[0].device))
        port = self.selected_port()
        self.report = None
        self.station.clear()
        self.steps.set_step(STEP_CONNECT)
        self.stack.setCurrentWidget(self.connect_page)
        if not port:
            self.connect_page.show_waiting("No AiXun station found.")
            return
        n = self._attempts.get(port.device, 0)
        self.connect_page.show_waiting(f"Probing {port.device} (read-only)…" +
                                       (f"  attempt {n + 1}" if n else ""))
        self.connect_page.error.set("")
        self.status(f"Probing {port.device} (read-only)…")
        job = ProbeJob(port, reader_test=self.s.reader_test)
        job.finished.connect(self.on_probe_done)
        job.progress.connect(self.on_probe_progress)
        th = start(job, self)
        self._probe = (th, job, port)
        self._threads.append((th, job))

    def on_probe_progress(self, done: int, total: int):
        if self.probing and self.stack.currentWidget() is self.connect_page:
            self.connect_page.line2.setText(f"Probing {self._probe[2].device} (read-only)…  "
                                            f"{done}/{total} queries answered")

    def _retry_probe(self):
        self._retry_pending = False
        if (not self.busy and not self.probing and not self.report
                and self.stack.currentWidget() is self.connect_page):
            self.start_probe()

    def on_probe_done(self, res):
        port = self._probe[2] if self._probe else self.selected_port()
        self._probe = None
        self.verify_page.update_gate()
        self.recovery_page.update_gate()
        if isinstance(res, ProbeCancelled):
            self._cancelled_count += 1
            if self._restart_manual is not None:
                manual, self._restart_manual = self._restart_manual, None
                QTimer.singleShot(0, lambda: self.start_probe(manual=manual))
            else:
                self.connect_page.show_waiting("Probe stopped.")
            return
        if isinstance(res, (NoReply, PortUnavailable)) and port is not None:
            dev = port.device
            self._attempts[dev] = self._attempts.get(dev, 0) + 1
            first = self._first_seen.get(dev)
            if (first is not None and time.monotonic() - first < self.s.wake_window_s
                    and self.stack.currentWidget() is self.connect_page):
                what = ("Port busy (another program has it open)" if isinstance(res, PortUnavailable)
                        else "Station on USB but not answering yet")
                self.connect_page.show_waiting(f"{what} · trying again (attempt {self._attempts[dev] + 1})…")
                self.status(f"{res}")
                self._retry_pending = True
                QTimer.singleShot(self.s.retry_gap_ms, self._retry_probe)
                return
        if isinstance(res, Exception):
            self._probe_failed_for = port.device if port else None
            self.connect_page.show_waiting("")
            hint = ("Check the cable and that the station is on, then click “Probe again”.")
            if isinstance(res, (NoReply, PortUnavailable)):
                hint = ("The station is on USB but never answered. Check that it is switched on, unplug it, "
                        "wait 5 s, plug it back in. If this only happens right after plugging in, another "
                        "program may be grabbing new serial ports (see WORKFLOW → Troubleshooting).")
            self.connect_page.show_error(f"Probe failed: {res}. {hint}")
            self.status("Probe failed")
            return
        self._probe_failed_for = None
        rep: ProbeReport = res
        self.report = rep
        v = rep.version
        self.station.set(Product=v.product_str if v.product else "?",
                         Firmware=v.version_str if rep.identity == ID_APP else "— (bootloader)",
                         Mode=rep.identity.decode(errors="replace"),
                         Serial="…" + (rep.port.serial_number or "")[-8:])
        self.connect_page.show_report(rep)
        if rep.identity == ID_BOOT:
            self.status("Recovery mode: station waiting in its bootloader")
            self.steps.set_step(STEP_FLASH)
            self.recovery_page.populate(rep)
            self.stack.setCurrentWidget(self.recovery_page)
        else:
            self.status(f"Station found on {rep.port.device} · read-only probe complete")
            self.check_for_newer(rep)

    def check_for_newer(self, rep: ProbeReport):
        """Opt-in (Check online… window): look up the site's list in the background and say on the
        Connect page if it lists a newer version for this station. Silent when offline."""
        self.connect_page.update_note.set("")
        v = rep.version
        if not (self.cfg.update_notice and v.product and v.version):
            return
        product, version = v.product_str, v.version
        cache = os.path.join(self.s.results_dir, "online")

        def look():
            cat = online.fetch_catalog(cache_dir=cache)
            newer = [e for e in cat.for_product(product)
                     if e.downloadable and fw.version_key(e.version.encode()) > fw.version_key(version)]
            return newer[0] if newer else None

        self.newer_found = None
        self._newer_for = (rep, product)
        job = FuncJob(look)
        # a bound method of this window: Qt delivers it on the GUI thread (a plain closure would
        # run in the worker thread and touch widgets from there; that crashed in testing)
        job.finished.connect(self._newer_done)
        self._threads.append((start(job, self), job))

    def _newer_done(self, res):
        rep, product = self._newer_for
        if isinstance(res, Exception) or res is None:
            self.newer_found = None
            return
        self.newer_found = res
        if self.report is rep:                  # still the same station on screen
            self.connect_page.update_note.set(
                f"ℹ  aixun-updates.github.io lists a newer version for {product}: {res.version} ({res.date}). "
                "Use “Check online…” on the Verify page to download it; nothing is downloaded automatically.",
                "info")

    # ---------------------------------------------------------- navigation
    def go_connect(self):
        self.steps.set_step(STEP_CONNECT)
        self.stack.setCurrentWidget(self.connect_page)

    def go_verify(self):
        if not self.report:
            return
        if self.report.identity == ID_BOOT:
            self.recovery_page.populate(self.report)
            self.stack.setCurrentWidget(self.recovery_page)
            return
        self.steps.set_step(STEP_VERIFY)
        self.verify_page.confirm.setChecked(False)
        self.verify_page.load_library()
        self.stack.setCurrentWidget(self.verify_page)
        self.status("Select an image; every check must pass")

    # ---------------------------------------------------------- flash
    def start_flash(self):
        if self.busy or self.probing or not self.report or not self.image:
            return
        img, rep = self.image, self.report
        os.makedirs(self.s.results_dir, exist_ok=True)
        expected = Expected(rep.identity, rep.version.raw)
        job = FlashJob(img, expected, self.s.results_dir, wait=self.s.wait, simulated=self.s.simulated,
                       allow_unknown_product=False, link_factory=self.s.link_factory)
        self.last_log = job.log_path
        v = rep.version
        from_txt = (f"{v.product_str} {v.version_str}" if rep.identity == ID_APP
                    else f"{v.product_str} bootloader")
        per, basis = self.expected_per_chunk(img)
        self.flash_page.reset(img, from_txt, per, basis)
        self.flash_stage = None
        self._chunk_tx = 0
        self.steps.set_step(STEP_FLASH)
        self.stack.setCurrentWidget(self.flash_page)
        self.flashing = True
        self.set_busy(True)
        self.status("Flashing… do not unplug or power off")
        job.event.connect(self.on_flash_event)
        job.finished.connect(self.on_flash_done)
        self._threads.append((start(job, self), job))

    def expected_per_chunk(self, img: fw.FirmwareImage):
        """Median seconds per chunk from earlier successful flashes of the same product line."""
        recs = [r for r in history.load(self.s.results_dir)
                if r.get("ok") and r.get("product") == img.product_str and r.get("transfer_s")
                and r.get("n_chunks") and not r.get("simulated")]
        if not recs:
            return 0.2, "typical value measured on a T3BS"
        per = sorted(r["transfer_s"] / r["n_chunks"] for r in recs)[len(recs) // 2]
        return per, f"from {len(recs)} earlier {img.product_str} flash{'es' if len(recs) > 1 else ''}"

    def on_flash_event(self, e):
        fp = self.flash_page
        if isinstance(e, ev.ProgressEvent):
            fp.progress(e)
        elif isinstance(e, ev.StageEvent):
            names = {ev.Stage.LOAD: "Checking image", ev.Stage.CONNECT: "Connecting",
                     ev.Stage.PREFLIGHT: "Re-reading station identity", ev.Stage.CONFIRM: "Confirming station",
                     ev.Stage.BOOTLOADER: "Entering bootloader (the station resets; USB drops briefly)",
                     ev.Stage.START: "Starting transfer", ev.Stage.TRANSFER: "Sending firmware",
                     ev.Stage.VERIFY: "Verifying: waiting for the station to restart with the new firmware",
                     ev.Stage.DONE: "Done", ev.Stage.FAILED: "Failed", ev.Stage.ABORTED: "Cancelled"}
            fp.stage.setText(names.get(e.stage, e.stage.value))
            self.flash_stage = e.stage
            if e.stage == ev.Stage.VERIFY:
                self.steps.set_step(STEP_CONFIRM)
        elif isinstance(e, ev.LogEvent):
            kind, m = self._log_line(e)
            if kind is None:
                return
            fp.log.add(kind, m)

    _TX = re.compile(r"^TX \((\d+)\): (.*)$")
    _RX = re.compile(r"^RX \((\d+)\) after (\d+) ms: (.*)$")

    def _log_line(self, e):
        """Readable log lines: firmware chunks as 'chunk n/N', not raw bytes."""
        m = e.message
        tx = self._TX.match(m)
        if tx:
            size = int(tx.group(1))
            if size >= 256 and self.flash_stage == ev.Stage.TRANSFER:
                self._chunk_tx += 1
                return "TX", f"chunk {self._chunk_tx}/{self.image.n_chunks} ({size} B)"
            body = tx.group(2)
            return "TX", body[2:-1] if body.startswith("b'") and body.endswith("'") else body
        rx = self._RX.match(m)
        if rx:
            body = rx.group(3)
            body = body[2:-1] if body.startswith("b'") and body.endswith("'") else body
            return "RX", f"{body or '(no reply)'}   [{rx.group(2)} ms]"
        kind = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR"}.get(e.level, "INFO")
        if kind == "DEBUG":
            if m.startswith("Opened"):
                return "INFO", m
            return None, None
        return kind, m.replace("re-run this script", "retry")

    def on_flash_done(self, r):
        self.flashing = False
        self.set_busy(False)
        self.last_result = r
        img = self.image
        states = list(self.flash_page.map.state)
        ok = isinstance(r, FlashResult) and r.ok
        if isinstance(r, FlashResult) and not ok and r.wrote_anything and r.chunks_acked < r.n_chunks:
            self.flash_page.map.mark_failed(r.chunks_acked)
            states = list(self.flash_page.map.state)
        if ok:
            self.steps.set_step(STEP_ALL)
            self.station.set(Firmware=img.version_str, Mode="JC_User")
            self.status(r.message)
        else:
            if isinstance(r, FlashResult) and r.wrote_anything:
                self.station.set(Firmware="— (incomplete)", Mode="JC_boot (waiting)")
            stage = STEP_FLASH if not (isinstance(r, FlashResult) and r.stage == ev.Stage.VERIFY) else STEP_CONFIRM
            self.steps.set_step(stage, failed=True)
            self.status("Update not completed")
        self.done_page.show_result(r, img, self.last_log or "", states)
        self.stack.setCurrentWidget(self.done_page)
        self.report = None if ok else self.report

    def export_report(self):
        default = os.path.join(self.s.results_dir, time.strftime("t3x_report_%Y%m%d_%H%M%S.json"))
        path, _ = QFileDialog.getSaveFileName(self, "Export report", default, "JSON (*.json)",
                                              options=QFileDialog.DontUseNativeDialog)
        if path:
            self.write_report(path)

    def write_report(self, path: str) -> str:
        r = self.last_result
        data = {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "image": None if not self.image else {"file": self.image.path, "product": self.image.product_str,
                                                  "version": self.image.version_str, "crc": f"{self.image.crc_calc:04X}"},
            "result": None if not isinstance(r, FlashResult) else {
                "ok": r.ok, "stage": r.stage.value, "message": r.message, "chunks_acked": r.chunks_acked,
                "n_chunks": r.n_chunks, "wrote_anything": r.wrote_anything,
                "bootloader": r.bootloader.raw.decode(errors="replace") if r.bootloader else None,
                "after": r.after.raw.decode(errors="replace") if r.after else None,
                "duration_s": round(r.duration, 2)},
            "log": self.last_log,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        self.status(f"Report saved: {path}")
        return path

    # ---------------------------------------------------------- close
    def save_config(self):
        g = self.geometry()
        self.cfg.geometry = [g.x(), g.y(), g.width(), g.height()]
        self.cfg.save()

    def closeEvent(self, e: QCloseEvent):
        if self.flashing:
            self.warn_dialog("Update in progress",
                             "The firmware is being written. Closing now would interrupt the update.\n\n"
                             "Wait until it finishes.")
            e.ignore()
            return
        self.timer.stop()
        self.save_config()
        if self._probe:                     # read-only probe: stop it and let its thread end
            th, job, _ = self._probe
            self._restart_manual = None
            job.cancel()
            try:
                th.quit()
                th.wait(4000)
            except RuntimeError:            # thread object already deleted: it has finished
                pass
        e.accept()

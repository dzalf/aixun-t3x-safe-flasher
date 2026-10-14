# SPDX-License-Identifier: GPL-2.0-or-later
"""Dark theme (Fusion + QSS), matching the approved mockups."""

BG = "#1e2127"
PANEL = "#252931"
LINE = "#343a44"
TEXT = "#dfe3e8"
MUTED = "#9aa3af"
DIM = "#6b7280"
ACCENT = "#ff7a33"
ACCENT_SOFT = "#3a2414"
OK = "#3ecf8e"
OK_TILE = "#2e9e6b"
WARN = "#f5c04a"
ERR = "#ff6b6b"
TILE_IDLE = "#3a3f48"
TX = "#7cb3ff"

QSS = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
QToolBar {{ background: {PANEL}; border: 0; border-bottom: 1px solid {LINE}; padding: 6px; spacing: 8px; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 6px; margin-top: 14px; padding: 12px 10px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#h1 {{ font-size: 20pt; font-weight: 700; }}
QLabel#big {{ font-size: 26pt; font-weight: 700; }}
QLabel#ok {{ color: {OK}; }}
QLabel#err {{ color: {ERR}; }}
QLabel#badge {{ background: {ACCENT_SOFT}; border: 1px solid #6b3d1b; border-radius: 8px; padding: 6px 16px;
               color: #ff9d55; font-size: 22pt; font-weight: 700; }}
QLabel#chip {{ background: #2b3039; border: 1px solid #3d4450; border-radius: 4px; padding: 3px 8px; font-weight: 600; }}
QLabel#chipNew {{ background: {ACCENT_SOFT}; border: 1px solid #6b3d1b; border-radius: 4px; padding: 3px 8px;
                 font-weight: 600; color: #ff9d55; }}
QLabel#bigok {{ color: {OK}; font-size: 40pt; font-weight: 700; }}
QLabel#bigerr {{ color: {ERR}; font-size: 40pt; font-weight: 700; }}
QPushButton {{ background: #2f343d; border: 1px solid #444b57; border-radius: 5px; padding: 7px 16px; }}
QPushButton:hover {{ border-color: #5a6270; }}
QPushButton:disabled {{ color: {DIM}; background: #2a2d33; border-color: #353a42; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #1a0d05; font-weight: 700; padding: 9px 22px; }}
QPushButton#primary:disabled {{ background: #4a3326; border-color: #4a3326; color: #8a6a55; }}
QComboBox, QLineEdit {{ background: #2b3039; border: 1px solid #3d4450; border-radius: 5px; padding: 4px 8px; }}
QListWidget#steps {{ background: transparent; border: 0; font-size: 11pt; }}
QListWidget#steps::item {{ padding: 9px 4px; }}
QListWidget#steps::item:selected {{ background: {ACCENT_SOFT}; color: #ff9d55; border-left: 3px solid #ff8a3d; }}
QTableWidget {{ background: #191c21; border: 1px solid {LINE}; border-radius: 5px; gridline-color: #2b3039;
               selection-background-color: {ACCENT_SOFT}; selection-color: #ff9d55; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: 0; border-bottom: 1px solid {LINE};
                       padding: 6px; font-weight: 600; }}
QPlainTextEdit {{ background: #121418; border: 1px solid {LINE}; border-radius: 5px;
                  font-family: 'DejaVu Sans Mono', monospace; font-size: 9pt; color: #b9c0ca; }}
QProgressBar {{ background: #2b3039; border: 1px solid #3d4450; border-radius: 5px; height: 18px;
               text-align: center; color: #fff; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QFrame#warn {{ background: #3a3010; border: 1px solid #6b5a1c; border-radius: 6px; }}
QFrame#warn QLabel {{ background: transparent; color: #f5d27a; }}
QFrame#info {{ background: #16263a; border: 1px solid #27486e; border-radius: 6px; }}
QFrame#info QLabel {{ background: transparent; color: #9cc6ff; }}
QFrame#errbox {{ background: #3a1616; border: 1px solid #6e2727; border-radius: 6px; }}
QFrame#errbox QLabel {{ background: transparent; color: #ffb3b3; }}
QFrame#okbox {{ background: #12301f; border: 1px solid #1f5c3b; border-radius: 6px; }}
QFrame#okbox QLabel {{ background: transparent; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {LINE}; }}
"""

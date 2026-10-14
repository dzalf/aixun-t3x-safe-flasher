# SPDX-License-Identifier: GPL-2.0-or-later
"""Known AiXun firmware changelog entries (T3B; the T3BS list is identical).

Source: https://aixun-updates.github.io/ (unofficial archive of AiXun's own
release notes), as read on 2026-10-08. English text as published.
"""

from __future__ import annotations

from typing import List, Tuple

from .image import version_key

T3B_FAMILY: List[Tuple[str, str, str]] = [
    ("1.16", "2024-06-25", "Release V1.16"),
    ("1.15", "2023-12-20", "Brand new neural network temperature control algorithm; brand new curve interface"),
    ("1.14", "2023-06-13", "Fixed several known bugs"),
    ("1.13", "2023-04-08", "Optimized 210 heating control"),
    ("1.12", "2023-03-16", "Fixed several known bugs; fixed abnormal shortcut temperature settings"),
    ("1.11", "2023-02-16", "Fixed several known bugs"),
    ("1.10", "2023-02-13", "Fixed several known bugs"),
    ("1.09", "2023-02-03", "Optimized interface display; Celsius/Fahrenheit toggle; quick language selection at first start"),
    ("1.08", "2022-10-25", "Fixed USB driver compatibility issues; optimized factory temperature of the 210 handle"),
    ("1.06", "2021-12-23", "Added a graph function"),
    ("1.05", "2021-10-08", "Added custom boot screen"),
    ("1.04", "2021-09-25", "Optimized heating logic and reheating; added intelligent temperature compensation"),
    ("1.03", "2021-09-06", "Fixed main interface button problem"),
    ("1.02", "2021-08-30", "Optimized heating temperature of the 210 and 115 handles"),
    ("1.01", "2021-08-25", "Optimized interface display"),
]

PRODUCTS = {"T3B": T3B_FAMILY, "T3BS": T3B_FAMILY}
SOURCE = "aixun-updates.github.io"


def between(product: str, installed: str, target: str) -> List[Tuple[str, str, str]]:
    """Entries newer than `installed` up to and including `target` (downgrades: empty)."""
    entries = PRODUCTS.get(product, [])
    lo, hi = version_key(installed.encode()), version_key(target.encode())
    return [e for e in entries if lo < version_key(e[0].encode()) <= hi]

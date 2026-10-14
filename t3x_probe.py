#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compatibility wrapper: runs `t3x-probe` from the t3x package.

Works from a plain checkout (no install needed). The standalone original is
kept in tests/reference/ and is used to prove the bytes on the wire match.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from t3x.cli.probe import main  # noqa: E402

if __name__ == "__main__":
    main()

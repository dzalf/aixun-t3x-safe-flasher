# SPDX-License-Identifier: GPL-2.0-or-later
"""t3x-history: the flash history in <results>/history.jsonl.

    t3x-history --results results list
    t3x-history --results results import               # add real flash logs found in results/
    t3x-history --results results import ~/old_logs    # ...or in another folder (e.g. from before the workspace)
"""

from __future__ import annotations

import argparse
import os
import sys

from ..core import history


def main(argv=None):
    ap = argparse.ArgumentParser(description="Flash history (results/history.jsonl)")
    ap.add_argument("--results", default="results", help="results folder holding history.jsonl")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="one line per update attempt (default)")
    p = sub.add_parser("import", help="add records rebuilt from flash logs not yet in the history")
    p.add_argument("log_dir", nargs="?", help="folder with t3x_flash_*.log (default: the results folder)")
    a = ap.parse_args(argv)
    if a.cmd == "import":
        src = os.path.expanduser(a.log_dir) if a.log_dir else a.results
        if not os.path.isdir(src):
            sys.exit(f"ERROR: no such folder: {src}")
        r = history.import_logs(a.results, src)
        for line in r["added"]:
            print(f"  added    {line}")
        for line in r["skipped"]:
            print(f"  skipped  {line}")
        print(f"{len(r['added'])} added, {len(r['skipped'])} skipped. "
              "Imported records have no file name or SHA-256 (logs don't contain them).")
        sys.exit(0)
    recs = history.load(a.results)
    if not recs:
        print(f"No flashes recorded yet in {os.path.join(a.results, history.FILE_NAME)}")
        print("Earlier flash logs can be added with:  import [folder]")
    for rec in recs:
        print(history.summary(rec) + (f"   [{rec['log']}]" if rec.get("log") else "")
              + ("   (imported)" if rec.get("tool") == "imported from log" else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()

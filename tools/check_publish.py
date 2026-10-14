#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pre-publication check for the project repository (run via `./aixun check-publish`).

Looks at every tracked file AND every commit in the history for things that must
not reach a public repository: firmware images, flash logs, the flash history,
real USB serial numbers, private keys and access tokens, oversized files. Also
lists the commit authors so you can see which names/e-mails will become public.

Read-only: it never changes the repository. Exit code 0 = nothing found.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys

MAX_BYTES = 5 * 1024 * 1024
FORBIDDEN_FILES = ["*.bin", "*.log", "history.jsonl", "*.source.json", "gui.json", "QtProject.conf",
                   "*.pem", "*.key", "id_rsa*", "id_ed25519*"]
ALLOWED_FILES = ["tests/data/*.log"]            # anonymised examples used by the tests
CONTENT = {
    "real USB serial number": r"JCID_[A-Z0-9]+_[0-9A-F]{12}\b",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "GitHub token": r"\b(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
}


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def main(repo: str) -> int:
    problems = []
    if git(repo, "status", "--porcelain").strip():
        problems.append("uncommitted changes in the repository (commit or discard them first)")

    revs = git(repo, "rev-list", "--all").split()
    print(f"Checking {len(revs)} commit(s) in {repo}")

    # 1. files: current tree and every file name that ever existed in the history
    names = set(git(repo, "log", "--all", "--format=", "--name-only").split()) | set(git(repo, "ls-files").split())
    for n in sorted(names):
        base = os.path.basename(n)
        if any(fnmatch.fnmatch(n, a) for a in ALLOWED_FILES):
            continue
        if any(fnmatch.fnmatch(base, pat) for pat in FORBIDDEN_FILES):
            problems.append(f"file that must not be published (now or in history): {n}")
    for line in git(repo, "ls-tree", "-r", "-l", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        size = meta.split()[3]
        if size.isdigit() and int(size) > MAX_BYTES:
            problems.append(f"large file ({int(size) // 1024} KB): {path}")

    # 2. content of every commit
    for label, rx in CONTENT.items():
        out = subprocess.run(["git", "-C", repo, "grep", "-I", "-n", "-E", rx, *revs],
                             capture_output=True, text=True).stdout
        hits = sorted({":".join(h.split(":")[1:3]) for h in out.splitlines()})
        for h in hits[:20]:
            problems.append(f"{label} in {h}")
        if len(hits) > 20:
            problems.append(f"{label}: {len(hits) - 20} more location(s)")

    # 3. who will appear as author
    authors = sorted(set(git(repo, "log", "--all", "--format=%an <%ae>").splitlines()))
    print("\nCommit authors that will be public:")
    for a in authors:
        print(f"  {a}")

    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        print("\nNothing was changed. Fix these before pushing (see docs/MAINTAINERS.md).")
        return 1
    print("OK: no firmware, logs, history, serial numbers, keys or tokens found in the tree or its history.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))

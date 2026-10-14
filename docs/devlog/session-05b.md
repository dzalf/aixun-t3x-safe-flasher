# Session 05b: Publication and contributor documents

| | |
|---|---|
| Date | 2026-10-14 |
| Trigger | Repository published on GitHub; the maintainer asked what was missing (an executable?), for a TODO / help-wanted document, and whether the folder structure was documented |
| Outcome | Documentation only; no code changes. 104 tests unchanged |

## 1. Publication (done by the maintainer on the Pi)

| Step | Result |
|---|---|
| Empty repository `dzalf/aixun-t3x-safe-flasher`, one commit "Initial release 0.1.0", tag `v0.1.0` | Done; the published tree is identical to the prepared one (checked by cloning it) |
| Authentication | Personal access token instead of the GitHub CLI: Kali's arm64 package sources have no `gh` package |
| First push errors | `403 … denied to dzalf` (token had no access to the newly created repository), then `refusing to allow a Personal Access Token to create or update workflow` (missing workflow permission). Both fixed in the token settings; documented in MAINTAINERS §2.3 |
| Commit author | Recorded as the maintainer's personal address, not the planned noreply address. Reported to the maintainer; MAINTAINERS §3 now shows how to set and check the noreply address |

## 2. Added or changed

| File | Change |
|---|---|
| `ROADMAP.md` (new) | Help wanted (H1–H7), good first issues (G1–G3), planned work (P1–P5), not planned. Each item says whether a station is needed |
| `README.md` | Folder structure of the repository and of the workspace; ROADMAP and MAINTAINERS in the documentation table |
| `CONTRIBUTING.md` | Points to ROADMAP and the folder structure |
| `docs/MAINTAINERS.md` | Rewritten: full paths, no shell variables, token permissions and error messages, commit identity, deliveries to GitHub, pull-request review, releases, record of the first publication |
| `docs/DEVELOPMENT_REPORT.md` | L11 closed; feature backlog moved to ROADMAP; session index |
| `CHANGELOG.md` | "Unreleased" section |

## 3. Decisions

| Decision | Reason |
|---|---|
| One ROADMAP.md with a "help wanted" section, rather than separate TODO and HELP_WANTED files | One list can't disagree with itself. GitHub's own mechanism for help wanted is issue labels (`help wanted`, `good first issue`), which link back to the ROADMAP IDs |
| No standalone executable for now | Linux users install Python tools with `pip`/`pipx`. A bundled build would be 150–250 MB per architecture and need rebuilding for every release. The actual gap is installing without the workspace (ROADMAP P1) |

## 4. Checks

- G1 verified against the code: no command has `--version`, and `t3x-sim` already uses `--version` for the simulated firmware version (excluded from G1).
- Every file and section referenced from ROADMAP exists.

## 5. Revision (05c, same day)

The 05b version of `docs/MAINTAINERS.md` used the maintainer's own machine paths and
GitHub username in its commands. That suited a private checklist, not a public document. 05c rewrites it
for any maintainer: commands run from the workspace folder (`./aixun …`, `git -C project …`), the
username and noreply address are described rather than written in, and the first-publication record is a
short summary. Added: saving the token (`credential.helper store`, with its risk) and commit messages.

## 6. Revision (05d, same day)

| Problem | Change |
|---|---|
| The public documents used "session" and "delivery" (`t3x_sessionXX.zip`) without ever saying what they were or where the zips came from | README section "How this project is developed": AI-assisted sessions, each handed over as a zip snapshot of the project folder; an AI assistant is not needed, it made development faster; a snapshot is made with `git archive`. Elsewhere the zips are called snapshots |
| WORKFLOW.md (314 lines) repeated INSTALLATION.md | Rewritten as a ~150-line reference: commands, snapshots, simulator, moving, workspace troubleshooting, manual equivalents. Firmware provenance and the ModemManager check/rule moved to INSTALLATION.md |
| INSTALLATION.md used a shell variable for the workspace | Explicit `~/aixun`, with one sentence on changing it |
| SCRIPTS_GUIDE.md (474 lines) repeated setup steps and long sample outputs; referred to a `t3xupdate.py` that isn't in the repository root | Condensed to background, the standalone scripts, what is normal during a flash, failures and technical notes |
| DEVELOPMENT_REPORT referred to commits of the private development history | Removed; status table updated |

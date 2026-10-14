# Session 03: Simulator fixes, notices, flash history, firmware from aixun-updates.github.io

| | |
|---|---|
| Date | 2026-10-12 |
| Input | Two real GUI flashes on 2026-10-11 (T3BS 1.16 → 1.15 → 1.16, both 82/82, version read back); user request for items 1–5 of the session-03 list |
| Outcome | All five items done; **90 passed** (+24 tests) |
| Wire bytes changed? | No (golden tests pass) |

## 1. Hardware result that started this session

| Flash | Transfer | Bootloader entry | After | Read back |
|---|---|---|---|---|
| 1.16 → 1.15 (23:49) | 16.5 s | drop 0.26 s after the echo, back as ttyUSB1 | drop after last chunk, back as ttyUSB0 2.3 s later | `JC_User` 1.15 |
| 1.15 → 1.16 (23:51) | 16.7 s | drop 0.21 s | same | `JC_User` 1.16 |

## 2. What was built

| # | Item | Details |
|---|---|---|
| 1 | Simulator faults happen once | `Scenario.fault_once` (default True): `fail_at_chunk` / `bad_ack_at_chunk` fire on the first transfer only, like a real cable pull, so the documented demo (fail → Resume → Recovery → success) now works. `t3x-sim --fault-every-time` keeps the old behaviour. Found in the Pi's 21:45 logs: Resume failed again at 31/82 |
| 1 | Simulator records kept apart | GUI `--sim` and `t3x-update` with `T3X_SIM_PORTS` write logs and history to `results/sim/`; simulator logs carry `SIMULATED STATION`. `latest_log()` skips simulator logs (also older ones, recognised by their `/tmp/t3x-sim-*` port), so the Recovery page and `t3x-update` never describe a simulated failure as the real station's |
| 2 | Downgrade warning in the CLI | `t3x-probe`: "Station v1.16 vs file v1.15  (DOWNGRADE)" + what to check. `t3x-update` pre-flight: "DOWNGRADE 1.16 -> 1.15: …" before the `yes` prompt |
| 3 | ModemManager notice | `core/environment.modemmanager_active()` asks `systemctl is-active` (read-only; `None` if it can't be asked). Shown on the Verify page and in the `t3x-update` pre-flight, with the temporary stop command; recorded in the flash log. Not shown in simulator mode |
| 3 | Duration on the confirmation | Measured value: ~0.2 s per chunk + ~8 s for the two USB restarts ("about 24 s" for 82 chunks) moved into the checkbox text, freeing banner space |
| 4 | Flash history | `core/history.py`: one JSON line per attempt in `results/history.jsonl` (GUI and `t3x-update`): time, tool, station before/after, bootloader, file, SHA-256, chunks, durations, result, log name. **Flash history** button in the GUI; `./aixun history` in the terminal. Declined/aborted runs are recorded too |
| 5 | Firmware online | `core/online.py`, `t3x-online` (`list`, `get`, `compare`), `./aixun online …`, and **Check online…** on the Verify page. Details in §3 |

## 3. Firmware online: how it works and why

Facts read from the site's own files (github.com/aixun-updates/aixun-updates.github.io, commit a6affd4):

| Piece | Value |
|---|---|
| Page | `https://aixun-updates.github.io/`, static |
| `assets/js/config.js` | `rootUrl: 'https://usr.tnyzeq.icu/~dd/aixun-updates'` |
| Version list | `<rootUrl>/files/changelog.json`: `{product: [{version: "T3BS:1.16", time, fileName, en_note, ch_note, url, fallbackSortKey}]}` |
| Download link on the page | `<rootUrl>/firmware/<fileName>` |
| `url` field (not shown on the page) | `http://aixun-file.oss-cn-shenzhen.aliyuncs.com/config/<timestamp>/<fileName>`; owner not confirmed |
| Checksums | None published |

| Decision | Rationale |
|---|---|
| D24: read `rootUrl` from the site's `config.js` on every run | The user trusts aixun-updates.github.io; the tool follows wherever that page links instead of hard-coding a personal domain |
| D25: https required for the site and data host (http only for localhost in tests) | |
| D26: the second address is used **only** for comparison, on by default, with a visible switch; different bytes → nothing saved; unreachable → saved and recorded as "unavailable" | Two independent places agreeing is the strongest check available without published checksums. CRC-16 catches corruption, not substitution |
| D27: every download must pass the image checks and match the listed product and version; existing files are never overwritten | |
| D28: provenance file `<file>.source.json` (SHA-256, both addresses, comparison result, catalogue entry) | The user can always tell where a .bin came from |
| D29: no automatic flashing, no automatic downloads | Every write to the station stays a deliberate act |

Not verified live: the development container cannot reach these hosts. The parser is tested against a local stand-in built from the real `config.js` and the field names reported by the live JSON. First live run is on the Pi (`./aixun online list --product T3BS`).

## 4. Tests added (24)

| File | Tests |
|---|---|
| `tests/test_session03.py` (9) | Fault once; fault every time; `latest_log` skips simulator logs (old and new); CLI probe downgrade; CLI update downgrade + ModemManager + declined run in history; history robustness and summary; ModemManager check read-only/overridable; GUI records and shows history; GUI ModemManager notice and duration |
| `tests/test_online.py` (15) | Catalogue follows `config.js`; save with provenance and "already present"; two addresses disagree → nothing saved; second address unreachable; no second request when switched off; refusals for non-image / wrong product / wrong version; never overwrite; compare local files; plain-http data host refused; offline error; CLI; real `config.js` snapshot; GUI dialog |
| Changed | `test_cli::test_update_cli_success_writes_log` now expects the log in `sim/` and a history record; GUI tests mark their windows as simulated |

## 5. Open

| ID | Item |
|---|---|
| L17 | Recovery from an interrupted real transfer: simulator only |
| L18 | Online catalogue not yet run against the live site (container has no access) |
| L19 | The second address's owner is unconfirmed; it is only used for comparison |

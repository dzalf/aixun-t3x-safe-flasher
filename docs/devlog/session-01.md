# Session 01: Core engine, simulator, CLI refactor

| | |
|---|---|
| Date | 2026-10-11 |
| Goal | Turn the two hardware-proven scripts into a reusable, UI-free engine without changing what goes on the wire |
| Outcome | Done. 44 tests passing, including byte-for-byte equivalence with `t3xupdate_safe.py` |
| Hardware tested | **No.** Everything in this session ran against the simulator. See [Hardware test plan](#hardware-test-plan-for-this-session) |
| Next | Session 02: PySide6 GUI on top of this engine |

---

## 1. What was built

```
pyproject.toml                 package t3x-safe-updater, entry points, extras [gui] [dev]
t3x_probe.py                   compatibility wrapper -> t3x.cli.probe   (README commands still work)
t3xupdate_safe.py              compatibility wrapper -> t3x.cli.update
src/t3x/core/
  crc.py                       CRC-16/MODBUS, pure Python (removes the crcmod build dependency)
  image.py                     JCID image parse/validate, chunking, directory scan, image diff
  protocol.py                  command/reply constants, version-string parsing, start command
  events.py                    Stage / LogEvent / StageEvent / ProgressEvent / PortsEvent
  link.py                      port discovery (injectable), SerialLink, Timing
  flasher.py                   the update procedure as a state machine, emits events
  probe.py                     read-only probe with an enforced command whitelist
  logfile.py                   log writing (same format as before) and log parsing
src/t3x/sim/station.py         pty-based simulated T3x station + `t3x-sim` command
src/t3x/cli/                   t3x-probe, t3x-update, t3x-image
tests/                         44 tests (pytest), reference copies of the original scripts
```

New commands after `pip install -e .`:

| Command | Purpose |
|---|---|
| `t3x-probe` | Same as `t3x_probe.py`, plus `--json` and `--wait S` |
| `t3x-update` | Same as `t3xupdate_safe.py`, plus `--log-dir` and `--allow-unknown-product` |
| `t3x-image` | **New.** Offline `info`, `scan DIR [--product]` and `diff A B` for update images |
| `t3x-sim` | **New.** Simulated station for developing without an iron |

## 2. Design decisions

| # | Decision | Why |
|---|---|---|
| D1 | The core never prints or prompts. It emits events and asks a `confirm(preflight)` callback | The CLI and the GUI share one tested engine |
| D2 | Port discovery is a function passed into the link | Lets the simulator and tests supply ports; no monkeypatching in production code |
| D3 | `T3X_SIM_PORTS` environment variable switches discovery to the simulator's port file | The real CLI (and later the GUI) can be run against `t3x-sim` unchanged |
| D4 | All delays live in one `Timing` object; defaults equal the original script | Tests use `Timing.fast()`; the wire bytes do not depend on timing |
| D5 | Pure-Python CRC instead of `crcmod` | `crcmod` fails to build on some systems; this is one less install problem. Verified against the CRC-16/MODBUS check value and both real images |
| D6 | The simulator runs on a real pseudo-terminal | It exercises the real pyserial code paths, including device loss (EIO) and re-enumeration under a new path |
| D7 | Original scripts kept verbatim in `tests/reference/` | They are the oracle for the equivalence tests |
| D8 | The probe's whitelist lives in the session object, not the CLI | The GUI cannot accidentally send a state-changing command through the probe |

## 3. Behaviour changes vs `t3xupdate_safe.py`

None of these change the bytes sent on a successful run (proven by `test_flash_bytes_identical_to_hardware_proven_script`).

| # | Change | Type |
|---|---|---|
| B1 | In bootloader (recovery) mode the product is checked against the bootloader's own version string (`00160000JC_M_T3BS_version1.01` -> `T3BS`). The original skipped the product check unless the station was in application mode. If the bootloader string has no product field, flashing is refused unless `--allow-unknown-product` is given | Safety |
| B2 | Device loss during pre-flight, start or verify is reported as a clean error instead of a Python traceback | Robustness |
| B3 | Warnings and errors are never printed on the same line as the progress counter | Usability (bug found this session, see §5) |
| B4 | `t3x-update` reports the outcome of the previous log in the same folder if it was interrupted ("stopped at chunk 31/82 (device lost)") | Recovery |
| B5 | Pre-flight in bootloader mode says "bootloader v1.01" instead of "v1.01", plus a "Recovery:" line. A same-version re-flash is noted | Clarity |
| B6 | Progress shows 82/82 (100%) at the end, even when the last chunk is answered by a USB drop instead of an ACK | Clarity |
| B7 | `t3x-probe` in bootloader mode explains the state and points to `t3x-update` instead of "do not flash yet" | Clarity |

## 4. Verification

### 4.1 Test suite: 44 passed (about 110 s)

| Area | Tests | What they prove |
|---|---|---|
| Equivalence | 3 | Refactored flash = **identical byte stream** to `t3xupdate_safe.py` (82-chunk image); every state-changing byte identical to upstream `t3xupdate.py` (upstream only adds read-only queries); probe queries identical to `t3x_probe.py` |
| Image + protocol | 14 | CRC check value; version-string and start-command parsing; layout and 82 chunks with a 256-byte last chunk; magic/size/CRC corruption; four kinds of wrong vector table; legacy `version1.26` field; directory scan; real-image values (CRC 1EE0/02BD, reset handlers, 84% difference) |
| Flasher | 13 | Success, with the exact stage sequence; abort sends only queries; product mismatch in both modes; unknown bootloader product; **interrupted at chunk 8, then recovered**; bad ACK; no start ACK; verify failure; split replies; `JC_reset` ACK; slow re-enumeration; timeout; same-version flag |
| Probe | 5 | Only whitelisted bytes are sent; echo and `JC_hardware` refused unless allowed; the reader test catches a split reply that the upstream reader truncates; bootloader classification |
| CLI | 9 | Human and JSON output; product-mismatch failure; flash with log file; corrupt file refused with nothing sent; declined prompt sends only queries; image info/scan/diff; bootloader wording |

Run: `pytest` (add `T3X_FW_DIR=<folder with the real .bin files>` to include the real-image test; the images are never committed).

### 4.2 Manual end-to-end run against `t3x-sim` (separate process, real CLI)

1. `t3x_probe.py --fw JC_M_T3BS_1.16.bin --reader-test 5`: 8/8 PASS, "Station v1.06 vs file v1.16".
2. `t3x-update` with the simulator set to drop off USB at chunk 31: stopped with
   `ERROR: Device lost at chunk 31/82. Station should be in bootloader: do NOT power off, re-run this script.`
3. `t3x-probe --wait 5`: `JC_boot`, bootloader string `00160000JC_M_T3BS_version1.01`, product T3BS, recovery message.
4. `t3x-update` again, same log folder:
   ```
   WARNING: Previous log t3x_flash_20261011_014714.log: stopped at chunk 31/82 (device lost)
   ...
     Station : T3BS bootloader v1.01 (JC_boot)
     Recovery: the station is waiting in its bootloader; this will complete the update.
   INFO: Station already in bootloader.
   ...
   INFO: Update successful. Station now runs T3BS v1.16.
   ```
5. `t3x-image diff` on the real images reproduced the session-0 analysis: 84.3% of payload bytes differ; `C115`/`C210` only in T3B, `T115` only in T3BS.
6. `pip install -e .` in a clean venv installs all four commands.

## 5. Bugs found and fixed during the session

| Bug | Found by | Fix |
|---|---|---|
| `--json` made later human-readable probe calls in the same process silent (module-level state leaked) | CLI test | The output function is now reset on every call |
| The "Device lost at chunk n" error was printed on the progress line, where it was easy to miss | Manual simulator run | The console breaks the line before any warning or error (B3) |
| A probe run immediately after an interrupted flash found no station (it was re-enumerating) | Manual simulator run | `t3x-probe --wait S` |
| Bootloader mode: the probe said "do not flash yet", and pre-flight showed the bootloader version as if it were the firmware version | Manual simulator run | B5, B7 |
| Test-side errors: a diff test compared against a junk file; a chunk count ignored the 256-byte header | Test failures | Tests corrected; the code was right |

## 6. Known limitations and open questions

| # | Item | Impact |
|---|---|---|
| L1 | Not yet run on the real station. The simulator models one T3BS unit's observed behaviour | The session-1 hardware test plan below closes this |
| L2 | The bootloader product check (B1) relies on the one bootloader string seen so far. Other models/revisions may differ; `--allow-unknown-product` is the escape hatch | Recovery on other models |
| L3 | Whether the real station ACKs the last chunk or just drops is handled both ways, but only "drop" has been observed | None expected |
| L4 | With `--hardware`, the reader test still covers only `JC_identity` and `JC_version` (the original also re-tested `JC_hardware`) | Cosmetic |
| L5 | Rollback (flashing an older version) is still untested on hardware | Documented in README |

## Hardware test plan for this session

All read-only except step 4. Run from the repository root with the venv active.

```bash
pip install -e .
t3x-probe --fw JC_M_T3BS_1.16.bin --reader-test 50      # expect 8/8 PASS, "same version - re-flash"
t3x-probe --json > probe.json                           # send me this file
t3x-image info JC_M_T3BS_1.16.bin JC_M_T3BS_1.06.bin    # offline
t3x-update -d JC_M_T3BS_1.16.bin                        # OPTIONAL: re-flash 1.16 over 1.16
```

Step 4 is the lowest-risk real flash: same file, same version, same procedure that already worked on 2026-10-08. Skip it if you'd rather wait for the GUI.

# Session 01a: Corrections from the first Raspberry Pi test run

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | `pytest` on the target machine (Raspberry Pi 5, Kali Linux, **Python 3.14.7**, pytest 9.1.1): 1 failed, 42 passed, 1 skipped |
| Outcome | Root cause found and fixed; 5 regression tests added; **49 passed** (development container, Python 3.13) |
| Hardware tested | No (simulator only). The fix covers the two moments when the real station drops off USB on purpose |

## 1. The failure

```
tests/test_flasher.py::test_verify_detects_station_not_back_in_app
src/t3x/core/flasher.py:191   ack = link.transfer(data, timeout=link.t.chunk_timeout)
src/t3x/core/link.py:188      self.ser.flush()
serial/serialposix.py:673     termios.tcdrain(self.fd)
E   termios.error: (5, 'Input/output error')
```

## 2. Root cause

| Step | What happens |
|---|---|
| 1 | The host writes the **last chunk**. The station (here the simulator) takes it and immediately drops off USB, as the real T3BS did on 2026-10-08 |
| 2 | `SerialLink.transfer()` then calls `ser.flush()`, which in pyserial is `termios.tcdrain()` |
| 3 | On a device that has just vanished, `tcdrain` raises **`termios.error` (EIO)**. This is **not** a `serial.SerialException` |
| 4 | The flasher only treated `SerialException` as "device lost", so the expected drop became an unhandled crash |

It is a **race**: on the x86 development container the drain finished before the device vanished, so all 44 tests passed there. The Pi was slower and lost the race. On real hardware the same race exists at the **two planned resets**: the bootloader echo and the last chunk.

**The reference script `t3xupdate_safe.py` from session 00 has the same latent issue.** It also calls `flush()` and catches only `SerialException`. It did not trigger during the successful 2026-10-08 flash, but it could have. Since session 01 the `t3xupdate_safe.py` in the repository root is a wrapper around the package, so anyone using it now gets the fix. The frozen copy in `tests/reference/` is left unchanged on purpose, because it is the byte-level oracle.

## 3. Fix

| File | Change |
|---|---|
| `core/link.py` | New `IO_ERRORS = (SerialException, OSError, termios.error)`. `DeviceLost` is now a dedicated exception class. `transfer()` converts any of these errors during reset/write/flush/read into `DeviceLost`. `connect()` treats them as "not ready yet, keep polling" |
| `core/probe.py` | `ProbeSession.query`, `query_original_reader` and `listen` convert the same errors into `DeviceLost` |
| `cli/probe.py` | A disconnect during the probe prints `ERROR: station disconnected during the probe ...` with a hint and exits 1, instead of a traceback |

Wire bytes are unchanged: the equivalence tests (S1–S3) still pass.

## 4. Regression tests (`tests/test_device_loss.py`)

These tests make `flush()` raise EIO **deterministically** at the chosen moment, so they no longer depend on machine speed.

| Test | Forces EIO after | Expected |
|---|---|---|
| `test_transfer_converts_eio_to_device_lost` | any write | `DeviceLost` raised |
| `test_eio_after_last_chunk_is_the_expected_drop` | last chunk (**the Pi failure**) | Update completes successfully |
| `test_eio_on_bootloader_echo_is_the_expected_drop` | version echo | Bootloader entered, update completes |
| `test_eio_mid_transfer_is_reported_not_raised` | chunk 5 of 21 | Clean "Device lost at chunk 5/21 … do NOT power off" |
| `test_probe_cli_reports_disconnect_cleanly` | `JC_version` in the probe | Error message, exit code 1 |

**Proof that they reproduce the bug:** with the session-01 error handling put back temporarily, 4 of the 5 fail with `termios.error: (5, 'Input/output error')`, the same error as on the Pi. The fifth exercises the probe, whose fix is in a different module.

## 5. Other notes from the Pi run

| Note | Action |
|---|---|
| The traceback shows pyserial loaded from `/usr/lib/python3/dist-packages`, i.e. Kali's system copy, not one installed in the venv. Harmless (Kali ships pyserial 3.5), but it suggests the venv can see system packages | Check with `pip show pyserial`. Optional: recreate the venv without `--system-site-packages` |
| Python 3.14.7 on the Pi vs 3.13 in development: 42 of 43 runnable tests already passed before the fix | Re-run `pytest -v -rs` on the Pi to confirm 48 passed, 1 skipped |
| The session-01 hardware test plan left out creating and activating the venv | Corrected below |

## Hardware test plan (corrected)

```bash
cd ~/Documents/Scripts/Aixun_Updater_GUI
python3 -m venv venv            # once
source venv/bin/activate        # every new terminal
pip install -e ".[dev]"

pytest -v -rs                   # no station needed: expect 48 passed, 1 skipped
# station connected (read-only):
t3x-probe --fw /path/to/JC_M_T3BS_1.16.bin --reader-test 50
t3x-probe --json > probe.json
# optional real flash (same version):
t3x-update -d /path/to/JC_M_T3BS_1.16.bin
```

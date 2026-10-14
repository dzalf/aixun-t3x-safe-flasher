# Session 02a: Test-harness fix from the Pi run of session 02

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | `./aixun test` on the Pi (Python 3.14.7), delivery 02: **1 failed, 57 passed** |
| Outcome | Failure reproduced deterministically and fixed in the test harness; a logging leak between tests fixed; **58 passed**, also with the race forced |
| Product code changed? | **No.** Only `tests/test_golden.py` and `tests/conftest.py` |

## 1. The failure

```
tests/test_golden.py::test_flash_bytes_identical_to_hardware_proven_script FAILED
tests/reference/t3xupdate_safe.py:262   ack = st.transfer(data, timeout=5.0)
tests/reference/t3xupdate_safe.py:165   self.ser.flush()
serial/serialposix.py:673               termios.tcdrain(self.fd)
E   termios.error: (5, 'Input/output error')
```

It stopped after chunk 81/82, inside the **frozen reference script** (the byte oracle), before the new engine had even run.

## 2. Root cause

The same race as session 01a, this time hitting the oracle instead of the package:

| Step | What happens |
|---|---|
| 1 | The host writes the last 256-byte chunk; the simulated station takes it and drops off USB, as the real T3BS does |
| 2 | If the host thread is slow to reach `flush()`, `tcdrain` runs on a vanished device and raises `termios.error` (EIO) |
| 3 | The reference script catches only `serial.SerialException` → crash |

This is limitation **L8**: the frozen copy keeps the bug on purpose, because it is the record of what was proven on hardware. The package itself has handled this since 01a (S10). The test passed on the Pi in 01c and failed now: same code path, different scheduling. It is a flaky test, not a regression.

## 3. Fix

| File | Change |
|---|---|
| `tests/test_golden.py` | The oracle gets its own `serial` module whose `Serial.flush()` converts `termios.error`/`OSError` into `SerialException`, the exception the script already handles at the last chunk. Applied only to the oracle (`monkeypatch.setattr(ref, "serial", …)`); the package under test is untouched. Wire bytes are unaffected: the shim only decides whether the oracle survives the drop that ends every flash |
| `tests/conftest.py` | Autouse fixture restores the `t3x` logger after each test. The reference script adds a handler on pytest's per-test stderr; later tests then logged into a closed stream (`--- Logging error --- ValueError: I/O operation on closed file`, 7× in the Pi output) |

## 4. Verification

| Check | Result |
|---|---|
| Forced race: a pytest plugin delays `flush()` by 300 ms after any 256-byte write (the host "descheduled" while the station drops) | **Before the fix:** the same test fails with the same `termios.error` as on the Pi ✅ reproduced. **After:** passes, 3 of 3 repeats |
| Full suite with the race forced (also hits the package's own last chunk) | 58 passed |
| Full suite, normal | 58 passed |
| Logging noise, test order as on the Pi (`cli, device_loss, flasher, golden`) | 10 "Logging error" blocks before, 0 after |

The plugin used for the forced race is kept in the session notes, not in the repo; the deterministic tests in `test_device_loss.py` already cover the package.

## 5. Limitations

| ID | Change |
|---|---|
| L8 | Still accepted for the frozen file itself; the golden test no longer depends on it losing or winning the race |
| L10 | Second timing-dependent test found and made deterministic |

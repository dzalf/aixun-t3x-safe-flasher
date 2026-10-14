# Background, technical notes and the standalone scripts

Why Linux, how to tell a T3B from a T3BS, the serial protocol and file format, and how to use the two
scripts in the repository root (`t3x_probe.py`, `t3xupdate_safe.py`) without installing anything.

The scripts are the names of the original console procedure that first updated a T3BS from 1.06 to 1.16
in October 2026. They are now thin wrappers that run the `t3x` package straight from a checkout. For most
people the workspace + GUI route in [INSTALLATION.md](../INSTALLATION.md) is easier. The original
upstream updater (Michael Niewöhner) is kept unchanged in `tests/reference/t3xupdate_upstream.py`.

## Contents

1. [Why not Windows?](#1-why-not-windows)
2. [T3B vs T3BS: which firmware?](#2-t3b-vs-t3bs-which-firmware)
3. [Using the standalone scripts](#3-using-the-standalone-scripts)
4. [What is normal during a flash](#4-what-is-normal-during-a-flash)
5. [If something fails](#5-if-something-fails)
6. [Technical notes](#6-technical-notes)

---

## 1. Why not Windows?

The station's USB interface reports itself as an FTDI FT232
(`USB\VID_0403&PID_6001&REV_0400`). It is **not a genuine FTDI chip**. The
station's GD32 MCU emulates the FTDI interface itself; the USB serial-number
prefix `JCID_T3B_` is compiled into the main firmware. See also
[aixun_t3a_rev](https://github.com/c0d3z3r0/aixun_t3a_rev).

What happens on Windows 10/11:

| Attempt | Result |
|---|---|
| Current FTDI CDM driver (e.g. 2.12.36.x) | **Code 10**, "This device cannot start". The driver rejects the non-genuine device. |
| Old CDM 2.08.x driver, force-installed | Blocked by **Memory Integrity** (Core Isolation), "A driver can't load on this device" |
| Same, with Memory Integrity off | **Code 52**: Windows rejects the old driver's signature |
| AiXun's own driver installer | Installs the current FTDI driver, which brings back Code 10 |

**The Linux kernel's `ftdi_sio` driver accepts the device with no extra
configuration.** The quickest route is therefore any Linux machine: a
Raspberry Pi (tested), an Ubuntu live USB, or WSL2 with `usbipd-win`
(untested).

> Firmware 1.08 lists "Fix USB driver compatibility issues". After updating
> to 1.16 it is worth checking whether Windows accepts the device. This has
> not been confirmed.

---

## 2. T3B vs T3BS: which firmware?

AiXun publishes separate `JC_M_T3B_x.xx.bin` and `JC_M_T3BS_x.xx.bin` images
with the **same firmware version numbers and the same changelogs**. **Do not
decide by the sticker, the stand or the menu.** The only reliable way to know
is to ask the station:

```bash
./aixun probe
# or, without the workspace: python3 t3x_probe.py
```

Look at the `Product (field2)` line:

- `T3B` → use `JC_M_T3B_x.xx.bin`
- `T3BS` → use `JC_M_T3BS_x.xx.bin`

The unit tested here had a **T3B sticker, the separate plug-in stand of a
T3B, and "T3B" on the front-panel screen**, yet it reported `T3BS`. Its
factory bootloader also identified as `JC_M_T3BS`. So this board was built
as a T3BS.

What the two 1.16 images have in common and where they differ:

| | `JC_M_T3B_1.16.bin` | `JC_M_T3BS_1.16.bin` |
|---|---|---|
| Size | 166,144 B | 166,144 B |
| Version reply | `JC_M_T3B_version1.16` | `JC_M_T3BS_version1.16` |
| Display name / USB serial prefix | `T3B` / `JCID_T3B_` | `T3B` / `JCID_T3B_` (same) |
| Handle-type strings | `C115`, `C210` | `T115` |
| Bytes that differ | ~84%: separately compiled builds, not a rename | |

The screen shows "T3B" with **either** firmware, so it tells you nothing.
By analogy with the T3A/T3AS (where the "S" firmware targets a GD32F305/307
board revision), the "S" variant may be a different board revision. **Do not
cross-flash.** `t3xupdate.py` and `t3xupdate_safe.py` both refuse a product
mismatch.

---

## 3. Using the standalone scripts

Only `pyserial` is needed. In a clone of the repository:

```bash
python3 -m venv venv
# a private Python environment in the clone (system pip is blocked on Kali and recent Debian)

venv/bin/python -m pip install pyserial
# the only dependency of the scripts

venv/bin/python t3x_probe.py --fw JC_M_T3BS_1.16.bin --reader-test 50
# READ-ONLY full pre-flash check; do not flash unless every line shows [PASS]

venv/bin/python t3xupdate_safe.py -d JC_M_T3BS_1.16.bin
# flash: prints a pre-flight summary and waits until you type yes
```

Serial-port permission and connecting the station: INSTALLATION.md §3 and §8.

| `t3x_probe.py` option | Description |
|---|---|
| `--fw FILE` | Offline file check (magic, size, CRC16, product, version, vector table), then compares the file's product with the station's |
| `--reader-test N` | Repeats each query N times with the **original updater's** `read(1)+read_all()` method and checks every reply is complete |
| `--hardware` | Opt-in: also sends `JC_hardware`, an undocumented query that looks read-only. Leave it out if unsure |
| `--port DEV` | Use a specific port instead of auto-detecting by USB serial number |
| `--repeat N` | Number of query rounds (default 3) |

The probe sends **only** `JC_identity` and `JC_version`; a whitelist in the code prevents anything else.
It never echoes the version string back, which is what triggers the bootloader. Exit code `0` = all checks
passed, `2` = at least one failed.

| `t3xupdate_safe.py` option | Description |
|---|---|
| `-d`, `--debug` | Show every TX/RX on screen (always written to the log file) |
| `--port DEV` | Use an explicit serial port |
| `--wait S` | Seconds to wait for the station to re-appear after a reset (default 20) |
| `--yes` | Skip the confirmation prompt |

A timestamped log `t3x_flash_YYYYMMDD_HHMMSS.log` is written for every run. It contains the station's USB
serial number: replace it before posting the log anywhere.

**What the safe updater changes compared with the original `t3xupdate.py`:**

| Change | Reason |
|---|---|
| Reads each reply until the line has been quiet for 100 ms | An ACK split across two USB packets can't be misread |
| Polls for up to `--wait` s after each reset instead of sleeping a fixed 3 s | Slow re-enumeration no longer causes "No T3x found" |
| Falls back to the single `0403:6001` device present if the serial number changes | Copes with a bootloader that enumerates under a different serial number |
| Magic, size, CRC16 **and a Cortex-M vector-table check** before any serial traffic | Rejects corrupt files or files for the wrong flash layout |
| Pre-flight confirmation + timestamped log | You can review the plan first, and diagnose a failure afterwards |
| Every error message says whether it is safe to re-run | Prevents a panicked power-off while the station is in the bootloader |

---

## 4. What is normal during a flash


| Message | Meaning |
|---|---|
| `Device dropped off USB (expected...)` after the version echo | **Normal.** The station is resetting into the bootloader. |
| Port changes, e.g. `ttyUSB0` → `ttyUSB1` | **Normal.** The kernel enumerates the device as a new tty. |
| `JC_boot` + a bootloader version string | **Normal.** On the test unit the bootloader reported `00160000JC_M_T3BS_version1.01`. |
| `Device dropped after last chunk` | **Normal.** The station restarts into the new firmware. |
| `RX ... after 150–200 ms` | **Normal.** This includes the 100 ms quiet-line wait. |
| `Product mismatch` | **Stop.** Wrong firmware variant (T3B vs T3BS). |
| `Bad ACK at chunk n/82` / `Device lost at chunk n/82` | See [Troubleshooting](#5-if-something-fails). **Do not power off.** |

---

## 5. If something fails

| Symptom | Action |
|---|---|
| `No T3x found` | Check `venv/bin/python -m serial.tools.list_ports -v`. Try a USB-A → USB-C data cable without a hub. Use `--port /dev/ttyUSB0`. |
| `Permission denied` on `/dev/ttyUSB*` | INSTALLATION.md §3 (serial-port group), then log out and back in |
| A probe check shows `[FAIL]` | Do not flash. Re-run the probe and investigate first. |
| `No update start ACK` | Nothing has been written yet. Re-running is safe. |
| Failure during the chunk transfer | **Do not power off or unplug.** The station stays in the bootloader. Re-run the same command; the script detects `JC_boot` and starts the transfer again. Keep the log file. |
| `station did not re-appear within 20 s` | Re-run, optionally with `--wait 60` or `--port /dev/ttyUSBx` |
| Rollback | Flash your saved older image. A one-step downgrade (T3BS 1.16 → 1.15) and the upgrade back were tested on real hardware in October 2026; larger downgrades have not been tested. |

The bootloader lives in its own flash region and is not touched by the update
(based on the T3A flash layout). This is why an interrupted transfer should be
recoverable by simply re-running. Note that the T3B has flash read protection
(RDP1), so SWD recovery is **not** a practical fallback: the bootloader is the
recovery path.

---

## 6. Technical notes

### Serial protocol (115200 8N1)

| Host sends | Station replies | Notes |
|---|---|---|
| `JC_identity` | `JC_User` (application) / `JC_boot` (bootloader) | Read-only |
| `JC_version` | `JC_M_T3BS_version1.06` | Read-only. The product is field 2 when split on `_`. |
| *the version string echoed back* | `JC_reset`, then a USB drop | **Enters the bootloader** |
| `JC_version` (in the bootloader) | `00160000JC_M_T3BS_version1.01` | The meaning of the 8-digit prefix is unknown. The updater strips it (`[8:]`). |
| `0x%08x<bootloader version string>` (file size + bootloader string) | `update_jcxx` | Starts the transfer |
| 2048-byte chunks of the **whole file, header included** | `ack_jcxx` per chunk | The last chunk is 256 bytes for these images |

Other command strings found in the firmware, all **unverified**, so do not
send them blindly: `JC_hardware` (probably a read query), `JC_reset`,
`syscfg -v`, `JC RW`, `JC DFU`, `JC_image` / `JC_image_end` / `image_start` /
`image_restart` (likely the custom boot-screen upload), `JCXX_open`.

### Update file format

| Offset | Content |
|---|---|
| `0x00` | `JCID` magic |
| `0x20` | Product string, e.g. `JC_M_T3BS` (padded with `0xFF`) |
| `0x40` | Firmware version, e.g. `1.16` (some T3A images use `version1.26`) |
| `0x60` | Payload size, big-endian (file size = value + 0x100) |
| `0x64` | CRC-16/MODBUS of the payload, big-endian |
| `0x100` | Plaintext Cortex-M image linked at `0x08010000` (not encrypted) |

Vector tables of the 1.16 images:
`T3BS`: SP `0x20005508`, Reset `0x08010165`.
`T3B`: SP `0x20005218`, Reset `0x08010145`.

### Hardware / flash layout

These details are documented for the T3A in
[aixun_t3a_rev](https://github.com/c0d3z3r0/aixun_t3a_rev) and are assumed,
not verified, to be similar for the T3B:

- MCU: GD32F303 (STM32F103-class clone); the USB FTDI interface is emulated
- Bootloader at `0x0000`; main firmware at `0x10000`, maximum `0x2E800` bytes;
  boot-screen image, settings, device-ID HMAC and signature in separate regions
- T3B: read protection (RDP1) enabled

### Relevant firmware changelog entries (T3B and T3BS are identical)

| Firmware | Change |
|---|---|
| 1.15 (2023-12-20) | New "neural network" temperature-control algorithm; new curve screen |
| 1.13 (2023-04-08) | Optimised 210 heating control |
| 1.08 (2022-10-25) | Fixed USB driver compatibility issues |
| 1.16 (2024-06-25) | Release 1.16 |

Full list: <https://aixun-updates.github.io/>

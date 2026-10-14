# Session 02b: Station plugged in after the GUI was started

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | First GUI test on the Pi. Station connected **before** starting the GUI: found correctly. Station plugged in **after** starting it: "the GUI freezes", Rescan and the port list unusable for a long time |
| Outcome | Reproduced in the simulator; the GUI now waits for a new station to settle, retries a silent or busy port by itself, never locks Rescan/port selection during a probe, and shows live progress. **65 passed** |
| Wire bytes changed? | No for a station that answers (golden tests pass). A silent station now receives **one** `JC_identity` instead of 26 queries |

## 1. What was happening

The window was not hung: all serial I/O already ran in a worker thread. But the GUI behaved as if it was:

| # | Cause in the session-02 code |
|---|---|
| 1 | The auto-probe started **as soon as the port appeared** (≤ 1 s poll) |
| 2 | Rescan, the port list and "Probe again" were **disabled for the whole probe** |
| 3 | The probe ran all its queries even when the station did not answer: 6 queries + 20 reader-test queries, each waiting up to **3 s** for a first byte, so up to about **80 s** with everything disabled |
| 4 | The result (empty identity) was then shown as a finished report, so **no automatic retry** happened; only "Probe again" helped |

Why only after plugging in: something makes the first seconds on USB silent or busy. With the station plugged in before starting the GUI, those seconds were already over.

| Candidate | Evidence | Status |
|---|---|---|
| The station's USB-serial bridge (GD32) enumerates before its firmware answers | Common for MCU-emulated USB-serial | Unverified |
| ModemManager opens new serial ports to look for modems (sends AT commands, can hold the port a few seconds) | Typical on Debian/Kali desktops | Unverified; check commands in WORKFLOW §10 |
| The Raspberry Pi itself | Nothing points at it | Unlikely |

The fix does not depend on which one it is.

## 2. Reproduction (simulator)

New simulator features: `SimStation.start(attached=False)`, `plug(wake_delay=…)`, `unplug()`. `wake_delay` keeps the station on USB but silent.

| Run (session-02 GUI, GUI defaults, station silent for its first 4 s) | Result |
|---|---|
| Controls while probing | Rescan and port list **disabled** |
| End of probe | After 9.4 s, identity `b''`, "Continue" disabled |
| 5 s later | Still `b''`: no retry |

## 3. Fix

| Where | Change |
|---|---|
| `core/probe.py` | `run_probe` **fails fast**: no reply to the first query → `NoReply` after one timeout. Opening errors → `PortUnavailable`. Cancellable between and **inside** queries (`cancelled`), so a cancel takes effect within a few milliseconds (the reader test's `read(1)` can still take up to 3 s if the station falls silent mid-test). `on_progress(done, total)` after each query. `ProbeSession(cancelled=…)` |
| `gui/workers.py` | `ProbeJob.cancel()` and a `progress` signal |
| `gui/window.py` | A new station must be on USB for **1.5 s** (`settle_s`) before the auto-probe. `NoReply`/`PortUnavailable` within **30 s** (`wake_window_s`) of the port appearing → retry every 1.5 s with "Station on USB but not answering yet · trying again (attempt n)…" or "Port busy (another program has it open) · …". Rescan, port list and "Probe again" stay **enabled**: using them cancels the running probe and starts a new one; choosing a port in the list now probes it. Unplugging during a probe cancels it. Line 2 shows "n/26 queries answered". After 30 s without an answer: an error with what to check. Flash and Recovery buttons stay off while a probe runs. Closing the window stops a running probe cleanly |
| `cli/probe.py` | Same open error handled; hint to wait a few seconds after plugging in |
| `docs/WORKFLOW.md` | Troubleshooting row; ModemManager check (read-only commands) and an **optional** udev rule, clearly marked as the only system-wide change |

## 4. Tests added (7)

| Test | Checks |
|---|---|
| `test_gui::test_station_plugged_in_after_start` | GUI first, station plugged later and silent for 4 s: controls usable during the probe; found without user action in < 15 s |
| `test_gui::test_rescan_cancels_a_running_probe` | Rescan during a probe against a silent station takes effect in < 2 s |
| `test_gui::test_port_busy_right_after_plugging_is_retried` | Port open fails twice with EBUSY (as when another program holds it): "busy" shown, third attempt succeeds |
| `test_gui::test_unplug_during_probe_then_replug` | Probe stops, back to "No AiXun station"; replug → found |
| `test_probe::test_silent_station_fails_fast_after_one_query` | `NoReply` in < 5 s; only `JC_identity` sent |
| `test_probe::test_probe_can_be_cancelled_mid_query` | Cancel during a 3 s wait returns in < 1.5 s |
| `test_probe::test_progress_counts_every_query` | Progress 1…10 of 10 |

## 5. Verification

| Check | Result |
|---|---|
| Full suite | **65 passed** (58 + 7) |
| Same scenario against the session-02 window code (scratch run, §2) | Controls locked, empty result, no retry: matches the Pi |
| Golden tests | Pass: same traffic for an answering station |
| GUI defaults, station silent for 6 s after plugging in (rendered offscreen) | Retry message at 6.0 s, station found at **11.1 s**; Rescan enabled throughout |

## 6. Open

| ID | Item |
|---|---|
| L14 | Root cause of the silent/busy first seconds on the Pi not confirmed (station firmware vs ModemManager). The GUI copes either way; the WORKFLOW commands tell them apart |

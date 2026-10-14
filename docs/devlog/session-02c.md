# Session 02c: Verifying manually selected firmware

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | User: "I do not see the option to do the verification on a manually-selected firmware. This is risky" |
| Outcome | Checks were already running on manual files, but the page didn't show which file they were for, and a **confirmation tick carried over to a different file**. Both fixed; downgrades flagged; **66 passed** |
| Wire bytes changed? | No |

## 1. What was already in place (verified, not assumed)

Scripted run against the simulator with four files added through **Add file…** from a folder outside `firmware/`:

| File added | Failing checks | Flash enabled |
|---|---|---|
| Valid T3BS image | none | yes (see §2) |
| Valid **T3B** image | Product match | no |
| T3BS image with one byte changed | CRC16 | no |
| `junk.bin` (5 bytes) | Image header (JCID), Product match | no |

Defence in depth already present:

| Layer | What it does |
|---|---|
| Verify page | Every selection (library row or Add file…) recomputes header, size, CRC, vector table and product match; "Flash firmware" needs all PASS + the tick |
| Flash engine (`Flasher._load`) | Re-validates the same image before opening the port; an invalid image sends nothing |
| Bytes sent = bytes checked | The image is read once into memory; the checks and the transfer use that copy, so changing the file on disk after Verify has no effect |

## 2. Gaps found and fixed

| # | Gap | Fix |
|---|---|---|
| 1 | **The tick carried over.** Tick the box for image A, then select image B: "Flash firmware" was enabled immediately for B | Any change of selected file (path or content, compared by SHA-256) clears the tick |
| 2 | The checks table didn't say which file it described | Line above the table: "Checks for: name · size · SHA-256 …"; full path and hash in the tooltip. Compare the hash with a trusted source if one is published |
| 3 | A downgrade looked like any other compatible image | Library status "⚠ downgrade" (amber); banner "DOWNGRADE x → y: older firmware may read the newer one's settings differently (unverified); check settings and temperature afterwards" |

Banner wording shortened so all ten checks stay visible at the default window size (checked in a rendered screenshot).

## 3. Tests

| Test | Checks |
|---|---|
| `test_gui::test_manually_added_files_are_checked_and_confirmation_resets` | The four files above; tick cleared on change; file name and SHA-256 shown; downgrade banner |

Full suite: **66 passed**.

## 4. Offline check without the GUI

`./aixun run t3x-image info firmware/FILE.bin` runs the same image checks from the command line, and `./aixun probe FILE.bin` adds the product match against the connected station (read-only).

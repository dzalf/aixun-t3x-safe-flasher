# Session 01c: Workspace corrections from the first real setup

| | |
|---|---|
| Date | 2026-10-11 |
| Trigger | First `setup` on the Pi (Kali, Python 3.14.7). It succeeded, but in a nested layout; it gave no progress feedback; and the docs had wrong assumptions |
| Outcome | Layout check, visible progress, path-agnostic docs, firmware listed as a prerequisite, zip top folder renamed to `project` |
| Code changes to the updater | None |

## 1. What happened on the Pi

The zip was extracted *into* `aixun/project/`, giving `aixun/project/aixun_t3x_safe_updater_and_probe/`. The script derives the workspace root from its own location, so the root silently became `aixun/project/`:

```
aixun/project/                          <- treated as the workspace root
├── aixun_t3x_safe_updater_and_probe/   <- the code (git repo, baseline commit OK)
├── venv/  firmware/  results/  deliveries/  aixun
```

Everything installed correctly (venv on Python 3.14.7, pyserial loaded **from the venv**), just one level deeper than intended.

## 2. Root causes (documentation and tooling, not the user)

| # | Cause |
|---|---|
| C1 | The bootstrap relied on a manual rename (`mv …/aixun_t3x_safe_updater_and_probe project`); extracting straight into `project/` is an obvious alternative that the script did not detect |
| C2 | The docs hard-coded `~/aixun` and `~/Downloads`, although the workspace can live anywhere |
| C3 | Firmware images were used (`cp …/*.bin firmware/`) but never listed as a prerequisite: which files, what for, whether required, where to get them |
| C4 | `pip install -q` hid all progress; setup looked frozen for minutes on the Pi |

## 3. Fixes

| Cause | Fix |
|---|---|
| C1 | (a) Zips now have **`project/` as their top folder**: `unzip -q X.zip -d .` inside the workspace creates the right layout, no rename. (b) `setup` checks the layout: it stops (non-interactive) or asks (interactive) when the code folder isn't called `project`, or when the workspace root itself is called `project`. Override: `AIXUN_ALLOW_LAYOUT=1` |
| C2 | WORKFLOW uses `WS=/path/of/your/choice/aixun`; no home-directory assumptions remain |
| C3 | New WORKFLOW §2 "Before you start": items needed, with what each is for; a firmware table (target image, rollback image, optional pair for the real-image test); how to find your product line |
| C4 | Steps numbered `[1/5]…[5/5]`; pip runs with its normal output (Collecting / Downloading / Installing); a note that it takes a few minutes on a Pi |

## 4. Verification

| Case | Result |
|---|---|
| Correct bootstrap with the new zip | Steps 1–5 shown with pip progress; `test tests/test_image.py`: 13 passed, 1 skipped ✅ |
| New zip extracted into `project/` (→ `project/project`) | **First attempt of the check missed this** (it only looked at the folder name); fixed to also reject a root called `project`. Now stops, nothing created ✅ |
| Old zip extracted into `project/` (the Pi case) | Stops, nothing created ✅ |
| Interactive, answer "n" | "stopped; nothing was changed" ✅ |
| `shellcheck -S warning` | Clean ✅ |

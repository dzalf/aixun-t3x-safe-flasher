# Changelog

All notable changes. Dates are when the change was validated. Development detail per session is in
[docs/devlog/](docs/devlog/); the integrated record is [docs/DEVELOPMENT_REPORT.md](docs/DEVELOPMENT_REPORT.md).

## Unreleased

### Documentation
- ROADMAP.md: planned work, where help is wanted, good first issues, what is out of scope.
- README: folder structure of the repository and of the workspace.
- docs/MAINTAINERS.md rewritten: explicit commands with full paths, personal access token (permissions, error
  messages), commit identity, everyday pushes, releases.
- DEVELOPMENT_REPORT: L11 closed; feature backlog moved to ROADMAP.md.

## 0.1.0 — 2026-10-14 (first release of this repository)

Hardware-validated: T3BS 1.16 → 1.15 → 1.16 (GUI, twice) on a Raspberry Pi 5 / Kali Linux.

### Added
- `t3x` Python package: UI-free engine (`core/`), simulator, command-line tools
  (`t3x-probe`, `t3x-update`, `t3x-image`, `t3x-online`, `t3x-history`) and a PySide6 GUI (`t3x-gui`)
  with Connect / Verify / Flash / Done / Recovery pages.
- Read-only probe with a whitelist that makes entering the bootloader impossible.
- Image checks (header, size, CRC-16/MODBUS, vector table, product, version) before any traffic;
  product check also in bootloader mode.
- Recovery: detection of a station waiting in its bootloader, last-log summary, resume.
- Firmware online: version list from aixun-updates.github.io (data host read from the site's own
  `config.js`), downloads checked and compared with a second address, provenance records, local
  comparison, saved list with revalidation, IPv4-first connections with short timeouts, gzip.
- Flash history (`results/history.jsonl`), import of earlier flash logs, GUI history window.
- Flash page: chunk map, live speed and time left (seeded from history).
- Downgrade warnings (GUI and CLI), ModemManager notice, opt-in "newer version listed" notice.
- Self-contained workspace manager `tools/aixun.sh` (`./aixun`): setup, test, probe, flash, gui,
  online, history, apply/accept/rollback of zip deliveries, reinstall (offline-aware), status,
  check-publish. Distribution-aware hints (apt, dnf, zypper, pacman).
- 104 tests, including byte-for-byte equivalence with the hardware-proven script and headless GUI tests.
- INSTALLATION.md, CONTRIBUTING.md, GitHub issue/PR templates and a test workflow.

### Compared with the earlier console scripts ([dzalf/aixun_t3x_safe_updater_and_probe](https://github.com/dzalf/aixun_t3x_safe_updater_and_probe))
- `t3x_probe.py` and `t3xupdate_safe.py` are included as wrappers around the package
  (same behaviour and wire bytes; no `crcmod` needed).
- The original `t3xupdate.py` is kept, unchanged, in `tests/reference/t3xupdate_upstream.py` as a byte-level reference.
- The script-based guide is in `docs/SCRIPTS_GUIDE.md`.

### Fixed (compared with the October 2026 scripts)
- `termios.error` (EIO) when the station drops off USB at the two planned resets is handled as the
  expected disconnect instead of crashing.

## Before this repository

- 2026-10-09: console scripts `t3x_probe.py` (read-only probe) and `t3xupdate_safe.py` (hardened updater)
  published in [dzalf/aixun_t3x_safe_updater_and_probe](https://github.com/dzalf/aixun_t3x_safe_updater_and_probe);
  first hardware flash T3BS 1.06 → 1.16 on 2026-10-08.

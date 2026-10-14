---
name: Hardware report
about: Report a probe or flash on a real station (works or not); this is how support grows
labels: hardware
---

| | |
|---|---|
| Station (sticker / model) | |
| Product and version reported by the probe | |
| Bootloader string (from the flash log, if any) | |
| Host (board, distribution, Python version) | |
| Tool and version (`./aixun status`, GUI or CLI) | |
| What you did (probe / re-flash / upgrade / downgrade) | |
| Result | |

**Attachments** (replace the USB serial number first):
- `results/probe_*.json`
- `results/t3x_flash_*.log` (if you flashed)
- `results/pytest_*.txt` (if you ran the tests)

# Session 03a: Slow online list on the Pi

| | |
|---|---|
| Date | 2026-10-12 |
| Trigger | `./aixun online list --product T3BS` on the Pi: correct result (T3BS 1.08–1.16, data host `usr.tnyzeq.icu` read from the site's `config.js`), but it "took absolute ages" |
| Outcome | Connection, compression and a saved copy of the list; **96 passed** (+6) |

## 1. Measurements on the Pi (curl)

| Request | Result |
|---|---|
| `config.js` from aixun-updates.github.io | 66 B, connect 0.04 s, total 0.08 s |
| `changelog.json`, **IPv4 only** (`curl -4`) | 652,284 B, connect 0.04 s, first byte 0.97 s, total **1.4 s** |
| `changelog.json`, compressed (`--compressed`) | 104,795 B on the wire, total **0.4 s** |

The server and the network are fast. curl was fast even without `-4` because it tries IPv4 and IPv6 in parallel. Python's default connector tries a host's addresses **one after another**, each with the full timeout (20 s here). Where IPv6 is advertised but doesn't work, every request waits that long before falling back to IPv4. This is the most likely cause; it is **not yet confirmed** on the Pi (the new `-v` option shows which address family each request used).

## 2. Fix

| Change | Effect |
|---|---|
| IPv4 addresses first, 4 s connect timeout per address (`_connect_ipv4_first`, used through custom `HTTPConnection`/`HTTPSConnection` classes) | A dead route costs ≤ 4 s once instead of 20 s per address |
| `Accept-Encoding: gzip`, decoded with a size limit | 652 KB → ~105 KB per list |
| Saved list in the workspace (`results/online/changelog.json` + `.meta.json`) | Re-checked with `If-None-Match`/`If-Modified-Since` when the server gives validators (a 304 costs one tiny request); otherwise reused for 6 h; also used when offline, with a note saying so. `--refresh` / **Refresh list** reads it again |
| `-v` on `list`/`get`/`compare`; costs shown in the GUI dialog | Size, compressed size, time and IPv4/IPv6 per request |

Every request still starts with `config.js` from aixun-updates.github.io, so a change of data host is noticed immediately.

## 3. Tests added (6)

`test_gzip_is_requested_and_decoded`, `test_saved_list_with_etag_is_revalidated`, `test_saved_list_without_validators_is_reused_for_hours`, `test_saved_list_is_used_when_offline`, `test_dead_address_costs_seconds_not_minutes` (first address non-routable, 0.5 s connect timeout: answer in < 3 s), `test_ipv4_is_tried_first`.

## 4. Also from this run

| Item | Status |
|---|---|
| L18: online catalogue against the live site | **Closed**: the list parsed correctly on the Pi |
| `apply` needs the internet even when dependencies haven't changed (pip downloads its build tool); a DNS outage on the Pi stopped it before the venv refresh | Open: session 04 |

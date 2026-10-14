# Session 00: Probe, hardened updater and first hardware flash (baseline)

| | |
|---|---|
| Dates | 2026-10-08 to 2026-10-09 |
| Goal | Update a T3B-labelled AiXun station from Linux after the Windows driver route failed |
| Outcome | **Flashed on hardware**: T3BS 1.06 → 1.16, 82/82 chunks, version read back |
| Host | Raspberry Pi 5, Kali Linux, pyserial, `ftdi_sio` |

This entry records the work done before the package existed. Its scripts are the reference that every later session is tested against.

## Findings

| Finding | Evidence |
|---|---|
| Windows: the current FTDI driver rejects the station (Code 10). Older drivers are blocked by Memory Integrity, then by signature checks (Code 52) | Device Manager; Microsoft support page for Memory Integrity |
| The station's USB interface is emulated by its MCU (`0403:6001`, bcdDevice `0x0400`, serial prefix compiled into the firmware) | Hardware IDs; `JCID_T3B_` string inside both firmware images |
| Linux `ftdi_sio` accepts it as `/dev/ttyUSB0` | `t3x_probe.py` output |
| A T3B sticker, T3B stand and "T3B" on screen, but the station reports `JC_M_T3BS_version1.06`; its bootloader reports `JC_M_T3BS` | Probe and flash logs |
| T3B and T3BS 1.16 images: same size, different builds (~84% of bytes differ; `C115`/`C210` vs `T115`) | Byte and string comparison |
| Images are unencrypted Cortex-M code linked at `0x08010000`; header CRC is CRC-16/MODBUS | Vector tables; CRC check |
| The upstream reader (`read(1)+read_all()`) returned complete replies 100/100 on this unit | `--reader-test 50` |

## Deliverables

- `t3x_probe.py`: read-only probe with a command whitelist, USB/sysfs details, a reader test, offline image checks and vector-table validation.
- `t3xupdate_safe.py`: the same wire protocol as upstream `t3xupdate.py`, with idle-based reads, reconnect polling with a `0403:6001` fallback, a timestamped log, pre-flight confirmation and image checks.
- README for the fork, with the commands and the real outputs.

## Hardware result (2026-10-08)

```
Station : T3BS v1.06 (JC_User)        File : T3BS v1.16 (166144 bytes, 82 chunks)
Device dropped off USB (expected)     -> re-enumerated as /dev/ttyUSB1
Bootloader version string: b'00160000JC_M_T3BS_version1.01'
TX b'0x00028900JC_M_T3BS_version1.01' -> update_jcxx
82 chunks, each ack_jcxx; USB drop after the last one (expected)
After flash: JC_User, JC_M_T3BS_version1.16 -> Update successful
```

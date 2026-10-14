# SPDX-License-Identifier: GPL-2.0-or-later
"""End-to-end flasher behaviour against the simulated station."""
import logging

import pytest

from conftest import make_image
from t3x.core import events as ev
from t3x.core import image as fw
from t3x.core.flasher import Flasher
from t3x.core.link import SerialLink, Timing
from t3x.core.logfile import LogSink, file_handler, parse_log
from t3x.sim import Scenario, SimStation

QUERIES = {b"JC_identity", b"JC_version"}


def flash(sim, img, confirm=lambda pf: True, wait=5, **kw):
    events = []
    link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=wait, emit=events.append)
    r = Flasher(img, link, emit=events.append, confirm=confirm, **kw).run()
    return r, events


@pytest.fixture
def t3bs():
    return fw.parse_bytes(make_image(payload=20 * 2048 + 256))     # 21 chunks: quick


def test_success_and_events(t3bs):
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        r, events = flash(sim, t3bs)
    assert r.ok and r.stage == ev.Stage.DONE and r.chunks_acked == 21
    assert sim.version == b"1.16" and sim.flashed == t3bs.data
    assert r.after.version == b"1.16" and r.bootloader.raw == b"00160000JC_M_T3BS_version1.01"
    stages = [e.stage for e in events if isinstance(e, ev.StageEvent)]
    assert stages == [ev.Stage.LOAD, ev.Stage.CONNECT, ev.Stage.PREFLIGHT, ev.Stage.CONFIRM,
                      ev.Stage.BOOTLOADER, ev.Stage.START, ev.Stage.TRANSFER, ev.Stage.VERIFY, ev.Stage.DONE]
    prog = [e.index for e in events if isinstance(e, ev.ProgressEvent)]
    assert prog == list(range(1, 22))
    assert sim.enumerations == 3       # initial, bootloader, new firmware


def test_abort_sends_only_queries(t3bs):
    with SimStation(Scenario()) as sim:
        r, _ = flash(sim, t3bs, confirm=lambda pf: False)
    assert r.stage == ev.Stage.ABORTED and not r.ok and not r.wrote_anything
    assert set(sim.frames) <= QUERIES and sim.version == b"1.06"


def test_product_mismatch_refused_before_any_write():
    t3b = fw.parse_bytes(make_image(product=b"T3B", payload=4096))
    with SimStation(Scenario()) as sim:
        r, _ = flash(sim, t3b)
    assert not r.ok and "Product mismatch" in r.message
    assert set(sim.frames) <= QUERIES


def test_bootloader_product_mismatch_refused():
    t3b = fw.parse_bytes(make_image(product=b"T3B", payload=4096))
    with SimStation(Scenario(start_in_bootloader=True)) as sim:
        r, _ = flash(sim, t3b)
    assert not r.ok and "bootloader" in r.message and set(sim.frames) <= QUERIES


def test_bootloader_without_product_needs_override(t3bs):
    sc = Scenario(start_in_bootloader=True, bootloader_string=b"00160000JCBOOT")
    with SimStation(sc) as sim:
        r, _ = flash(sim, t3bs)
        assert not r.ok and "allow-unknown-product" in r.message
        r2, _ = flash(sim, t3bs, allow_unknown_product=True)
    assert r2.ok


def test_interrupted_transfer_then_recovery(t3bs, tmp_path):
    with SimStation(Scenario(fail_at_chunk=8, reenum_delay=0.05)) as sim:
        log = logging.getLogger("t3x-test-recovery")
        log.setLevel(logging.DEBUG)
        log.handlers[:] = [file_handler(str(tmp_path / "t3x_flash_1.log"))]
        r, _ = flash_with_log(sim, t3bs, log)
        assert not r.ok and "Device lost at chunk 8/21" in r.message and r.wrote_anything
        assert sim.mode == "boot"                       # station waits in the bootloader
        s = parse_log(str(tmp_path / "t3x_flash_1.log"))
        assert s.outcome == "interrupted" and s.chunks_acked == 7 and s.n_chunks == 21
        assert s.describe() == "stopped at chunk 8/21 (device lost)"
        sim.sc.fail_at_chunk = None                     # second attempt succeeds
        r2, _ = flash(sim, t3bs)
    assert r2.ok and sim.version == b"1.16"
    assert r2.preflight.in_bootloader


def flash_with_log(sim, img, logger):
    sink = LogSink(logger)
    link = SerialLink(port_lister=sim.port_lister, timing=Timing.fast(), wait=5, emit=sink)
    return Flasher(img, link, emit=sink).run(), None


def test_bad_ack(t3bs):
    with SimStation(Scenario(bad_ack_at_chunk=3)) as sim:
        r, _ = flash(sim, t3bs)
    assert not r.ok and "Bad ACK at chunk 3/21" in r.message


def test_no_start_ack_writes_nothing(t3bs):
    with SimStation(Scenario(no_start_ack=True, reenum_delay=0.05)) as sim:
        r, _ = flash(sim, t3bs)
    assert not r.ok and "No update start ACK" in r.message and not r.wrote_anything


def test_verify_detects_station_not_back_in_app(t3bs):
    with SimStation(Scenario(verify_comes_back_in_boot=True, reenum_delay=0.05)) as sim:
        r, _ = flash(sim, t3bs)
    assert not r.ok and r.stage == ev.Stage.FAILED and "Could not confirm" in r.message


def test_split_replies_and_reset_ack(t3bs):
    with SimStation(Scenario(split_replies=True, reset_ack=True, ack_last_chunk=True,
                             reenum_delay=0.05)) as sim:
        r, _ = flash(sim, t3bs)
    assert r.ok


def test_slow_reenumeration_is_waited_for(t3bs):
    with SimStation(Scenario(reenum_delay=1.5)) as sim:
        r, _ = flash(sim, t3bs, wait=5)
    assert r.ok


def test_station_never_returns_times_out(t3bs):
    with SimStation(Scenario(reenum_delay=30)) as sim:
        r, _ = flash(sim, t3bs, wait=1)
    assert not r.ok and r.fatal and "did not re-appear" in r.message


def test_same_version_flagged():
    img = fw.parse_bytes(make_image(version=b"1.06", payload=4096))
    seen = {}
    with SimStation(Scenario()) as sim:
        flash(sim, img, confirm=lambda pf: seen.setdefault("same", pf.same_version) and False)
    assert seen["same"] is True


def test_forced_port_survives_reenumeration(t3bs):
    """--port /dev/ttyUSB0 must not time out when the bootloader appears as a new tty."""
    with SimStation(Scenario(reenum_delay=0.05)) as sim:
        first = sim.device
        events = []
        link = SerialLink(port=first, port_lister=sim.port_lister, timing=Timing.fast(), wait=5,
                          emit=events.append)
        r = Flasher(t3bs, link).run()
        assert first.endswith("ttyUSB0") and sim.device.endswith("ttyUSB2")
        assert r.ok and sim.enumerations == 3
        followed = [e.message for e in events if isinstance(e, ev.LogEvent) and "following serial" in e.message]
        assert len(followed) == 2       # bootloader entry and after the flash

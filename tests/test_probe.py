# SPDX-License-Identifier: GPL-2.0-or-later
import threading
import time

import pytest

from conftest import make_image
from t3x.core import image as fw
from t3x.core.probe import (NoReply, NotAllowed, ProbeCancelled, ProbeSession, find_station,
                            run_probe)
from t3x.sim import Scenario, SimStation


def test_probe_reports_station_and_sends_only_queries():
    img = fw.parse_bytes(make_image())
    with SimStation(Scenario()) as sim:
        p = find_station(port_lister=sim.port_lister)
        rep = run_probe(p, repeat=3, reader_test=10, image=img, listen_s=0.2)
    assert rep.ok, [c for c in rep.checks() if not c.ok]
    assert rep.identity == b"JC_User" and rep.version.product == b"T3BS" and rep.version.version == b"1.06"
    assert set(sim.frames) == {b"JC_identity", b"JC_version"} and sim.mode == "app"
    assert len(rep.checks()) == 8


def test_echo_of_version_string_is_refused():
    with SimStation(Scenario()) as sim:
        with ProbeSession(sim.device) as s:
            with pytest.raises(NotAllowed):
                s.query(b"JC_M_T3BS_version1.06")
            with pytest.raises(NotAllowed):
                s.query(b"JC_hardware")
    assert sim.frames == [] and sim.mode == "app"


def test_hardware_query_is_opt_in():
    with SimStation(Scenario(hardware_reply=b"JC_M_T3BS_hardware_1.00")) as sim:
        p = find_station(port_lister=sim.port_lister)
        rep = run_probe(p, repeat=1, allow_hardware=True, listen_s=0.1)
    assert rep.hardware == b"JC_M_T3BS_hardware_1.00"


def test_reader_test_catches_split_replies():
    """The upstream read(1)+read_all() reader truncates a reply that arrives in two parts."""
    with SimStation(Scenario(split_replies=True)) as sim:
        p = find_station(port_lister=sim.port_lister)
        rep = run_probe(p, repeat=1, reader_test=3, listen_s=0.1)
    assert rep.version.raw == b"JC_M_T3BS_version1.06"      # robust reader still complete
    assert rep.reader_mismatches and not rep.ok


def test_bootloader_station_fails_application_check_only():
    with SimStation(Scenario(start_in_bootloader=True)) as sim:
        p = find_station(port_lister=sim.port_lister)
        rep = run_probe(p, repeat=2, listen_s=0.1)
    failed = [c.name for c in rep.checks() if not c.ok]
    assert failed == ["Station in application mode (JC_User)"] and rep.version.product == b"T3BS"


def test_silent_station_fails_fast_after_one_query():
    """Session 02b: a station that is on USB but not answering yet (just plugged in) used to
    cost every query its full timeout (~80 s with the GUI's reader test). Now: one query."""
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        sim.plug(wake_delay=60)
        t0 = time.monotonic()
        with pytest.raises(NoReply, match="did not answer JC_identity"):
            run_probe(find_station(port_lister=sim.port_lister), repeat=3, reader_test=10, listen_s=0.2)
        assert time.monotonic() - t0 < 5
    finally:
        sim.stop()
    assert sim.frames == [b"JC_identity"]


def test_probe_can_be_cancelled_mid_query():
    stop = threading.Event()
    sim = SimStation(Scenario())
    sim.start(attached=False)
    try:
        sim.plug(wake_delay=60)
        threading.Timer(0.8, stop.set).start()
        t0 = time.monotonic()
        with pytest.raises(ProbeCancelled):
            run_probe(find_station(port_lister=sim.port_lister), listen_s=0.2, cancelled=stop.is_set)
        assert time.monotonic() - t0 < 1.5
    finally:
        sim.stop()


def test_progress_counts_every_query():
    seen = []
    with SimStation(Scenario()) as sim:
        run_probe(find_station(port_lister=sim.port_lister), repeat=2, reader_test=3, listen_s=0.1,
                  on_progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (10, 10) and [d for d, _ in seen] == list(range(1, 11))

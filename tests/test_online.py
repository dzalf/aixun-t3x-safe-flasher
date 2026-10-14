# SPDX-License-Identifier: GPL-2.0-or-later
"""Online catalogue against a local stand-in for aixun-updates.github.io (no internet needed)."""
import gzip
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import make_image
from t3x.cli import online as cli_online
from t3x.core import online


class FakeWeb:
    """Serves /site/assets/js/config.js, /data/files/changelog.json, /data/firmware/*, /vendor/*."""

    def __init__(self):
        self.files = {}
        self.hits = []
        self.gzip = False
        self.etag = None
        web = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                web.hits.append(self.path)
                body = web.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                extra = {}
                if web.etag and self.path.endswith("changelog.json"):
                    if self.headers.get("If-None-Match") == web.etag:
                        self.send_response(304)
                        self.end_headers()
                        return
                    extra["ETag"] = web.etag
                if web.gzip and "gzip" in (self.headers.get("Accept-Encoding") or ""):
                    body = gzip.compress(body)
                    extra["Content-Encoding"] = "gzip"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                for k, v in extra.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def site(self, catalog: dict, root_path="/data"):
        self.files["/site/assets/js/config.js"] = (
            "config = {\n\trootUrl: '" + self.base + root_path + "'\n}\n").encode()
        self.files[root_path + "/files/changelog.json"] = json.dumps(catalog).encode()

    def close(self):
        self.srv.shutdown()


T316 = make_image(version=b"1.16", payload=20 * 2048 + 256)
T315 = make_image(version=b"1.15", payload=20 * 2048 + 256, seed=5)


def entry(ver, fn, vendor=True, web=None):
    e = {"version": f"T3BS:{ver}", "time": "2024-06-25", "fileName": fn, "en_note": f"Release V{ver};",
         "ch_note": "", "fallbackSortKey": f"T3BS:{ver}"}
    if vendor and fn:
        e["url"] = f"{web.base}/vendor/{fn}"
    return e


@pytest.fixture
def web(monkeypatch):
    w = FakeWeb()
    w.site({"T3BS": [entry("1.15", "JC_M_T3BS_1.15.bin", web=w), entry("1.16", "JC_M_T3BS_1.16.bin", web=w),
                     entry("1.07", False, web=w)],
            "T3B": [], "Product_x": {}})
    for name, data in (("JC_M_T3BS_1.16.bin", T316), ("JC_M_T3BS_1.15.bin", T315)):
        w.files[f"/data/firmware/{name}"] = data
        w.files[f"/vendor/{name}"] = data
    monkeypatch.setenv("T3X_ONLINE_SITE", w.base + "/site")
    yield w
    w.close()


def test_catalog_follows_the_sites_own_config(web):
    cat = online.fetch_catalog()
    assert cat.root == web.base + "/data" and cat.data_host == "127.0.0.1"
    assert cat.products() == ["T3B", "T3BS"]                       # Product_* skipped like the site does
    es = cat.for_product("T3BS")
    assert [e.version for e in es] == ["1.16", "1.15", "1.07"]      # newest first
    assert es[0].mirror_url == web.base + "/data/firmware/JC_M_T3BS_1.16.bin"
    assert not es[2].downloadable                                   # fileName: false on the site


def test_get_saves_checked_file_with_provenance(web, tmp_path):
    cat = online.fetch_catalog()
    d = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert d.status == "saved" and d.cross_check == "match"
    assert open(d.path, "rb").read() == T316
    prov = json.load(open(d.path + ".source.json"))
    assert prov["downloaded_from"].endswith("/data/firmware/JC_M_T3BS_1.16.bin") and prov["sha256"] == d.sha256
    again = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert again.status == "already present"


def test_two_addresses_disagree_nothing_saved(web, tmp_path):
    web.files["/vendor/JC_M_T3BS_1.16.bin"] = T315
    cat = online.fetch_catalog()
    d = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert not d.ok and d.cross_check == "different" and os.listdir(tmp_path) == []


def test_second_address_unreachable_is_reported_not_fatal(web, tmp_path):
    del web.files["/vendor/JC_M_T3BS_1.16.bin"]
    cat = online.fetch_catalog()
    d = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert d.status == "saved" and d.cross_check.startswith("unavailable")


def test_no_cross_check_means_no_second_request(web, tmp_path):
    cat = online.fetch_catalog()
    online.download(cat.find("T3BS", "1.16"), str(tmp_path), cross_check=False, catalog=cat)
    assert not any(h.startswith("/vendor/") for h in web.hits)


@pytest.mark.parametrize("served,reason", [
    (b"<html>not found</html>", "fails the image checks"),
    (make_image(product=b"T3B", version=b"1.16", payload=4096), "is for T3B"),
    (T315, "is v1.15"),
])
def test_bad_downloads_are_refused(web, tmp_path, served, reason):
    web.files["/data/firmware/JC_M_T3BS_1.16.bin"] = served
    cat = online.fetch_catalog()
    d = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert not d.ok and reason in d.status and os.listdir(tmp_path) == []


def test_existing_different_file_is_never_overwritten(web, tmp_path):
    (tmp_path / "JC_M_T3BS_1.16.bin").write_bytes(b"mine")
    cat = online.fetch_catalog()
    d = online.download(cat.find("T3BS", "1.16"), str(tmp_path), catalog=cat)
    assert not d.ok and "already exists" in d.status
    assert (tmp_path / "JC_M_T3BS_1.16.bin").read_bytes() == b"mine"


def test_compare_local_files(web, tmp_path):
    (tmp_path / "JC_M_T3BS_1.16.bin").write_bytes(T316)
    (tmp_path / "JC_M_T3BS_1.15.bin").write_bytes(make_image(version=b"1.15", payload=20 * 2048 + 256, seed=9))
    (tmp_path / "JC_M_T3BS_1.14.bin").write_bytes(make_image(version=b"1.14", payload=4096))
    res = {r.version: r.result for r in online.compare_local(str(tmp_path), online.fetch_catalog(), "T3BS")}
    assert res == {"1.16": "matches the site", "1.15": "DIFFERENT from the site", "1.14": "not listed"}


def test_plain_http_data_host_is_refused(web):
    web.files["/site/assets/js/config.js"] = b"config = { rootUrl: 'http://example.com/x' }"
    with pytest.raises(online.OnlineError, match="not https"):
        online.fetch_catalog()


def test_offline_is_a_clean_error(monkeypatch):
    monkeypatch.setenv("T3X_ONLINE_SITE", "http://127.0.0.1:9")      # nothing listens there
    with pytest.raises(online.OnlineError):
        online.fetch_catalog()


def test_cli(web, tmp_path, capsys):
    def run(argv):
        with pytest.raises(SystemExit) as e:
            cli_online.main(argv)
        return e.value.code
    assert run(["list", "--product", "T3BS"]) == 0
    out = capsys.readouterr().out
    assert "Data host : 127.0.0.1" in out and "1.16    2024-06-25  JC_M_T3BS_1.16.bin" in out
    assert run(["get", "T3BS", "latest", "--dest", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "compared   : match" in out and "result     : saved" in out
    assert run(["compare", str(tmp_path), "--product", "T3BS"]) == 0
    assert "matches the site" in capsys.readouterr().out
    assert run(["get", "T3BS", "9.99", "--dest", str(tmp_path)]) == 2


def test_parses_the_real_sites_config_js():
    """Snapshot of assets/js/config.js from github.com/aixun-updates/aixun-updates.github.io
    (commit a6affd4, 2026-03-25). If the site changes its layout, this documents what we expected."""
    import io
    real = b"config = {\n\trootUrl: 'https://usr.tnyzeq.icu/~dd/aixun-updates'\n}\n"

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert online.discover_root("https://aixun-updates.github.io",
                                opener=lambda req, timeout: Resp(real)) == "https://usr.tnyzeq.icu/~dd/aixun-updates"
    assert online._version_of("T3BS:1.16") == "1.16" and online._version_of("T3A:v1.37") == "1.37"


def test_gui_online_dialog(web, tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_gui import make_window, probe_done, wait_until
    from t3x.sim import Scenario, SimStation
    app = QApplication.instance() or QApplication([])
    fwdir = tmp_path / "firmware"
    fwdir.mkdir()
    (fwdir / "JC_M_T3BS_1.16.bin").write_bytes(T316)                 # same bytes as the site's 1.16
    with SimStation(Scenario()) as sim:
        w = make_window(app, sim, str(fwdir), tmp_path)
        assert wait_until(app, lambda: probe_done(w))
        w.go_verify()
        w.verify_page.check_online()
        dlg = w.verify_page.online_dialog
        assert wait_until(app, lambda: dlg.catalog is not None and not dlg.busy, 15)
        t = dlg.table
        assert [t.item(r, 0).text() for r in range(t.rowCount())] == ["1.16", "1.15", "1.07"]
        assert t.item(0, 3).text().startswith("✔") and "matches the site" in t.item(0, 3).text()
        assert "byte-identical" in dlg.status.label.text() and "127.0.0.1" in dlg.source.text()
        t.selectRow(2)
        assert not dlg.get_btn.isEnabled()                              # 1.07: no file listed
        t.selectRow(1)
        assert dlg.get_btn.isEnabled()
        dlg.get_btn.click()
        assert wait_until(app, lambda: not dlg.busy and "saved" in dlg.status.label.text(), 15)
        assert (fwdir / "JC_M_T3BS_1.15.bin").read_bytes() == T315
        assert any(i.version_str == "1.15" for i in w.verify_page.images)    # library refreshed
        dlg.close()
        w.close()



def test_gzip_is_requested_and_decoded(web):
    web.gzip = True
    cat = online.fetch_catalog()
    f = [x for x in cat.fetches if x.url.endswith("changelog.json")][0]
    assert f.wire_bytes < f.bytes and f.peer.startswith("IPv4")
    assert [e.version for e in cat.for_product("T3BS")] == ["1.16", "1.15", "1.07"]


def test_saved_list_with_etag_is_revalidated(web, tmp_path):
    web.etag = '"v1"'
    c1 = online.fetch_catalog(cache_dir=str(tmp_path))
    assert c1.note == "downloaded now" and (tmp_path / "changelog.json").exists()
    c2 = online.fetch_catalog(cache_dir=str(tmp_path))
    assert c2.note.startswith("unchanged on the server") and c2.for_product("T3BS")[0].version == "1.16"
    assert [f.status for f in c2.fetches if f.url.endswith("changelog.json")] == [304]


def test_saved_list_without_validators_is_reused_for_hours(web, tmp_path):
    online.fetch_catalog(cache_dir=str(tmp_path))
    n = sum(h.endswith("changelog.json") for h in web.hits)
    c2 = online.fetch_catalog(cache_dir=str(tmp_path))
    assert "less than 6 h old" in c2.note and sum(h.endswith("changelog.json") for h in web.hits) == n
    c3 = online.fetch_catalog(cache_dir=str(tmp_path), refresh=True)
    assert c3.note == "downloaded now" and sum(h.endswith("changelog.json") for h in web.hits) == n + 1


def test_saved_list_is_used_when_offline(web, tmp_path, monkeypatch):
    online.fetch_catalog(cache_dir=str(tmp_path))
    monkeypatch.setenv("T3X_ONLINE_SITE", "http://127.0.0.1:9")      # site unreachable now
    cat = online.fetch_catalog(cache_dir=str(tmp_path))
    assert cat.note.startswith("offline") and cat.for_product("T3BS")[0].version == "1.16"


def test_dead_address_costs_seconds_not_minutes(web, monkeypatch):
    """A host whose first address never answers (as with broken IPv6) must fall through quickly."""
    real = socket.getaddrinfo
    port = int(web.base.rsplit(":", 1)[1])

    def fake(host, p, *a, **kw):
        if host == "slow.example":
            dead = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.255.255.1", p))   # non-routable
            return [dead] + real("127.0.0.1", p, *a, **kw)
        return real(host, p, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    monkeypatch.setattr(online, "CONNECT_TIMEOUT", 0.5)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    t0 = time.monotonic()
    body = online._get(f"http://slow.example:{port}/site/assets/js/config.js", 4096)
    assert b"rootUrl" in body and time.monotonic() - t0 < 3


def test_ipv4_is_tried_first(monkeypatch):
    seen = []

    class FakeSock:
        def __init__(self, af, *a):
            self.af = af

        def settimeout(self, t):
            pass

        def connect(self, sa):
            seen.append(self.af)
            raise OSError("refused")

        def close(self):
            pass

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 1, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1))])
    monkeypatch.setattr(socket, "socket", FakeSock)
    with pytest.raises(OSError):
        online._connect_ipv4_first(("x", 1), 5)
    assert seen == [socket.AF_INET, socket.AF_INET6]


@pytest.mark.parametrize("enabled", [True, False])
def test_newer_version_notice_is_opt_in(web, tmp_path, enabled):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from test_gui import make_window, probe_done, wait_until
    from t3x.gui.config import GuiConfig
    from t3x.sim import Scenario, SimStation
    app = QApplication.instance() or QApplication([])
    fwdir = tmp_path / "firmware"
    fwdir.mkdir()
    with SimStation(Scenario()) as sim:                      # station reports T3BS 1.06
        w = make_window(app, sim, str(fwdir), tmp_path, config=GuiConfig(update_notice=enabled))
        assert wait_until(app, lambda: probe_done(w))
        if enabled:
            assert wait_until(app, lambda: "1.16" in w.connect_page.update_note.label.text(), 10)
            assert "nothing is downloaded automatically" in w.connect_page.update_note.label.text()
        else:
            wait_until(app, lambda: False, 1.0)
            assert w.connect_page.update_note.label.text() == "" and web.hits == []
        w.close()

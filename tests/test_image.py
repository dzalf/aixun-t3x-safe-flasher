# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from conftest import make_image, real_fw
from t3x.core import image as fw
from t3x.core.crc import crc16_modbus
from t3x.core.protocol import parse_version, start_command


def test_crc_check_value():
    assert crc16_modbus(b"123456789") == 0x4B37     # CRC-16/MODBUS reference value


def test_crc_matches_crcmod_if_installed():
    crcmod = pytest.importorskip("crcmod")
    f = crcmod.mkCrcFun(0x18005, rev=True, initCrc=0xFFFF, xorOut=0x0000)
    data = make_image()[0x100:]
    assert f(data) == crc16_modbus(data)


def test_valid_image_layout():
    img = fw.parse_bytes(make_image())
    assert img.valid and img.product == b"T3BS" and img.version == b"1.16"
    assert img.size == 166144 and img.n_chunks == 82
    chunks = list(img.chunks())
    assert len(chunks) == 82 and len(chunks[-1][2]) == 256 and chunks[0][2][:4] == b"JCID"
    assert img.vector_text() == ("payload 165888 B (limit 190464) OK; SP 0x20005508 OK; "
                                 "Reset 0x08010165 OK")


def test_legacy_version_field():
    img = fw.parse_bytes(make_image(version=b"1.26", legacy_version=True))
    assert img.version == b"1.26"


@pytest.mark.parametrize("mutate,failing", [
    (lambda b: b"XXXX" + b[4:], "magic"),
    (lambda b: b + b"\x00", "size"),
    (lambda b: b[:-1] + bytes([b[-1] ^ 0xFF]), "crc"),
])
def test_corruption_detected(mutate, failing):
    img = fw.parse_bytes(mutate(make_image()))
    assert not img.valid
    assert not img.check(failing).ok
    with pytest.raises(fw.ImageError):
        fw.require_valid(img)


@pytest.mark.parametrize("kw", [dict(sp=0x10000000), dict(reset=0x08000000), dict(reset=0x08010164),
                                dict(payload=0x2E800 + 4)])
def test_vector_table_rejects_wrong_layout(kw):
    img = fw.parse_bytes(make_image(**kw))
    assert img.check("crc").ok and not img.check("vectors").ok
    with pytest.raises(fw.ImageError, match="main-firmware image"):
        fw.require_valid(img)


def test_scan_and_diff(tmp_path):
    (tmp_path / "a.bin").write_bytes(make_image(product=b"T3B", seed=2))
    (tmp_path / "b.bin").write_bytes(make_image(product=b"T3BS", version=b"1.06"))
    (tmp_path / "c.bin").write_bytes(make_image(product=b"T3BS", version=b"1.16"))
    (tmp_path / "junk.bin").write_bytes(b"nope")
    imgs = fw.scan_directory(str(tmp_path))
    assert [(i.product, i.version) for i in imgs if i.valid] == [
        (b"T3BS", b"1.16"), (b"T3BS", b"1.06"), (b"T3B", b"1.16")]
    valid = [i for i in imgs if i.valid]
    assert not imgs[-1].valid                       # junk.bin is listed, flagged invalid
    d = fw.diff_images(valid[0], valid[-1])
    assert d.same_size and d.differing_pct > 90


def test_protocol_parsing():
    app = parse_version(b"JC_M_T3BS_version1.06")
    assert (app.product, app.version, app.bootloader_prefix) == (b"T3BS", b"1.06", None)
    boot = parse_version(b"00160000JC_M_T3BS_version1.01")
    assert (boot.product, boot.version, boot.bootloader_prefix) == (b"T3BS", b"1.01", b"00160000")
    assert start_command(166144, boot.raw) == b"0x00028900JC_M_T3BS_version1.01"   # as logged on hardware


def test_real_images_match_session_findings():
    t3bs = fw.load(real_fw("JC_M_T3BS_1.16.bin"))
    t3b = fw.load(real_fw("JC_M_T3B_1.16.bin"))
    assert t3bs.valid and t3bs.crc_calc == 0x1EE0 and t3bs.reset_handler == 0x08010165
    assert t3b.valid and t3b.crc_calc == 0x02BD and t3b.reset_handler == 0x08010145
    d = fw.diff_images(t3b, t3bs)
    assert 80 < d.differing_pct < 90


def test_changelog_between():
    from t3x.core import changelog
    v = [e[0] for e in changelog.between("T3BS", "1.06", "1.16")]
    assert v[0] == "1.16" and v[-1] == "1.08" and "1.06" not in v and len(v) == 9
    assert changelog.between("T3BS", "1.16", "1.06") == []        # downgrade: nothing new
    assert changelog.between("T420D", "1.0", "2.0") == []

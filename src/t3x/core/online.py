# SPDX-License-Identifier: GPL-2.0-or-later
"""Firmware catalogue from aixun-updates.github.io (unofficial; read-only use).

How that site works (read from its own files, October 2026):

* https://aixun-updates.github.io/ is a static page. Its script
  assets/js/config.js names a data host ("rootUrl"); at the time of writing
  https://usr.tnyzeq.icu/~dd/aixun-updates.
* The page loads <rootUrl>/files/changelog.json: {product: [entry, ...]}, entry =
  {version: "T3BS:1.16", time, fileName, en_note, ch_note, url, ...}.
* The page's download link for an entry is <rootUrl>/firmware/<fileName>. That is
  where a .bin downloaded "from aixun-updates.github.io" actually comes from.
* `url` in each entry is a second address recorded by the site for the same file,
  on aixun-file.oss-cn-shenzhen.aliyuncs.com over plain http. The page does not
  show it. Its owner is not confirmed (the name suggests AiXun's own storage).
  Here it is used only to compare bytes, never as the sole source.

The data host is taken from the site's config.js on every run (not hard-coded),
so this tool always downloads from wherever the site itself links. No checksums
are published by the site; the image checks (header, size, CRC, vectors, product)
plus the optional two-address comparison are what this module can offer.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from . import image as fw

DEFAULT_SITE = "https://aixun-updates.github.io"
USER_AGENT = "t3x-safe-updater/0.1"
TIMEOUT = 20                     # reading a response
CONNECT_TIMEOUT = 4              # per address: a dead route (e.g. broken IPv6) costs seconds, not minutes
MAX_JSON = 8 * 1024 * 1024
MAX_IMAGE = 1024 * 1024          # T3x images are ~166 KB; anything near 1 MB is not one
CACHE_MAX_AGE = 6 * 3600         # reuse a saved list without asking the server, if it gave no validators


def site_url() -> str:
    """The site to read (T3X_ONLINE_SITE overrides it, e.g. for tests)."""
    return (os.environ.get("T3X_ONLINE_SITE") or DEFAULT_SITE).rstrip("/")


class OnlineError(Exception):
    pass


def _https_or_local(url: str, what: str) -> None:
    u = urllib.parse.urlparse(url)
    if u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost")):
        return
    raise OnlineError(f"{what} is not https: {url}")


# ------------------------------------------------------------------ transport
# Python's default connector tries each address of a host in turn with the full
# timeout. On networks where IPv6 is advertised but doesn't work, every request
# then hangs ~20 s per IPv6 address before falling back to IPv4 (curl avoids this
# with "happy eyeballs"). Here: IPv4 addresses first, and a short connect timeout
# per address. Responses are requested gzip-compressed (the catalogue is ~650 KB,
# ~105 KB compressed).
_peer = threading.local()


def _connect_ipv4_first(address, timeout=None, source_address=None, *args, **kwargs):
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)
    read_timeout = timeout if isinstance(timeout, (int, float)) else None
    last: Optional[OSError] = None
    for af, kind, proto, _canon, sa in infos:
        sock = socket.socket(af, kind, proto)
        try:
            sock.settimeout(min(CONNECT_TIMEOUT, read_timeout) if read_timeout else CONNECT_TIMEOUT)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            sock.settimeout(read_timeout)
            _peer.value = f"{'IPv4' if af == socket.AF_INET else 'IPv6'} {sa[0]}"
            return sock
        except OSError as e:
            last = e
            sock.close()
    raise last or OSError(f"no addresses for {host}")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_ipv4_first


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_ipv4_first


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(_HTTPHandler, _HTTPSHandler)


@dataclass
class Fetch:
    """What one request cost (shown with -v and in the GUI)."""
    url: str
    status: int
    wire_bytes: int
    bytes: int
    seconds: float
    peer: str = ""

    def describe(self) -> str:
        host = urllib.parse.urlparse(self.url).hostname
        if self.status == 304:
            return f"{host}: unchanged (304) in {self.seconds:.2f} s via {self.peer or '?'}"
        z = f", {self.wire_bytes:,} B compressed" if self.wire_bytes != self.bytes else ""
        return f"{host}: {self.bytes:,} B{z} in {self.seconds:.2f} s via {self.peer or '?'}"


FETCH_LOG: List[Fetch] = []            # requests of the current command (cleared by fetch_catalog)


def _get_full(url: str, limit: int, opener: Optional[Callable] = None,
              headers: Optional[Dict[str, str]] = None):
    """GET with gzip, size limit and stats. Returns (status, body, response headers)."""
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    t0 = time.monotonic()
    _peer.value = ""
    try:
        with (opener or _OPENER.open)(req, timeout=TIMEOUT) as r:
            raw = r.read(limit + 1)
            status = getattr(r, "status", 200) or 200
            rh = dict(getattr(r, "headers", {}) or {})
    except urllib.error.HTTPError as e:
        if e.code == 304:
            FETCH_LOG.append(Fetch(url, 304, 0, 0, time.monotonic() - t0, getattr(_peer, "value", "")))
            return 304, b"", dict(e.headers or {})
        raise OnlineError(f"{url}: HTTP {e.code} {e.reason}") from e
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise OnlineError(f"{url}: {getattr(e, 'reason', e)}") from e
    wire = len(raw)
    enc = {k.lower(): v for k, v in rh.items()}.get("content-encoding", "")
    if "gzip" in enc.lower():
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            body = d.decompress(raw, limit + 1)
        except zlib.error as e:
            raise OnlineError(f"{url}: bad gzip data ({e})") from e
        if len(body) > limit or d.unconsumed_tail:
            raise OnlineError(f"{url}: larger than {limit} bytes, refusing")
    else:
        body = raw
        if len(body) > limit:
            raise OnlineError(f"{url}: larger than {limit} bytes, refusing")
    FETCH_LOG.append(Fetch(url, status, wire, len(body), time.monotonic() - t0, getattr(_peer, "value", "")))
    return status, body, rh


def _get(url: str, limit: int, opener: Optional[Callable] = None) -> bytes:
    return _get_full(url, limit, opener)[1]


@dataclass
class Entry:
    product: str
    version: str
    date: str
    file_name: Optional[str]
    notes: str
    mirror_url: Optional[str]
    vendor_url: Optional[str]

    @property
    def downloadable(self) -> bool:
        return bool(self.file_name and self.mirror_url)


@dataclass
class Catalog:
    site: str
    data_host: str
    root: str
    fetched_at: str
    entries: Dict[str, List[Entry]] = field(default_factory=dict)
    note: str = ""                                   # where the list came from this time (network / saved copy)
    fetches: List[Fetch] = field(default_factory=list)

    def products(self) -> List[str]:
        return sorted(self.entries)

    def for_product(self, product: str) -> List[Entry]:
        return self.entries.get(product, [])

    def find(self, product: str, version: str) -> Optional[Entry]:
        return next((e for e in self.for_product(product) if e.version == version), None)


def discover_root(site: str = None, opener=None) -> str:
    site = (site or site_url()).rstrip("/")
    _https_or_local(site, "site")
    js = _get(site + "/assets/js/config.js", 64 * 1024, opener).decode("utf-8", "replace")
    m = re.search(r"rootUrl\s*:\s*['\"]([^'\"]+)['\"]", js)
    if not m:
        raise OnlineError(f"{site}/assets/js/config.js: no rootUrl found (site layout changed?)")
    root = m.group(1).rstrip("/")
    _https_or_local(root, "data host named by the site")
    return root


def _version_of(raw: str) -> str:
    m = re.match(r"^[A-Za-z0-9]+:v?([A-Za-z0-9.]+)$", raw or "")    # same rule as the site's app.js
    return m.group(1) if m else (raw or "?")


def parse_catalog(data: dict, site: str, root: str) -> Catalog:
    if not isinstance(data, dict):
        raise OnlineError("changelog.json: unexpected format")
    cat = Catalog(site, urllib.parse.urlparse(root).hostname or root, root,
                  time.strftime("%Y-%m-%d %H:%M:%S"))
    for product, items in data.items():
        if product.startswith("Product_") or not isinstance(items, list):
            continue
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            fn = it.get("fileName") if isinstance(it.get("fileName"), str) else None
            vendor = it.get("url") if isinstance(it.get("url"), str) else None
            out.append(Entry(product=product, version=_version_of(str(it.get("version", ""))),
                             date=str(it.get("time", "")), file_name=fn,
                             notes=str(it.get("en_note") or "").strip(),
                             mirror_url=f"{root}/firmware/{urllib.parse.quote(fn)}" if fn else None,
                             vendor_url=vendor))
        out.sort(key=lambda e: fw.version_key(e.version.encode()), reverse=True)
        cat.entries[product] = out
    return cat


def _cache_paths(cache_dir: str):
    return os.path.join(cache_dir, "changelog.json"), os.path.join(cache_dir, "changelog.meta.json")


def _load_cache(cache_dir: Optional[str]) -> Optional[dict]:
    if not cache_dir:
        return None
    data_p, meta_p = _cache_paths(cache_dir)
    try:
        with open(meta_p) as f:
            meta = json.load(f)
        with open(data_p, "rb") as f:
            meta["body"] = f.read()
        return meta if isinstance(meta, dict) and meta.get("root") else None
    except (OSError, ValueError):
        return None


def _save_cache(cache_dir: Optional[str], root: str, body: bytes, headers: dict) -> None:
    if not cache_dir:
        return
    os.makedirs(cache_dir, exist_ok=True)
    data_p, meta_p = _cache_paths(cache_dir)
    low = {k.lower(): v for k, v in headers.items()}
    meta = {"root": root, "saved": time.time(), "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "etag": low.get("etag"), "last_modified": low.get("last-modified")}
    for path, payload in ((data_p, body), (meta_p, json.dumps(meta, indent=2).encode())):
        fd, tmp = tempfile.mkstemp(dir=cache_dir, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp, path)


def _touch_cache(cache_dir: str, cache: dict) -> None:
    meta = {k: v for k, v in cache.items() if k != "body"}
    meta.update(saved=time.time(), saved_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(_cache_paths(cache_dir)[1], "w") as f:
        json.dump(meta, f, indent=2)


def _catalog_from(body: bytes, site: str, root: str, note: str) -> Catalog:
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError as e:
        raise OnlineError(f"changelog.json is not valid JSON: {e}") from e
    cat = parse_catalog(data, site, root)
    cat.note = note
    cat.fetches = list(FETCH_LOG)
    return cat


def fetch_catalog(site: str = None, opener=None, cache_dir: Optional[str] = None,
                  refresh: bool = False) -> Catalog:
    """The site's version list. With `cache_dir`, the last list is kept there: it is reused when
    the server says it hasn't changed (or, without validators, for 6 h), and when offline."""
    FETCH_LOG.clear()
    site = (site or site_url()).rstrip("/")
    cache = _load_cache(cache_dir)
    try:
        root = discover_root(site, opener)
    except OnlineError as e:
        if cache:
            return _catalog_from(cache["body"], site, cache["root"],
                                 f"offline ({e}); showing the list saved {cache.get('saved_at')}")
        raise
    url = root + "/files/changelog.json"
    if cache and cache["root"] == root and not refresh:
        validators = {}
        if cache.get("etag"):
            validators["If-None-Match"] = cache["etag"]
        if cache.get("last_modified"):
            validators["If-Modified-Since"] = cache["last_modified"]
        if not validators and time.time() - float(cache.get("saved", 0)) < CACHE_MAX_AGE:
            return _catalog_from(cache["body"], site, root, f"list saved {cache.get('saved_at')} "
                                 "(less than 6 h old; refresh to read it again)")
        try:
            status, body, headers = _get_full(url, MAX_JSON, opener, validators)
        except OnlineError as e:
            return _catalog_from(cache["body"], site, root,
                                 f"server unreachable ({e}); showing the list saved {cache.get('saved_at')}")
        if status == 304:
            _touch_cache(cache_dir, cache)
            return _catalog_from(cache["body"], site, root, "unchanged on the server; using the saved list")
    else:
        status, body, headers = _get_full(url, MAX_JSON, opener)
    cat = _catalog_from(body, site, root, "downloaded now")
    _save_cache(cache_dir, root, body, headers)
    return cat


@dataclass
class Download:
    entry: Entry
    path: Optional[str]              # where it was saved (None if refused)
    sha256: str
    size: int
    cross_check: str                 # "match" | "different" | "unavailable: ..." | "skipped" | "no address"
    status: str                      # "saved" | "already present" | "refused: ..."

    @property
    def ok(self) -> bool:
        return self.status in ("saved", "already present")


def _check_image(data: bytes, entry: Entry) -> fw.FirmwareImage:
    img = fw.parse_bytes(data, entry.file_name)
    if not img.valid:
        bad = ", ".join(c.name for c in img.checks if not c.ok)
        raise OnlineError(f"downloaded file fails the image checks ({bad})")
    if img.product_str != entry.product:
        raise OnlineError(f"downloaded file is for {img.product_str}, catalogue says {entry.product}")
    if img.version_str != entry.version:
        raise OnlineError(f"downloaded file is v{img.version_str}, catalogue says v{entry.version}")
    return img


def download(entry: Entry, dest_dir: str, cross_check: bool = True, opener=None,
             catalog: Optional[Catalog] = None) -> Download:
    """Download one image from the address the site links to, check it, optionally compare
    it with the second recorded address, and save it to dest_dir with a provenance file.
    Nothing is overwritten: an existing file with different content is a refusal."""
    if not entry.downloadable:
        raise OnlineError(f"{entry.product} {entry.version}: the site lists no file to download")
    data = _get(entry.mirror_url, MAX_IMAGE, opener)
    sha = hashlib.sha256(data).hexdigest()
    try:
        _check_image(data, entry)
    except OnlineError as e:
        return Download(entry, None, sha, len(data), "skipped", f"refused: {e}")

    if not cross_check:
        xc = "skipped"
    elif not entry.vendor_url:
        xc = "no address"
    else:
        try:
            other = _get(entry.vendor_url, MAX_IMAGE, opener)
            xc = "match" if other == data else "different"
        except OnlineError as e:
            xc = f"unavailable: {e}"
    if xc == "different":
        return Download(entry, None, sha, len(data), xc,
                        "refused: the two addresses recorded by the site serve different files")

    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(entry.file_name))
    if os.path.exists(path):
        with open(path, "rb") as f:
            have = f.read()
        if have == data:
            return Download(entry, path, sha, len(data), xc, "already present")
        return Download(entry, None, sha, len(data), xc,
                        f"refused: {os.path.basename(path)} already exists with different content "
                        "(not overwritten; compare or move it first)")
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".download-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    prov = {
        "file": os.path.basename(path), "sha256": sha, "size": len(data),
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "site": catalog.site if catalog else site_url(), "data_host": catalog.data_host if catalog else None,
        "downloaded_from": entry.mirror_url, "compared_with": entry.vendor_url if cross_check else None,
        "cross_check": xc, "catalogue_entry": asdict(entry),
    }
    with open(path + ".source.json", "w") as f:
        json.dump(prov, f, indent=2)
    return Download(entry, path, sha, len(data), xc, "saved")


@dataclass
class Comparison:
    file: str
    product: str
    version: str
    sha256: str
    result: str                      # "matches the site" | "DIFFERENT from the site" | "not listed" | "unavailable: ..."


def compare_local(firmware_dir: str, catalog: Catalog, product: Optional[str] = None,
                  opener=None) -> List[Comparison]:
    """For each valid local image, download the site's copy of the same product/version
    (into memory only) and compare bytes."""
    out = []
    for img in fw.scan_directory(firmware_dir):
        if not img.valid or (product and img.product_str != product):
            continue
        sha = hashlib.sha256(img.data).hexdigest()
        e = catalog.find(img.product_str, img.version_str)
        if not e or not e.downloadable:
            res = "not listed"
        else:
            try:
                res = "matches the site" if _get(e.mirror_url, MAX_IMAGE, opener) == img.data \
                    else "DIFFERENT from the site"
            except OnlineError as err:
                res = f"unavailable: {err}"
        out.append(Comparison(os.path.basename(img.path or "?"), img.product_str, img.version_str, sha, res))
    return out

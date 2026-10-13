import re
from pathlib import Path

import pytest

from fixel.playground.monaco import FILES, MonacoError, MonacoFiles, digest

PAGE = Path(__file__).parents[1] / "fixel" / "playground" / "web" / "index.html"
MANIFEST = {"vs/loader.js": digest(b"loader code")}


class FakeFetch:
    def __init__(self, data=b"loader code", error=None):
        self.data, self.error, self.urls = data, error, []

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.data


def test_unknown_paths_are_not_served(tmp_path):
    files = MonacoFiles(tmp_path, fetch=FakeFetch(), files=MANIFEST)
    assert files.get("vs/evil.js") is None and files.get("../../etc/passwd") is None


def test_fetched_once_checked_and_cached(tmp_path):
    fetch = FakeFetch()
    files = MonacoFiles(tmp_path, fetch=fetch, files=MANIFEST)
    assert files.get("vs/loader.js") == b"loader code"
    assert files.get("vs/loader.js") == b"loader code"
    assert len(fetch.urls) == 1 and fetch.urls[0].endswith("/0.52.2/min/vs/loader.js")
    assert (tmp_path / "vs" / "loader.js").read_bytes() == b"loader code"


def test_tampered_download_is_refused_and_not_cached(tmp_path):
    files = MonacoFiles(tmp_path, fetch=FakeFetch(b"evil code"), files=MANIFEST)
    with pytest.raises(MonacoError, match="integrity"):
        files.get("vs/loader.js")
    assert not (tmp_path / "vs" / "loader.js").exists()


def test_tampered_cache_is_replaced(tmp_path):
    (tmp_path / "vs").mkdir()
    (tmp_path / "vs" / "loader.js").write_bytes(b"evil code")
    fetch = FakeFetch()
    assert MonacoFiles(tmp_path, fetch=fetch, files=MANIFEST).get("vs/loader.js") == b"loader code"
    assert len(fetch.urls) == 1


def test_offline_raises_monaco_error(tmp_path):
    files = MonacoFiles(tmp_path, fetch=FakeFetch(error=OSError("no network")), files=MANIFEST)
    with pytest.raises(MonacoError, match="no network"):
        files.get("vs/loader.js")


def test_manifest_covers_every_file_the_page_loads():
    page = PAGE.read_text()
    referenced = set(re.findall(r'/monaco/(vs/[\w./-]+\.(?:js|css))', page))
    assert referenced and referenced <= set(FILES)
    assert all(re.fullmatch(r"[A-Za-z0-9+/]{64}", h) for h in FILES.values())
    assert "vs/base/worker/workerMain.js" in FILES and "vs/language/typescript/tsWorker.js" in FILES


def test_page_loads_no_code_from_a_cdn():
    page = PAGE.read_text()
    assert "cdnjs" not in page and "jsdelivr" not in page and "unpkg" not in page

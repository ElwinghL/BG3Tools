"""Tests pour bg3_mod_tui.downloader.

`httpx.stream` réel n'est jamais appelé : les tests construisent une fausse
réponse httpx (via `httpx.Response` avec un transport `MockTransport`) pour
rester fidèles au vrai comportement de `httpx` sans requête réseau."""

from __future__ import annotations

import httpx
import pytest

from bg3_mod_tui import downloader as dl


def _client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_filename_from_content_disposition_simple():
    assert dl._filename_from_content_disposition('attachment; filename="mod.zip"') == "mod.zip"


def test_filename_from_content_disposition_rfc5987():
    header = "attachment; filename*=UTF-8''mod%20name.zip"
    assert dl._filename_from_content_disposition(header) == "mod name.zip"


def test_filename_from_content_disposition_none():
    assert dl._filename_from_content_disposition(None) is None


def test_filename_from_url():
    assert dl._filename_from_url("https://example.com/path/mod%20file.zip") == "mod file.zip"


def test_filename_from_url_no_name():
    assert dl._filename_from_url("https://example.com/") == "mod_download.bin"


def test_sanitize_filename_removes_unsafe_chars():
    assert dl._sanitize_filename("bad:name/with*chars?") == "bad_name_with_chars_"


def test_sanitize_filename_empty_fallback():
    assert dl._sanitize_filename("   ") == "mod_download"


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"PK\x03\x04rest", ".zip"),
        (b"PK\x05\x06", ".zip"),
        (b"Rar!\x1a\x07\x01\x00", ".rar"),
        (b"Rar!\x1a\x07\x00", ".rar"),
        (b"7z\xbc\xaf\x27\x1c", ".7z"),
        (b"not-an-archive", None),
    ],
)
def test_sniff_archive_extension(data, expected):
    assert dl._sniff_archive_extension(data) == expected


def _make_response(headers=None):
    def handler(request):
        return httpx.Response(200, headers=headers or {}, content=b"PK\x03\x04restofzip")

    with _client_for(handler) as client:
        return client.get("https://example.com/download")


def test_resolve_filename_uses_content_disposition():
    resp = _make_response(headers={"content-disposition": 'attachment; filename="Real.zip"'})
    name, peeked = dl._resolve_filename("https://example.com/download", resp, resp.iter_bytes())
    assert name == "Real.zip"
    assert peeked == b""


def test_resolve_filename_falls_back_to_fallback_stem():
    resp = _make_response()
    name, _peeked = dl._resolve_filename(
        "https://example.com/download.zip", resp, resp.iter_bytes(), fallback_stem="My Mod"
    )
    assert name == "My Mod.zip"


def test_resolve_filename_sniffs_when_no_extension():
    resp = _make_response()
    name, peeked = dl._resolve_filename(
        "https://example.com/download", resp, resp.iter_bytes(), fallback_stem="My Mod"
    )
    assert name == "My Mod.zip"
    assert peeked  # premier chunk consommé pour le reniflage


def _fake_stream_factory(handler):
    """Reproduit `httpx.stream(...)` (context manager) au-dessus d'un
    `MockTransport`, pour éviter toute vraie requête réseau tout en
    exerçant le vrai code de streaming httpx."""

    def fake_stream(method, url, timeout=None, follow_redirects=None):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return client.stream(method, url)

    return fake_stream


def test_resolve_remote_filename(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-disposition": 'attachment; filename="Real.zip"'},
            content=b"PK\x03\x04data",
        )

    monkeypatch.setattr(dl.httpx, "stream", _fake_stream_factory(handler))
    name = dl.resolve_remote_filename("https://example.com/download")
    assert name == "Real.zip"


def test_download_file_success(tmp_path, monkeypatch):
    body = b"PK\x03\x04" + b"x" * 100

    def handler(request):
        return httpx.Response(
            200,
            headers={
                "content-disposition": 'attachment; filename="Mod.zip"',
                "content-length": str(len(body)),
            },
            content=body,
        )

    monkeypatch.setattr(dl.httpx, "stream", _fake_stream_factory(handler))

    progress_calls = []
    target = dl.download_file(
        "https://example.com/download",
        tmp_path,
        on_progress=lambda done, total: progress_calls.append((done, total)),
    )
    assert target == tmp_path / "Mod.zip"
    assert target.read_bytes() == body
    assert progress_calls
    assert progress_calls[-1][0] == len(body)


def test_download_file_rejects_unsupported_extension(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, headers={}, content=b"not an archive at all")

    monkeypatch.setattr(dl.httpx, "stream", _fake_stream_factory(handler))

    with pytest.raises(dl.DownloadError):
        dl.download_file("https://example.com/plain.txt", tmp_path)
    assert not any(tmp_path.iterdir())

"""Tests pour bg3_mod_tui.webserver."""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from bg3_mod_tui import webserver as ws


def test_start_http_server_invalid_port_low(tmp_path):
    with pytest.raises(ValueError):
        ws.start_http_server(tmp_path, "0", on_line=lambda _line: None)


def test_start_http_server_invalid_port_high(tmp_path):
    with pytest.raises(ValueError):
        ws.start_http_server(tmp_path, "65536", on_line=lambda _line: None)


def test_start_http_server_invalid_port_not_a_number(tmp_path):
    with pytest.raises(ValueError):
        ws.start_http_server(tmp_path, "abc", on_line=lambda _line: None)


class _FakeProcess:
    def __init__(self, lines):
        self._lines = list(lines)
        self.stdout = iter(self._lines)
        self.terminated = False
        self.killed = False
        self._poll_result = None

    def poll(self):
        return self._poll_result

    def terminate(self):
        self.terminated = True
        self._poll_result = 0

    def wait(self, timeout=None):
        if self._wait_raises:
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)

    def kill(self):
        self.killed = True

    _wait_raises = False


@pytest.fixture(autouse=True)
def _cleanup_active_handles():
    yield
    with ws._active_handles_lock:
        ws._active_handles.clear()


def test_start_http_server_pumps_output(tmp_path, monkeypatch):
    fake_process = _FakeProcess(["line1\n", "line2\n"])
    monkeypatch.setattr(ws.subprocess, "Popen", lambda *a, **k: fake_process)

    received: list[str] = []
    handle = ws.start_http_server(tmp_path, "8123", on_line=received.append)
    handle.thread.join(timeout=2)

    assert received == ["line1", "line2"]
    assert handle in ws._active_handles


def test_web_server_handle_is_running():
    fake_process = _FakeProcess([])
    thread = threading.Thread(target=lambda: None)
    handle = ws.WebServerHandle(fake_process, thread)
    fake_process._poll_result = None
    assert handle.is_running is True
    fake_process._poll_result = 0
    assert handle.is_running is False


def test_web_server_handle_stop_terminates_running_process():
    fake_process = _FakeProcess([])
    thread = threading.Thread(target=lambda: None)
    handle = ws.WebServerHandle(fake_process, thread)
    with ws._active_handles_lock:
        ws._active_handles.add(handle)

    handle.stop()
    assert fake_process.terminated is True
    assert handle not in ws._active_handles


def test_web_server_handle_stop_kills_on_timeout():
    fake_process = _FakeProcess([])
    fake_process._wait_raises = True

    def terminate():
        fake_process.terminated = True
        # poll() reste None (processus toujours "actif" pour wait())

    fake_process.terminate = terminate
    thread = threading.Thread(target=lambda: None)
    handle = ws.WebServerHandle(fake_process, thread)
    handle.stop()
    assert fake_process.killed is True


def test_web_server_handle_stop_noop_if_already_stopped():
    fake_process = _FakeProcess([])
    fake_process._poll_result = 0
    thread = threading.Thread(target=lambda: None)
    handle = ws.WebServerHandle(fake_process, thread)
    handle.stop()  # ne lève pas, rien à arrêter
    assert fake_process.terminated is False


def test_stop_all_servers(monkeypatch):
    fake_process = _FakeProcess([])
    thread = threading.Thread(target=lambda: None)
    handle = ws.WebServerHandle(fake_process, thread)
    with ws._active_handles_lock:
        ws._active_handles.add(handle)

    ws.stop_all_servers()
    assert fake_process.terminated is True
    assert handle not in ws._active_handles

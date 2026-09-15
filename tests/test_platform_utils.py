"""Tests pour bg3_mod_tui.platform_utils."""

from __future__ import annotations

import errno

import pytest

from bg3_mod_tui import platform_utils as pu


def test_is_windows(monkeypatch):
    monkeypatch.setattr(pu.sys, "platform", "win32")
    assert pu.is_windows() is True
    monkeypatch.setattr(pu.sys, "platform", "linux")
    assert pu.is_windows() is False


def test_has_graphical_display_windows_always_true(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    assert pu.has_graphical_display() is True


def test_has_graphical_display_linux_with_display(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert pu.has_graphical_display() is True


def test_has_graphical_display_linux_with_wayland(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert pu.has_graphical_display() is True


def test_has_graphical_display_headless(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert pu.has_graphical_display() is False


def test_is_admin_non_windows(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    assert pu.is_admin() is True


def test_is_admin_windows_fails_gracefully(monkeypatch):
    # Sous Linux, `ctypes.windll` n'existe pas : l'exception est attrapée
    # et False retourné plutôt que de planter.
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    assert pu.is_admin() is False


def test_relaunch_as_admin_non_windows(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    assert pu.relaunch_as_admin() is False


def test_relaunch_as_admin_windows_fails_gracefully(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    assert pu.relaunch_as_admin() is False


def test_windows_dev_mode_enabled_non_windows(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    assert pu.windows_dev_mode_enabled() is False


def test_windows_dev_mode_enabled_windows_fails_gracefully(monkeypatch):
    # `winreg` n'existe pas sous Linux -> ImportError attrapée -> False.
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    assert pu.windows_dev_mode_enabled() is False


def test_can_create_links_without_admin_non_windows(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    assert pu.can_create_links_without_admin() is True


def test_can_create_links_without_admin_windows_admin(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setattr(pu, "is_admin", lambda: True)
    monkeypatch.setattr(pu, "windows_dev_mode_enabled", lambda: False)
    assert pu.can_create_links_without_admin() is True


def test_can_create_links_without_admin_windows_dev_mode(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setattr(pu, "is_admin", lambda: False)
    monkeypatch.setattr(pu, "windows_dev_mode_enabled", lambda: True)
    assert pu.can_create_links_without_admin() is True


def test_can_create_links_without_admin_windows_denied(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setattr(pu, "is_admin", lambda: False)
    monkeypatch.setattr(pu, "windows_dev_mode_enabled", lambda: False)
    assert pu.can_create_links_without_admin() is False


def test_find_proton_prefix_found(tmp_path):
    pfx = tmp_path / "compatdata" / "1234" / "pfx"
    (pfx / "drive_c").mkdir(parents=True)
    start = pfx / "drive_c" / "users" / "steamuser"
    start.mkdir(parents=True)
    assert pu.find_proton_prefix(start) == pfx


def test_find_proton_prefix_not_found(tmp_path):
    start = tmp_path / "somewhere" / "else"
    start.mkdir(parents=True)
    assert pu.find_proton_prefix(start) is None


def test_steam_root_candidates_filters_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pu.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".steam" / "steam").mkdir(parents=True)
    candidates = pu._steam_root_candidates()
    assert candidates == [tmp_path / ".steam" / "steam"]


def test_find_proton_dir_no_config_info(tmp_path):
    prefix = tmp_path / "compatdata" / "1234" / "pfx"
    prefix.mkdir(parents=True)
    assert pu.find_proton_dir(prefix) is None


def test_find_proton_dir_empty_config_info(tmp_path):
    appid_dir = tmp_path / "compatdata" / "1234"
    prefix = appid_dir / "pfx"
    prefix.mkdir(parents=True)
    (appid_dir / "config_info").write_text("\n")
    assert pu.find_proton_dir(prefix) is None


def test_find_proton_dir_found_via_steamapps_common(tmp_path, monkeypatch):
    # Isole `_steam_root_candidates()` de la vraie install Steam de la
    # machine (sinon un vrai dossier Proton pourrait matcher en premier).
    monkeypatch.setattr(pu.Path, "home", classmethod(lambda cls: tmp_path / "fake_home"))
    library = tmp_path / "library"
    steamapps = library / "steamapps"
    appid_dir = steamapps / "compatdata" / "1234"
    prefix = appid_dir / "pfx"
    prefix.mkdir(parents=True)
    (appid_dir / "config_info").write_text("GE-Proton11-1\n")

    proton_entry = steamapps / "common" / "Proton 11.1"
    proton_entry.mkdir(parents=True)
    (proton_entry / "version").write_text("20240101 GE-Proton11-1\n")

    assert pu.find_proton_dir(prefix) == proton_entry


def test_find_proton_dir_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(pu.Path, "home", classmethod(lambda cls: tmp_path / "fake_home"))
    library = tmp_path / "library"
    steamapps = library / "steamapps"
    appid_dir = steamapps / "compatdata" / "1234"
    prefix = appid_dir / "pfx"
    prefix.mkdir(parents=True)
    (appid_dir / "config_info").write_text("GE-Proton11-1\n")

    proton_entry = steamapps / "common" / "Proton 9.0"
    proton_entry.mkdir(parents=True)
    (proton_entry / "version").write_text("some-other-version\n")

    assert pu.find_proton_dir(prefix) is None


def test_find_proton_wine_bin_found(tmp_path, monkeypatch):
    prefix = tmp_path / "pfx"
    prefix.mkdir()
    proton_dir = tmp_path / "proton"
    wine_bin = proton_dir / "files" / "bin" / "wine"
    wine_bin.parent.mkdir(parents=True)
    wine_bin.write_text("")
    monkeypatch.setattr(pu, "find_proton_dir", lambda p: proton_dir)
    assert pu.find_proton_wine_bin(prefix) == wine_bin


def test_find_proton_wine_bin_not_found(tmp_path, monkeypatch):
    prefix = tmp_path / "pfx"
    monkeypatch.setattr(pu, "find_proton_dir", lambda p: None)
    assert pu.find_proton_wine_bin(prefix) is None


def test_find_proton_wine_bin_missing_wine_binary(tmp_path, monkeypatch):
    prefix = tmp_path / "pfx"
    proton_dir = tmp_path / "proton"
    proton_dir.mkdir()
    monkeypatch.setattr(pu, "find_proton_dir", lambda p: proton_dir)
    assert pu.find_proton_wine_bin(prefix) is None


def test_to_wine_path(tmp_path):
    target = tmp_path / "sub" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    result = pu.to_wine_path(target)
    assert result.startswith("Z:")
    assert "\\" in result
    assert "/" not in result[2:]


def test_link_or_symlink_normal(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("hello")
    target = tmp_path / "target.txt"
    pu.link_or_symlink(source, target)
    assert target.read_text() == "hello"
    assert not target.is_symlink()


def test_link_or_symlink_exdev_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("hello")
    target = tmp_path / "target.txt"

    def fake_link(_src, _dst):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(pu.os, "link", fake_link)
    pu.link_or_symlink(source, target)
    assert target.is_symlink()


def test_link_or_symlink_other_oserror_reraised(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("hello")
    target = tmp_path / "target.txt"

    def fake_link(_src, _dst):
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(pu.os, "link", fake_link)
    with pytest.raises(OSError):
        pu.link_or_symlink(source, target)


def test_default_env_appdata_windows(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    assert pu.default_env_appdata() == r"C:\Users\test\AppData\Local"


def test_default_env_appdata_linux(monkeypatch):
    monkeypatch.setattr(pu, "is_windows", lambda: False)
    assert pu.default_env_appdata() is None

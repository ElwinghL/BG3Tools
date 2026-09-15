"""Tests pour bg3_mod_tui/providers/nexus.py — client API Nexus Mods.
Tout appel réseau (`httpx.Client`) est mocké ; aucune requête HTTP réelle
n'est effectuée."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bg3_mod_tui.providers import nexus


def _client_ctx(get_side_effect):
    client = MagicMock()
    client.get.side_effect = get_side_effect
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    return r


# ---------------------------------------------------------------------------
# parse_mod_links_file / remove_mod_links
# ---------------------------------------------------------------------------


def test_parse_mod_links_file_missing_raises(tmp_path):
    with pytest.raises(nexus.NexusAPIError, match="introuvable"):
        nexus.parse_mod_links_file(tmp_path / "missing.md")


def test_parse_mod_links_file_extracts_ids(tmp_path):
    f = tmp_path / "links.md"
    f.write_text(
        "https://www.nexusmods.com/baldursgate3/mods/5447\n"
        "some unrelated line\n"
        "https://www.nexusmods.com/baldursgate3/mods/1234 extra text\n",
        encoding="utf-8",
    )
    assert nexus.parse_mod_links_file(f) == [5447, 1234]


def test_remove_mod_links_noop_if_missing_file(tmp_path):
    nexus.remove_mod_links(tmp_path / "missing.md", {1})  # ne doit pas lever


def test_remove_mod_links_noop_if_no_ids(tmp_path):
    f = tmp_path / "links.md"
    f.write_text("https://www.nexusmods.com/baldursgate3/mods/1\n", encoding="utf-8")
    nexus.remove_mod_links(f, set())
    assert f.read_text(encoding="utf-8") == "https://www.nexusmods.com/baldursgate3/mods/1\n"


def test_remove_mod_links_removes_matching(tmp_path):
    f = tmp_path / "links.md"
    f.write_text(
        "https://www.nexusmods.com/baldursgate3/mods/1\n"
        "keep this line\n"
        "https://www.nexusmods.com/baldursgate3/mods/2\n",
        encoding="utf-8",
    )
    nexus.remove_mod_links(f, {1})
    content = f.read_text(encoding="utf-8")
    assert "mods/1" not in content
    assert "keep this line" in content
    assert "mods/2" in content


def test_remove_mod_links_all_removed_leaves_empty_file(tmp_path):
    f = tmp_path / "links.md"
    f.write_text("https://www.nexusmods.com/baldursgate3/mods/1\n", encoding="utf-8")
    nexus.remove_mod_links(f, {1})
    assert f.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# NexusClient construction
# ---------------------------------------------------------------------------


def test_nexus_client_requires_api_key():
    with pytest.raises(nexus.NexusAPIError, match="Clé API"):
        nexus.NexusClient("")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_success():
    client = nexus.NexusClient("key")
    with patch.object(
        nexus.httpx, "Client", return_value=_client_ctx([_resp(200, {"name": "user"})])
    ):
        data = client.validate()
    assert data == {"name": "user"}


def test_validate_failure_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(401)])):
        with pytest.raises(nexus.NexusAPIError, match="invalide"):
            client.validate()


# ---------------------------------------------------------------------------
# mod_info
# ---------------------------------------------------------------------------


def test_mod_info_success():
    client = nexus.NexusClient("key")
    data = {"mod_id": 5447, "name": "Config App", "version": "1.1", "summary": "sum"}
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, data)])):
        mod = client.mod_info(5447)
    assert mod == nexus.NexusMod(mod_id=5447, name="Config App", version="1.1", summary="sum")


def test_mod_info_defaults_missing_fields():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, {"mod_id": 1})])):
        mod = client.mod_info(1)
    assert mod.name == "Mod 1"
    assert mod.version == ""
    assert mod.summary == ""


def test_mod_info_not_found_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(404)])):
        with pytest.raises(nexus.NexusAPIError, match="introuvable"):
            client.mod_info(999)


# ---------------------------------------------------------------------------
# tracked_mods
# ---------------------------------------------------------------------------


def test_tracked_mods_filters_by_domain_and_fetches_info():
    client = nexus.NexusClient("key")
    tracked_resp = _resp(
        200, [{"domain_name": "baldursgate3", "mod_id": 1}, {"domain_name": "skyrim", "mod_id": 2}]
    )
    mod_info_resp = _resp(200, {"mod_id": 1, "name": "M1", "version": "1.0", "summary": ""})

    with patch.object(
        nexus.httpx,
        "Client",
        side_effect=[_client_ctx([tracked_resp]), _client_ctx([mod_info_resp])],
    ):
        mods = client.tracked_mods()
    assert len(mods) == 1
    assert mods[0].mod_id == 1


def test_tracked_mods_error_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(500)])):
        with pytest.raises(nexus.NexusAPIError, match="mods suivis"):
            client.tracked_mods()


# ---------------------------------------------------------------------------
# latest_file_variants / latest_files
# ---------------------------------------------------------------------------


def test_latest_file_variants_error_status():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(500)])):
        with pytest.raises(nexus.NexusAPIError, match="Impossible de récupérer"):
            client.latest_file_variants(1)


def test_latest_file_variants_no_files_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, {"files": []})])):
        with pytest.raises(nexus.NexusAPIError, match="Aucun fichier"):
            client.latest_file_variants(1)


def test_latest_file_variants_dedups_by_name_keeps_newest():
    client = nexus.NexusClient("key")
    files = {
        "files": [
            {
                "category_name": "MAIN",
                "name": "Variant A",
                "file_id": 1,
                "file_name": "a-v1.zip",
                "version": "1.0",
                "uploaded_timestamp": 100,
            },
            {
                "category_name": "UPDATE",
                "name": "Variant A",
                "file_id": 2,
                "file_name": "a-v2.zip",
                "version": "2.0",
                "uploaded_timestamp": 200,
            },
            {
                "category_name": "OPTIONAL",
                "name": "Variant B",
                "file_id": 3,
                "file_name": "b.zip",
                "version": "1.0",
                "uploaded_timestamp": 150,
            },
            {
                "category_name": "OLD_VERSION",
                "name": "Variant A",
                "file_id": 4,
                "file_name": "a-old.zip",
                "version": "0.5",
                "uploaded_timestamp": 50,
            },
        ]
    }
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, files)])):
        variants = client.latest_file_variants(1)

    by_name = {v.name: v for v in variants}
    assert by_name["Variant A"].version == "2.0"
    assert by_name["Variant A"].file_id == 2
    assert "Variant B" in by_name
    assert len(variants) == 2  # OLD_VERSION exclu


def test_latest_file_variants_falls_back_to_all_files_if_none_eligible():
    client = nexus.NexusClient("key")
    files = {
        "files": [
            {
                "category_name": "MISCELLANEOUS",
                "name": "Extra",
                "file_id": 9,
                "file_name": "extra.zip",
                "version": "1.0",
                "uploaded_timestamp": 1,
            }
        ]
    }
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, files)])):
        variants = client.latest_file_variants(1)
    assert len(variants) == 1
    assert variants[0].name == "Extra"


def test_latest_file_variants_default_names():
    client = nexus.NexusClient("key")
    files = {"files": [{"category_name": "MAIN", "file_id": 7, "uploaded_timestamp": 1}]}
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, files)])):
        variants = client.latest_file_variants(1)
    assert variants[0].file_name == "mod_1.zip"
    assert variants[0].name == ""


def test_latest_files_wraps_variants():
    client = nexus.NexusClient("key")
    files = {
        "files": [
            {
                "category_name": "MAIN",
                "name": "V",
                "file_id": 1,
                "file_name": "v.zip",
                "version": "1.0",
                "uploaded_timestamp": 1,
            }
        ]
    }
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, files)])):
        result = client.latest_files(1)
    assert result == [(1, "v.zip")]


# ---------------------------------------------------------------------------
# download_link
# ---------------------------------------------------------------------------


def test_download_link_success():
    client = nexus.NexusClient("key")
    with patch.object(
        nexus.httpx,
        "Client",
        return_value=_client_ctx([_resp(200, [{"URI": "http://x/file.zip"}])]),
    ):
        url = client.download_link(1, 2)
    assert url == "http://x/file.zip"


def test_download_link_no_premium_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(403)])):
        with pytest.raises(nexus.NexusAPIError, match="non-Premium"):
            client.download_link(1, 2)


def test_download_link_empty_list_raises():
    client = nexus.NexusClient("key")
    with patch.object(nexus.httpx, "Client", return_value=_client_ctx([_resp(200, [])])):
        with pytest.raises(nexus.NexusAPIError, match="Aucun lien"):
            client.download_link(1, 2)

"""Tests pour bg3_mod_tui/providers/modio.py — client API mod.io. Tout
appel réseau (`httpx.Client`) est mocké."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bg3_mod_tui.providers import modio


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


def test_client_requires_api_key():
    with pytest.raises(modio.ModIOAPIError, match="Clé API"):
        modio.ModIOClient("", user_id="1")


def test_client_requires_user_id_or_base():
    with pytest.raises(modio.ModIOAPIError, match="MOD_IO_USER_ID"):
        modio.ModIOClient("key")


def test_client_base_from_user_id():
    client = modio.ModIOClient("key", user_id="42")
    assert client._base == "https://u-42.modapi.io/v1"


def test_client_base_from_explicit_api_base_strips_trailing_slash():
    client = modio.ModIOClient("key", api_base="https://custom.example/v1/")
    assert client._base == "https://custom.example/v1"


def test_client_headers_with_access_token():
    client = modio.ModIOClient("key", user_id="1", access_token="tok")
    with patch.object(modio.httpx, "Client") as ctor:
        client._client()
    _, kwargs = ctor.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_client_headers_without_access_token():
    client = modio.ModIOClient("key", user_id="1")
    with patch.object(modio.httpx, "Client") as ctor:
        client._client()
    _, kwargs = ctor.call_args
    assert "Authorization" not in kwargs["headers"]


def test_params_merges_api_key():
    client = modio.ModIOClient("key", user_id="1")
    params = client._params(foo="bar")
    assert params == {"api_key": "key", "foo": "bar"}


def test_subscribed_mods_success():
    client = modio.ModIOClient("key", user_id="1")
    data = {
        "data": [
            {
                "id": 1,
                "name": "Mod One",
                "summary": "desc",
                "modfile": {"download": {"binary_url": "http://x/mod.zip"}},
            },
            {"id": 2},
        ]
    }
    with patch.object(client, "_client", return_value=_client_ctx([_resp(200, data)])):
        mods = client.subscribed_mods()
    assert mods[0] == modio.ModIOMod(
        mod_id=1, name="Mod One", summary="desc", download_url="http://x/mod.zip"
    )
    assert mods[1].name == "Mod 2"
    assert mods[1].download_url is None


def test_subscribed_mods_error_raises():
    client = modio.ModIOClient("key", user_id="1")
    with patch.object(client, "_client", return_value=_client_ctx([_resp(500)])):
        with pytest.raises(modio.ModIOAPIError, match="mods abonnés"):
            client.subscribed_mods()


def test_subscribed_mods_no_modfile():
    client = modio.ModIOClient("key", user_id="1")
    data = {"data": [{"id": 3, "name": "NoFile", "summary": "", "modfile": None}]}
    with patch.object(client, "_client", return_value=_client_ctx([_resp(200, data)])):
        mods = client.subscribed_mods()
    assert mods[0].download_url is None

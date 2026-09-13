"""Tests de `bg3_mod_tui.compat_audit` — audit statique 18a/18b/18c du TODO
section 18 (dépendances/config, syntaxe des GUIDs, déclarations
d'injection). Les tests d'intégration (`audit_mod`/`audit_installed_mods`)
construisent un .pak LSPK v18 minimal en mémoire (même approche que
`tests/test_pak_reader.py`, pas de vrai .pak BG3 disponible dans cet
environnement) ; les autres testent directement les fonctions pures
(pas d'I/O), sans passer par un .pak."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import lz4.block
import pytest

from bg3_mod_tui.compat_audit import (
    KNOWN_JSON_ACTIONS,
    PLACEHOLDER_GUID,
    _audit_bootstrap_lua,
    _audit_config_file,
    _check_actions_generic,
    _check_lists_section,
    _check_progressions_section,
    _classify_guid,
    _collect_guids,
    audit_installed_mods,
    audit_mod,
    write_compat_audit_markdown,
)

_SIGNATURE_BYTES = struct.pack("<I", 0x4B50534C)

_VALID_V4 = "b60618d1-c262-42b5-9fdd-2c0f7aa5e5af"
_VALID_V4_2 = "6fb3831e-45d8-4b30-9714-6fe73988921b"


def _meta_lsx(mod_uuid: str, mod_name: str, dependency_uuid: str | None = None) -> bytes:
    dep_block = ""
    if dependency_uuid:
        dep_block = f"""
        <node id="Dependencies">
          <children>
            <node id="ModuleShortDesc">
              <attribute id="UUID" value="{dependency_uuid}" type="guid"/>
              <attribute id="Name" value="Dep" type="LSString"/>
            </node>
          </children>
        </node>"""
    return f"""<?xml version="1.0"?>
<save>
  <version major="4" minor="0" revision="0" build="0"/>
  <region id="Config">
    <node id="root">
      <children>{dep_block}
        <node id="ModuleInfo">
          <attribute id="UUID" value="{mod_uuid}" type="guid"/>
          <attribute id="Name" value="{mod_name}" type="LSString"/>
          <attribute id="Folder" value="{mod_name}" type="LSString"/>
        </node>
      </children>
    </node>
  </region>
</save>
""".encode("utf-8")


def _build_v18_pak_multi(entries: list[tuple[str, bytes]]) -> bytes:
    """Construit un .pak LSPK v18 minimal en mémoire avec plusieurs entrées
    non compressées — copie locale de l'utilitaire de
    `tests/test_pak_reader.py` (voir sa docstring), dupliquée ici pour que
    ce fichier de test reste autonome."""
    data_offset = 40  # 4 (signature) + 36 (LSPKHeader16)

    packed_entries = b""
    concatenated_content = b""
    offset = data_offset
    for entry_name, content in entries:
        name_bytes = entry_name.encode("utf-8").ljust(256, b"\0")
        packed_entries += struct.pack(
            "<256sIHBBII",
            name_bytes,
            offset,
            0,
            0,
            0,
            len(content),
            len(content),
        )
        concatenated_content += content
        offset += len(content)

    file_list_offset = data_offset + len(concatenated_content)
    compressed_entries = lz4.block.compress(packed_entries, store_size=False)

    header = struct.pack(
        "<IQIBB16sH",
        18,
        file_list_offset,
        len(compressed_entries),
        0,
        0,
        b"\0" * 16,
        1,
    )
    file_list_section = struct.pack("<II", len(entries), len(compressed_entries)) + compressed_entries

    return _SIGNATURE_BYTES + header + concatenated_content + file_list_section


def _write_pak(tmp_path: Path, name: str, entries: list[tuple[str, bytes]]) -> Path:
    path = tmp_path / name
    path.write_bytes(_build_v18_pak_multi(entries))
    return path


# --- _classify_guid --------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (_VALID_V4, "ok"),
        (PLACEHOLDER_GUID, "placeholder"),
        ("b60618d1-c262-12b5-9fdd-2c0f7aa5e5af", "not_v4"),  # version nibble = 1, pas 4
        ("your-mods-uuid-in-metalsx", "invalid"),
        ("", "invalid"),
        ("   ", "invalid"),
    ],
)
def test_classify_guid(value, expected):
    assert _classify_guid(value) == expected


# --- _collect_guids ---------------------------------------------------------


def test_collect_guids_nested():
    data = {
        "Progressions": [
            {"UUID": _VALID_V4, "Subclasses": [{"UUID": _VALID_V4_2, "Action": "Remove"}]},
        ],
        "Unrelated": {"Value": "Intelligence"},
    }
    found = dict(_collect_guids(data))
    values = set(found.values())
    assert _VALID_V4 in values
    assert _VALID_V4_2 in values
    assert "Intelligence" not in values


def test_collect_guids_list_of_uuids():
    data = {"ClassDescriptions": [{"UUIDs": [_VALID_V4, PLACEHOLDER_GUID]}]}
    found = dict(_collect_guids(data))
    assert set(found.values()) == {_VALID_V4, PLACEHOLDER_GUID}


# --- _check_actions_generic --------------------------------------------------


def test_check_actions_generic_flags_unknown_action():
    errors: list[str] = []
    _check_actions_generic({"Lists": [{"Action": "AddSubclass"}]}, "$", errors)
    assert len(errors) == 1
    assert "AddSubclass" in errors[0]


def test_check_actions_generic_accepts_known_actions():
    for action in KNOWN_JSON_ACTIONS:
        errors: list[str] = []
        _check_actions_generic({"Lists": [{"Action": action}]}, "$", errors)
        assert errors == []


# --- _check_lists_section -----------------------------------------------------


def test_check_lists_section_missing_type_is_error():
    warnings: list[str] = []
    errors: list[str] = []
    _check_lists_section([{"Action": "Insert", "Items": ["x"]}], warnings, errors)
    assert any("Type" in e for e in errors)


def test_check_lists_section_missing_content_is_warning():
    warnings: list[str] = []
    errors: list[str] = []
    _check_lists_section([{"Action": "Insert", "Type": "SpellList"}], warnings, errors)
    assert errors == []
    assert any("ignorée" in w for w in warnings)


def test_check_lists_section_valid_entry_is_silent():
    warnings: list[str] = []
    errors: list[str] = []
    _check_lists_section([{"Action": "Insert", "Type": "SpellList", "Items": ["x"]}], warnings, errors)
    assert warnings == []
    assert errors == []


# --- _check_progressions_section ----------------------------------------------


def test_check_progressions_section_insert_subclass_is_flagged():
    warnings: list[str] = []
    refs: list[tuple[str, str]] = []
    _check_progressions_section(
        [{"UUID": _VALID_V4, "Subclasses": [{"UUID": _VALID_V4_2, "Action": "Insert"}]}],
        warnings,
        refs,
    )
    assert len(warnings) == 1
    assert "InsertSubClasses" in warnings[0]
    assert refs == [("$.Progressions[0].Subclasses[0]", _VALID_V4)]


def test_check_progressions_section_remove_subclass_is_silent():
    warnings: list[str] = []
    refs: list[tuple[str, str]] = []
    _check_progressions_section(
        [{"UUID": _VALID_V4, "Subclasses": [{"UUID": _VALID_V4_2, "Action": "Remove"}]}],
        warnings,
        refs,
    )
    assert warnings == []
    assert refs == [("$.Progressions[0].Subclasses[0]", _VALID_V4)]


# --- _audit_config_file --------------------------------------------------------


def test_audit_config_file_invalid_json_syntax():
    ok, warnings, errors = [], [], []
    _audit_config_file("{not valid json", "CompatibilityFrameworkConfig.json", ok, warnings, errors)
    assert len(errors) == 1
    assert "JSON invalide" in errors[0]


def test_audit_config_file_valid_json_reports_ok():
    text = json.dumps({"FileVersion": 1, "Lists": [{"Action": "Insert", "Type": "SpellList", "Items": ["x"]}]})
    ok, warnings, errors = [], [], []
    data, refs = _audit_config_file(text, "CompatibilityFrameworkConfig.json", ok, warnings, errors)
    assert errors == []
    assert data is not None
    assert any("syntaxe valide" in m for m in ok)


def test_audit_config_file_unknown_top_section_is_warning():
    text = json.dumps({"NotASection": []})
    ok, warnings, errors = [], [], []
    _audit_config_file(text, "CompatibilityFrameworkConfig.json", ok, warnings, errors)
    assert any("NotASection" in w for w in warnings)


def test_audit_config_file_placeholder_guid_is_error():
    text = json.dumps({"ClassDescriptions": [{"UUID": PLACEHOLDER_GUID}]})
    ok, warnings, errors = [], [], []
    _audit_config_file(text, "CompatibilityFrameworkConfig.json", ok, warnings, errors)
    assert any(PLACEHOLDER_GUID in e for e in errors)


# --- _audit_bootstrap_lua --------------------------------------------------------


def test_audit_bootstrap_lua_unknown_function_is_error():
    text = 'Mods.SubclassCompatibilityFramework.Api.AddSubclass({modGuid = "x"})'
    ok, warnings, errors = [], [], []
    found = _audit_bootstrap_lua(text, "BootstrapClient.lua", ok, warnings, errors)
    assert found is True
    assert any("AddSubclass" in e for e in errors)


def test_audit_bootstrap_lua_known_function_is_not_flagged_as_unknown():
    text = 'Mods.SubclassCompatibilityFramework.Api.InsertSubClasses(subClasses)'
    ok, warnings, errors = [], [], []
    _audit_bootstrap_lua(text, "BootstrapClient.lua", ok, warnings, errors)
    assert errors == []


def test_audit_bootstrap_lua_flags_template_guid_leftover():
    text = 'local t = { modGuid = "your-mods-uuid-in-metalsx" }'
    ok, warnings, errors = [], [], []
    _audit_bootstrap_lua(text, "BootstrapClient.lua", ok, warnings, errors)
    assert any("your-mods-uuid-in-metalsx" in e for e in errors)


# --- audit_mod (intégration, .pak construit à la main) ----------------------------


def test_audit_mod_not_applicable_without_cf_integration(tmp_path):
    entries = [("Mods/PlainMod/meta.lsx", _meta_lsx(_VALID_V4, "PlainMod"))]
    pak_path = _write_pak(tmp_path, "plain.pak", entries)
    result = audit_mod(pak_path)
    assert result.applicable is False
    assert result.errors == []


def test_audit_mod_missing_script_extender_dependency_is_error(tmp_path):
    cf_config = json.dumps({"ClassDescriptions": [{"UUID": _VALID_V4}]}).encode("utf-8")
    entries = [
        ("Mods/MyMod/meta.lsx", _meta_lsx(_VALID_V4_2, "MyMod", dependency_uuid=None)),
        ("Mods/MyMod/ScriptExtender/CompatibilityFrameworkConfig.json", cf_config),
    ]
    pak_path = _write_pak(tmp_path, "mymod.pak", entries)
    result = audit_mod(pak_path)
    assert result.applicable is True
    assert any("ScriptExtender/Config.json" in e for e in result.errors)
    assert any("CommunityLibrary" in w for w in result.warnings)


def test_audit_mod_well_formed_mod_has_no_errors(tmp_path):
    from bg3_mod_tui.compat_audit import COMMUNITY_LIBRARY_UUID

    cf_config = json.dumps(
        {
            "ClassDescriptions": [{"UUID": _VALID_V4}],
            "Lists": [{"Action": "Insert", "Type": "SpellList", "Items": [_VALID_V4_2]}],
        }
    ).encode("utf-8")
    se_config = json.dumps({"RequiredVersion": 3, "ModTable": "MyMod", "FeatureFlags": ["Lua"]}).encode("utf-8")
    entries = [
        ("Mods/MyMod/meta.lsx", _meta_lsx(_VALID_V4_2, "MyMod", dependency_uuid=COMMUNITY_LIBRARY_UUID)),
        ("Mods/MyMod/ScriptExtender/Config.json", se_config),
        ("Mods/MyMod/ScriptExtender/CompatibilityFrameworkConfig.json", cf_config),
    ]
    pak_path = _write_pak(tmp_path, "mymod.pak", entries)
    result = audit_mod(pak_path)
    assert result.applicable is True
    assert result.errors == []
    assert result.mod_name == "MyMod"
    assert result.mod_uuid == _VALID_V4_2


def test_audit_mod_corrupted_pak_reports_error(tmp_path):
    pak_path = tmp_path / "broken.pak"
    pak_path.write_bytes(b"PK\x03\x04" + b"\0" * 100)  # en-tête zip, pas LSPK
    result = audit_mod(pak_path)
    assert result.applicable is True
    assert result.errors
    assert "illisible" in result.errors[0]


# --- audit_installed_mods / cohérence inter-mods (18b) ---------------------------


def test_audit_installed_mods_cross_mod_parent_consistency(tmp_path):
    # Mod A : déclare une classe personnalisée (ClassDescriptions[].UUID == _VALID_V4).
    class_a_config = json.dumps({"ClassDescriptions": [{"UUID": _VALID_V4}]}).encode("utf-8")
    se_config = json.dumps({"RequiredVersion": 3, "FeatureFlags": ["Lua"]}).encode("utf-8")
    pak_a = _write_pak(
        tmp_path,
        "mod_a.pak",
        [
            ("Mods/ModA/meta.lsx", _meta_lsx("11111111-1111-4111-8111-111111111111", "ModA")),
            ("Mods/ModA/ScriptExtender/Config.json", se_config),
            ("Mods/ModA/ScriptExtender/CompatibilityFrameworkConfig.json", class_a_config),
        ],
    )

    # Mod B : retire une sous-classe de la Progression _VALID_V4 (celle de ModA).
    prog_b_config = json.dumps(
        {"Progressions": [{"UUID": _VALID_V4, "Subclasses": [{"UUID": _VALID_V4_2, "Action": "Remove"}]}]}
    ).encode("utf-8")
    pak_b = _write_pak(
        tmp_path,
        "mod_b.pak",
        [
            ("Mods/ModB/meta.lsx", _meta_lsx("22222222-2222-4222-8222-222222222222", "ModB")),
            ("Mods/ModB/ScriptExtender/Config.json", se_config),
            ("Mods/ModB/ScriptExtender/CompatibilityFrameworkConfig.json", prog_b_config),
        ],
    )

    results = audit_installed_mods([pak_a, pak_b])
    by_name = {r.mod_name: r for r in results}
    assert any("cohérence interne confirmée" in m for m in by_name["ModB"].ok)


def test_audit_installed_mods_unresolved_parent_is_a_warning_not_error(tmp_path):
    se_config = json.dumps({"RequiredVersion": 3, "FeatureFlags": ["Lua"]}).encode("utf-8")
    prog_config = json.dumps(
        {"Progressions": [{"UUID": _VALID_V4, "Subclasses": [{"UUID": _VALID_V4_2, "Action": "Remove"}]}]}
    ).encode("utf-8")
    pak_path = _write_pak(
        tmp_path,
        "solo.pak",
        [
            ("Mods/Solo/meta.lsx", _meta_lsx("33333333-3333-4333-8333-333333333333", "Solo")),
            ("Mods/Solo/ScriptExtender/Config.json", se_config),
            ("Mods/Solo/ScriptExtender/CompatibilityFrameworkConfig.json", prog_config),
        ],
    )
    results = audit_installed_mods([pak_path])
    result = results[0]
    assert result.errors == []
    assert any("classe vanilla" in w for w in result.warnings)


# --- write_compat_audit_markdown -----------------------------------------------


def test_write_compat_audit_markdown_smoke(tmp_path):
    cf_config = json.dumps({"ClassDescriptions": [{"UUID": PLACEHOLDER_GUID}]}).encode("utf-8")
    pak_path = _write_pak(
        tmp_path,
        "mod.pak",
        [
            ("Mods/MyMod/meta.lsx", _meta_lsx(_VALID_V4, "MyMod")),
            ("Mods/MyMod/ScriptExtender/CompatibilityFrameworkConfig.json", cf_config),
        ],
    )
    results = audit_installed_mods([pak_path])
    markdown = write_compat_audit_markdown(results)
    assert "MyMod" in markdown
    assert PLACEHOLDER_GUID in markdown

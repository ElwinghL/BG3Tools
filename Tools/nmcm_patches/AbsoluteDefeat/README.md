# Absolute Defeat — NMCM Bridge

Pilot patch for `.claude/TODO.md` section 20b: gives the already-installed **Absolute Defeat** mod
(`BG3_Managed/Mods/AbsoluteDefeat.pak`) a second, NMCM-native configuration screen (gamepad/Honour
mode friendly), **without modifying Absolute Defeat's own `.pak`**. This is a separate mini-mod, its
own module UUID, that reads/writes into MCM's existing storage for Absolute Defeat's settings — the
exact same storage Absolute Defeat's own MCM page already reads via `Mods.BG3MCM.MCMAPI`.

Absolute Defeat keeps working exactly as before, MCM interface included. This is strictly additive.

---

## What it exposes

Read from Absolute Defeat's real `Mods/AbsoluteDefeat/MCM_blueprint.json` (inside `AbsoluteDefeat.pak`,
via `bg3_mod_tui/pak_reader.py`, not guessed):

| Blueprint setting | Type | NMCM control |
|---|---|---|
| `include_summons` | `checkbox`, default `false` | checkbox row |
| `downed_protection` | `checkbox`, default `true` | checkbox row |
| `debug_level` | `slider_int`, `Options.Min=0`, `Options.Max=2`, default `0` | numeric stepper, range re-scaled 0-2 (see below) |
| `btn_surrender` | `event_button` | button row, fire-and-forget |
| `btn_softlockfix` | `event_button` | button row, fire-and-forget |

## Identifiers

| | |
|---|---|
| Bridge module UUID | `4af12fa8-50e7-4a17-8ddc-8c6ef83df8c7` |
| Bridge module folder | `AbsoluteDefeat_NMCM_Bridge` |
| Absolute Defeat's real module UUID | `84a166e9-6a68-43a4-82f5-565ec14c349d` (read from its `meta.lsx`, not guessed) |
| MCM (BG3MCM) module UUID | `755a8a72-407f-4f0d-9a33-274ac0f0b53d` |
| NMCM module UUID | `ca8bfe06-88ec-a4e7-b49e-44eb5658f434`, folder `NMCM_ca8bfe06-88ec-a4e7-b49e-44eb5658f434`, minimum version **1.1.2** |

## Slot claim

Checked `Tools/bg3-nmcm/docs/slot-registry.md` before building (`git submodule` at the pinned commit
in this branch): slots 0-2 are taken (framework / Requiem for the Absolute / NMCM's own example mod),
**slot 3 is free**. This bridge claims **slot 3**:

- state name `NMCM_Slot3` (`GUI/StateMachines/Keyboard.xaml`)
- marker passive `NMCM_SLOT3_CLAIMED` (framework-provided, stamped by the goal)
- label handle `h90ab866dgb68fg4aafga9d6ge14977bcfbfa` (framework-provided, redeclared in
  `Localization/English/english.xml` as "Absolute Defeat (NMCM)")
- `PROC_NMCM_ClaimSlot(3, "AbsoluteDefeat_NMCM_Bridge")` in the goal

⚠️ This claim was **not** submitted as a pull request against the upstream `bg3-nmcm` repository (that
repository is a tracked third-party submodule, not part of this project) — it is only recorded here
and in the goal/state machine that actually enforce it. If this bridge is ever published, the slot
claim PR against `Luiznunes12/bg3-nmcm` (per `docs/slot-registry.md`'s own process) should be opened
before release, same spirit as the existing LSLib fork patches in this repo (documented locally,
never pushed without explicit review).

---

## Architecture

```
source/
  Mods/AbsoluteDefeat_NMCM_Bridge/
    meta.lsx                                   NMCM + MCM + Absolute Defeat dependencies
    GUI/StateMachines/Keyboard.xaml             claims NMCM_Slot3
    GUI/Pages/AbsoluteDefeat_NMCM.xaml           the screen: 2 checkboxes, 1 stepper, 2 buttons
    Localization/English/english.xml            slot label + all page text + comparison keys
    Story/RawFiles/Goals/AbsoluteDefeat_NMCM_Bridge.txt   all Osiris logic, one file
    ScriptExtender/Lua/BootstrapServer.lua       Osiris -> MCM bridge (checkboxes/slider) + relay trigger
    ScriptExtender/Lua/BootstrapClient.lua       relays the two event_buttons to Absolute Defeat's own channels
  Public/AbsoluteDefeat_NMCM_Bridge/
    Tutorials/TutorialEvents.lsx                8 TutorialEvent UUIDs the page fires
    ActionResourceDefinitions/ActionResourceDefinitions.lsx   ADNB_DebugG, mirrors debug_level
  Editor/Mods/AbsoluteDefeat_NMCM_Bridge/
    Stats/Stats/Passive.stats                   3 passives the page reads (2 markers + 1 carrier)
dist/
  AbsoluteDefeat_NMCM_Bridge.pak                built artifact (see "Building the .pak" below)
```

Assembled from `Tools/bg3-nmcm/examples/controls/page-skeleton.xaml` plus the `toggle`, `slider` and
`button` control examples, following `Tools/bg3-nmcm/docs/integration.md` step by step (dependency
declaration, slot claim, storage pattern, namespacing, the two easy-to-miss artifacts).

### The debug level stepper: 0-2, not 0-100

NMCM's own numeric control is built as "a bar from 0 to 100" (Action Resource mirror + stepper), but
Absolute Defeat's `debug_level` is `Options.Min=0`/`Options.Max=2`. The XAML's `LSProgressBar
Maximum` is a purely local display constant (the framework's own slider example warns that the
`ActionResourceDefinition`'s `MaxValue` is never the real ceiling either — writing moves it), so it
was re-scaled to `2`, `ActionResourceDefinition.MaxValue` set to `2`, and the goal's `IntegerMin/Max`
clamp uses `0`/`2` instead of `0`/`100`. Everything else (mirror-without-reading, floor-then-add,
party-wide carrier passive) follows the framework's documented law unchanged.

### Osiris side (`Story/RawFiles/Goals/AbsoluteDefeat_NMCM_Bridge.txt`)

- Subscribes to `PROC_NMCM_Boot()`: claims the slot, seeds/re-syncs both checkboxes and the debug
  level (positive **and** negative mirror halves), grants the debug carrier passive, enables all 8
  tutorial events per player, and fires `PROC_ADNB_RequestSync()` (see below).
- Two checkboxes share one generic 3-body guarded toggle (`PROC_ADNB_Toggle`), same law as NMCM's own
  reference control (`examples/controls/toggle`): body 1 turns on, body 2 turns off, body 3 (textually
  last) releases the busy guard.
- The debug stepper follows NMCM's own numeric reference control (`examples/controls/slider`)
  verbatim, range re-scaled as above.
- The two `event_button` rows carry no state: `IF TutorialEvent(...) THEN PROC_ADNB_Fire("btn_id")`.
- A `Reset` footer button (`ADNB_ACT_RESET`) restores Absolute Defeat's own blueprint defaults and
  pushes them to MCM the same way a normal click would. It never clears `NMCM_SLOT3_CLAIMED`.
- **Own addition beyond the minimal contract**: `PROC_ADNB_ApplySummons/ApplyDowned/ApplyDebug`, three
  PROCs with no internal caller in this file — they exist to be called **from Lua** (`Osi.PROC_ADNB_…`,
  documented under "Calling Osiris from Lua" in BG3SE's `API.md`) during the resync triggered by
  `PROC_ADNB_RequestSync()`, so this page's display always starts in sync with whatever Absolute
  Defeat's own native MCM page last set — not just with whatever this bridge's own page last set.

### Lua side (Script Extender)

BG3SE's `Ext.Osiris.RegisterListener(name, arity, "after", handler)` explicitly supports "user-defined
PROCs" (`API.md`, "Calling Lua from Osiris"), which is what lets `BootstrapServer.lua` capture the
goal's own custom PROCs without Absolute Defeat or MCM knowing this bridge exists:

- `PROC_ADNB_SyncSetting(STRING id, INTEGER value)` (arity 2) → `Mods.BG3MCM.MCMAPI:SetSettingValue(id,
  value, "84a166e9-…")`. Confirmed API: Absolute Defeat's own `Utils.MCMGet`
  (`ScriptExtender/Lua/Server/Helpers/Utils.lua`) and `MCMGet`
  (`ScriptExtender/Lua/Client/UIHelpers.lua`) both call
  `Mods.BG3MCM.MCMAPI:GetSettingValue(settingID, ModuleUUID)` — server **and** client side, so the
  write counterpart used here is a reasonable, symmetric extrapolation from BG3MCM's own documented
  API (https://wiki.bg3.community/Tutorials/Mod-Frameworks/mod-configuration-menu), not something
  literally found written out in Absolute Defeat's shipped Lua.
- `PROC_ADNB_Fire(STRING id)` (arity 1) → **not** a direct call (see below).
- `PROC_ADNB_RequestSync()` (arity 0) → reads the three current values via `MCMAPI:GetSettingValue`
  and pushes them back into Osiris via `Osi.PROC_ADNB_ApplySummons/ApplyDowned/ApplyDebug`.

**Why the buttons need a client-side relay (`BootstrapClient.lua`).** Absolute Defeat's own
`Client/UI.lua` registers `MCM.EventButton.RegisterCallback("btn_surrender"/"btn_softlockfix", …)`,
but that only fires for a click on **MCM's own IMGUI widget** — this bridge's NMCM page is a separate
widget tree and never reaches it. What that callback actually *does*, however, is directly usable:
`Ext.Net.PostMessageToServer("AD_Surrender", "")` / `("AD_AttemptSoftlockFix", "")`, answered by
Absolute Defeat's own `Server/SubscribedEvents.lua`
(`Ext.RegisterNetListener("AD_Surrender", AD.CmdSurrender)` /
`Ext.RegisterNetListener("AD_AttemptSoftlockFix", AD.SoftLockFix)`) — both confirmed by reading
Absolute Defeat's shipped Lua, not guessed. A server-registered `RegisterNetListener` only answers a
message that actually arrives **from a client** (confirmed in BG3SE's `API.md`, "Listening for
NetMessages"), and `PostMessageToServer` is only callable client-side, so `BootstrapServer.lua` (which
is where the Osiris listener necessarily lives — Osiris only runs server-side) cannot call Absolute
Defeat's channels directly. It broadcasts `ADNB_Relay_Fire` instead; `BootstrapClient.lua` picks it up
and re-posts on Absolute Defeat's exact channel names, gated by `Ext.Net.IsHost()` so a co-op session
does not fire the action once per connected client.

---

## Static verification performed

All of the following ran in this environment (no game, no toolkit):

- **Well-formed XML/XAML**: every `.lsx`/`.xaml`/`.xml`/`.stats` file under `source/` parses cleanly
  with Python's `xml.etree.ElementTree`.
- **No XML comment in the localisation file** (`Localization/English/english.xml`) — checked by
  substring search for `<!--`; an `<!-- … -->` there crashes the game on module load per
  `Tools/bg3-nmcm/docs/integration.md` section 7.
- **Cross-reference check** (script-driven, not eyeballed) between:
  - every `TutorialEvent` UUID fired from the XAML page and every UUID declared in
    `TutorialEvents.lsx` — exact match, no orphan on either side;
  - every loca handle referenced from XAML/`.lsx`/`.stats` and every handle declared in
    `english.xml` — exact match (two intentionally-reused vanilla handles, Back/Reset button text,
    excluded on purpose, same choice as `examples/example-mod`);
  - the marker passive `Name.Str` literals compared in the XAML's `DataTrigger`s against
    `Passive.stats`'s own `Name` fields — exact match (the carrier passive, `ADNB_DEBUG_CARRIER`, is
    correctly absent from the XAML: it is never compared, only granted);
  - the `TypeId` compared in the slider row's `DataTrigger` against
    `ActionResourceDefinitions.lsx`'s `Name` — exact match (`ADNB_DebugG`);
  - every `PROC_ADNB_*` called in the goal has either a declared body in the same file, or is one of
    the three deliberately Lua-captured signals (`PROC_ADNB_SyncSetting`, `PROC_ADNB_Fire`,
    `PROC_ADNB_RequestSync`) — confirmed via the same script.
- **Lua syntax**: `luac -p` (Lua 5.4) on both `BootstrapServer.lua` and `BootstrapClient.lua` — no
  parse errors.
- **`.pak` packaging**: built with Divine (`create-package` action, see below) and re-read two
  independent ways — Divine's own `list-package` action, and `bg3_mod_tui/pak_reader.py` (this
  project's native reader) — both report the expected 10 files and the correct module identity
  (`4af12fa8-50e7-4a17-8ddc-8c6ef83df8c7`, "Absolute Defeat - NMCM Bridge",
  `AbsoluteDefeat_NMCM_Bridge`).

What was **not** and **cannot** be verified without the toolkit or the game running: whether the goal
actually compiles against NMCM's real `PROC_NMCM_*` procedures (that requires the Story build step,
which needs the GPLex/GPPG-dependent parser this Linux LSLib fork build deliberately excludes — see
`.claude/TODO.md` section 19), and everything under "Manual testing checklist" below.

---

## Building the `.pak`

### 1. Build Divine (LSLib fork, Linux)

```bash
./scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh /tmp/lslib_fork_build
```

This applies **two** local-only patches (never pushed to `ElwinghL/lslib` without explicit review, see
the script's own header) on top of the fork's `main` (currently pinned at commit `551cff1`):

- `0001-linux-build-pak-only-scope.patch` (pre-existing, `.claude/TODO.md` 19a/19b): trims the
  solution to `Divine.csproj` + pak/resource I/O, dropping the MSVC-only `LSLibNative` (GR2/Granny)
  and the GPLex/GPPG-only Osiris Story/Goal parser.
- `0002-fix-linux-path-validation.patch` (**new, found while building this patch**):
  `Divine.CLI.CommandLineActions.TryToValidatePath` crashed with `System.InvalidOperationException:
  This operation is not supported for a relative URI` on **every** absolute Unix path passed to
  `-s`/`-d` — reproduced even on a throwaway `/tmp` folder unrelated to this mod, so this is a
  genuine, previously-undocumented Linux-porting bug in the fork's CLI argument validation, not
  something specific to this project. Root cause: `Uri.TryCreate(path, UriKind.RelativeOrAbsolute)`
  only recognises `IsFile` for a Windows drive/UNC path or an explicit `file://` URI; a Unix absolute
  path (`/tmp/x`) is parsed as a **relative** `Uri`, so `uri.IsFile` then throws. The patch drops the
  `Uri` detour entirely in favour of `Path.IsPathRooted(path)`, which is what the very next line
  (`Path.GetFullPath`) already relies on — same behaviour on Windows, fixed on Linux.

The result is `<clone_dir>/Divine/bin/Release/net8.0/Divine.dll`, run via `dotnet` (native, or through
the `bg3tools-dotnet` distrobox container this repo already uses elsewhere — see the script).

### 2. Stage the source tree off the `M2` mount before packaging

**Found while building this patch, undiagnosed root cause, but clearly isolated and reproducible**:
running `create-package` with `-s` pointed directly at a source tree living on the external `M2` mount
(`/run/media/system/M2/BG3Tools/…`, this whole project's own working copy) produces a `.pak` that
**both** Divine's own `list-package` action **and** `bg3_mod_tui/pak_reader.py` fail to read
(`[FATAL] Failed to list package: The position may not be greater or equal to the capacity of the
accessor` / `CorruptedPak: Décompression … échouée`) — reproduced with **every** compression method
tried (`none`, `zlib`; LZ4 also fails the same way). Bisected file-by-file: it is not any single file
in this mod (a `Mods/`-only, `Mods/+Public/`-only, and `Editor/`-only subset each package and list
correctly straight from the `M2` mount), and it is not a file-count threshold (a synthetic 13-file
tree on the same mount packages fine). Copying the **exact same** 10-file tree to a normal
filesystem (`/tmp`, tmpfs) before running `create-package` produces a fully valid, fully listable
`.pak` every time. Likely an mmap/file-read quirk specific to that mount under this .NET build, not
yet root-caused further. Practical workaround, applied to build the shipped `.pak`:

```bash
# Stage a plain copy off the M2 mount (only needed because of the mount quirk above).
mkdir -p /tmp/adnb_build
cp -r Tools/nmcm_patches/AbsoluteDefeat/src/{Mods,Public,Editor} /tmp/adnb_build/

DIVINE=/tmp/lslib_fork_build/Divine/bin/Release/net8.0/Divine.dll

# Package (zlib: readable by both Divine's own reader and bg3_mod_tui's, some compression).
distrobox enter bg3tools-dotnet -- dotnet "$DIVINE" \
    -g bg3 -s /tmp/adnb_build -d /tmp/adnb_build_out.pak -a create-package -c zlib

# Verify before shipping it.
distrobox enter bg3tools-dotnet -- dotnet "$DIVINE" -g bg3 -s /tmp/adnb_build_out.pak -a list-package

cp /tmp/adnb_build_out.pak Tools/nmcm_patches/AbsoluteDefeat/dist/AbsoluteDefeat_NMCM_Bridge.pak
```

(If `dotnet` is available natively, drop the `distrobox enter bg3tools-dotnet --` prefix.)

### 3. Re-verify with this project's own reader

```bash
python3 -c "
from pathlib import Path
from bg3_mod_tui.pak_reader import PakArchive, parse_meta_lsx_bytes
with PakArchive.open(Path('Tools/nmcm_patches/AbsoluteDefeat/dist/AbsoluteDefeat_NMCM_Bridge.pak')) as pak:
    for e in sorted(x.name for x in pak.entries): print(e)
    print(parse_meta_lsx_bytes(pak.read(pak.find_suffix('meta.lsx'))))
"
```

Expected: the 10 files listed under "Architecture" above, and
`('4af12fa8-50e7-4a17-8ddc-8c6ef83df8c7', 'Absolute Defeat - NMCM Bridge', 'AbsoluteDefeat_NMCM_Bridge')`.

---

## Installing it (for Elwingh to test)

1. Build (or use the already-built) `dist/AbsoluteDefeat_NMCM_Bridge.pak` above.
2. Copy it next to `AbsoluteDefeat.pak` in `BG3_Managed/Mods/`.
3. Add it to the active profile's mod order **after** MCM, NMCM, and Absolute Defeat itself (this
   mod's `meta.lsx` declares all three as dependencies, so any load-order tool that respects
   dependencies — including this project's own — should place it correctly on its own).
4. Launch the game, ESC → **Mod Configuration** → **Absolute Defeat (NMCM)**.

## Manual testing checklist (cannot be done here — no game running)

Mirrors `Tools/bg3-nmcm/docs/integration.md` section 8 ("Testing") and the framework's own
`log.txt`/`osirislog` guidance:

- [ ] The slot 3 entry appears in the NMCM hub, labelled "Absolute Defeat (NMCM)", with no slot-claim
      warning (would mean another installed mod also claims slot 3 — check
      `Tools/bg3-nmcm/docs/slot-registry.md` again if so).
- [ ] `log.txt` shows `CreateState NMCM_Slot3` when the entry is opened.
- [ ] Both checkboxes reflect Absolute Defeat's actual current MCM values the **first** time the page
      is opened in an existing save (tests the `PROC_ADNB_RequestSync` → `Mods.BG3MCM.MCMAPI:GetSettingValue`
      → `Osi.PROC_ADNB_Apply*` resync path) — toggle a setting from Absolute Defeat's own native MCM
      page first, then open this bridge's page and confirm it already shows the new value without
      being clicked here.
- [ ] Toggling either checkbox here changes the same value read back from Absolute Defeat's own MCM
      page (and vice versa).
- [ ] The debug level stepper moves in steps of 1 between 0 and 2, does not go outside that range, and
      the displayed number matches what `Utils.MCMGet("debug_level")` (Absolute Defeat's own code)
      would report — e.g. via the `debug` console command Absolute Defeat itself registers.
- [ ] **Surrender**: clicking it from this page ends combat the same way Absolute Defeat's own MCM
      button does. Test in an actual combat encounter, not from the main menu.
- [ ] **Emergency Stop**: clicking it from this page ends a stuck defeat scenario the same way
      Absolute Defeat's own MCM button does. Requires deliberately reaching a defeat scenario first.
- [ ] Co-op: with two clients connected, clicking Surrender/Emergency Stop from a **non-host** client's
      copy of this page still works exactly once (tests the `Ext.Net.IsHost()` guard in
      `BootstrapClient.lua` — expected to fire once regardless of which client clicked, since the
      relay always re-posts from the host's client only).
- [ ] Reset button restores Absolute Defeat's blueprint defaults (`include_summons=false`,
      `downed_protection=true`, `debug_level=0`) both on this page and on Absolute Defeat's own MCM
      page, and the slot 3 entry is still present afterwards (i.e. `NMCM_SLOT3_CLAIMED` was not
      cleared).
- [ ] A character created **before** this mod was installed still receives working clicks (tests
      `EnableTutorialEvent` being called for existing `DB_Players` at boot, not just at character
      creation) — load an existing save rather than starting a fresh one.
- [ ] Gamepad: not implemented (`GUI/StateMachines/Controller.xaml` / a `_c.xaml` page were not built
      for this pilot patch — keyboard-only is a documented, legitimate NMCM choice per
      `Tools/bg3-nmcm/README.md`, "keyboard only… your entry simply does not appear for a controller
      player"). If gamepad support is wanted later, it is a second, separate page + state machine, no
      change to the Osiris/Lua side.

## Known assumptions / not found literally in Absolute Defeat's shipped Lua

- `Mods.BG3MCM.MCMAPI:SetSettingValue(id, value, moduleUUID)` — the read counterpart
  (`GetSettingValue`) is confirmed used by Absolute Defeat itself, server and client side; the write
  form is BG3MCM's own documented API (see the Lua side section above) but was not seen literally
  called in Absolute Defeat's own shipped code (only a commented-out `IMGUIAPI:SetSettingValue` line).
  If it turns out to have a different signature in the installed BG3MCM version, `BootstrapServer.lua`
  is the only file that needs adjusting.
- The exact BG3MCM/NMCM version pinned in this project's `Tools/bg3-nmcm` submodule was assumed
  current with the published 1.1.2.x line the framework's own docs describe as minimum required.

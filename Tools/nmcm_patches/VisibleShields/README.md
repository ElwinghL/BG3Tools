# Visible Shields — NMCM Bridge

Second pilot patch for `.claude/TODO.md` section 20b: gives the already-installed **Visible Shields
- Universal** mod (`BG3_Managed/Mods/VisibleShieldsU.pak`) a second, NMCM-native configuration
screen (gamepad/Honour mode friendly), **without modifying Visible Shields Universal's own `.pak`**.
This is a separate mini-mod, its own module UUID, that reads/writes into MCM's existing storage for
Visible Shields Universal's settings — the exact same storage its own MCM page already reads via
`Mods.BG3MCM.MCMAPI` / its local `MCM.Get` helper.

Visible Shields Universal keeps working exactly as before, MCM interface included. This is strictly
additive. Same pattern, same precautions and the same author as the first pilot patch,
`Tools/nmcm_patches/AbsoluteDefeat/` (read in full before building this one).

---

## What it exposes

Read from Visible Shields Universal's real `Mods/VisibleShieldsU/MCM_blueprint.json` (inside
`VisibleShieldsU.pak`, via `bg3_mod_tui/pak_reader.py`, not guessed):

| Blueprint setting | Type | NMCM control |
|---|---|---|
| `share_mode` | `enum`, 3 fixed `Options.Choices`, default choice 0 | drop-down of 3 values |
| `debug_level` | `slider_int`, `Options.Min=0`, `Options.Max=2`, default `0` | numeric stepper, range 0-2 |

`share_mode`'s three choices, exactly as declared in the blueprint (double space around the slash is
part of the shipped string, not a typo):

1. `"Melee + shield  /  Ranged"` (default)
2. `"Melee + shield  /  Ranged + shield"`
3. `"Melee + ranged + shield  /  Melee + ranged + shield"`

**This is the first patch in this project to bridge an `enum` setting.** `Tools/bg3-nmcm/docs/
integration.md` section 7 documents exactly four native controls (button, checkbox, drop-down of N
values, and a 0-100 bar), and the drop-down (`Tools/bg3-nmcm/examples/controls/list/`) is precisely
NMCM's own answer to a fixed set of choices — used here instead of improvising a multi-radio
mechanism, per the framework's own reference control and law: "ONE UUID PER VALUE, not one per row.
[...] A selector implemented as a switch cycles between two values and never reaches the third."

## Identifiers

| | |
|---|---|
| Bridge module UUID | `d9f90e77-b06b-4f62-b777-7f31718e42e0` |
| Bridge module folder | `VisibleShields_NMCM_Bridge` |
| Visible Shields Universal's real module UUID | `8cc00893-60a1-4240-88fb-f0bf87b95e74` (read from its `meta.lsx`, not guessed) |
| MCM (BG3MCM) module UUID | `755a8a72-407f-4f0d-9a33-274ac0f0b53d` (dependency Version64 also read from Visible Shields Universal's own shipped `meta.lsx`) |
| NMCM module UUID | `ca8bfe06-88ec-a4e7-b49e-44eb5658f434`, folder `NMCM_ca8bfe06-88ec-a4e7-b49e-44eb5658f434`, minimum version **1.1.2** |

## Slot claim

Checked `Tools/bg3-nmcm/docs/slot-registry.md` before building (`git submodule` at the pinned commit
in this branch): slots 0-2 are taken (framework / Requiem for the Absolute / NMCM's own example mod).
**Slot 3 is already claimed locally by `AbsoluteDefeat_NMCM_Bridge`** (merged earlier in this
project, not yet submitted upstream — see that patch's own README), so this bridge claims the next
free one, **slot 4**:

- state name `NMCM_Slot4` (`GUI/StateMachines/Keyboard.xaml`)
- marker passive `NMCM_SLOT4_CLAIMED` (framework-provided, stamped by the goal)
- label handle `hc261d90cg81bag43c8g9c31g368cefe1e951` (framework's own table,
  `Tools/bg3-nmcm/docs/integration.md` section 4, redeclared in `Localization/English/english.xml`
  as "Visible Shields (NMCM)")
- `PROC_NMCM_ClaimSlot(4, "VisibleShields_NMCM_Bridge")` in the goal

⚠️ Same as `AbsoluteDefeat_NMCM_Bridge`: this claim was **not** submitted as a pull request against
the upstream `bg3-nmcm` repository (a tracked third-party submodule, not part of this project) — it
is only recorded here and in the goal/state machine that actually enforce it. If this bridge is ever
published, the slot claim PR against `Luiznunes12/bg3-nmcm` should be opened before release.

---

## Architecture

```
source/
  Mods/VisibleShields_NMCM_Bridge/
    meta.lsx                                    NMCM + MCM + Visible Shields Universal dependencies
    GUI/StateMachines/Keyboard.xaml              claims NMCM_Slot4
    GUI/Pages/VisibleShields_NMCM.xaml           the screen: 1 drop-down (3 values), 1 stepper
    Localization/English/english.xml             slot label + all page text + comparison keys
    Story/RawFiles/Goals/VisibleShields_NMCM_Bridge.txt   all Osiris logic, one file
    ScriptExtender/Lua/BootstrapServer.lua        Osiris -> MCM bridge (enum index -> string, slider)
  Public/VisibleShields_NMCM_Bridge/
    Tutorials/TutorialEvents.lsx                 7 TutorialEvent UUIDs the page fires
    ActionResourceDefinitions/ActionResourceDefinitions.lsx   VSNB_DebugG, mirrors debug_level
  Editor/Mods/VisibleShields_NMCM_Bridge/
    Stats/Stats/Passive.stats                    4 passives the page reads (3 share markers + 1 carrier)
dist/
  VisibleShields_NMCM_Bridge.pak                 built artifact (see "Building the .pak" below)
```

No `ScriptExtender/Lua/BootstrapClient.lua`: unlike Absolute Defeat, Visible Shields Universal's
blueprint has no `event_button` setting, so there is nothing to relay client -> server.

Assembled from `Tools/bg3-nmcm/examples/controls/page-skeleton.xaml` plus the `list` (drop-down) and
`slider` control examples, following `Tools/bg3-nmcm/docs/integration.md` step by step (dependency
declaration, slot claim, storage pattern, namespacing, the two easy-to-miss artifacts).

### The enum: MCM stores the raw choice STRING, not an index

Osiris facts only carry STRING/INTEGER, and "the third entry of an array" is not something Osiris
can express on its own, so the goal only ever carries `DB_VSNB_Share` as an **index** (0, 1, 2) into
`MCM_blueprint.json`'s `Options.Choices`. The conversion to and from the literal choice string lives
entirely in `BootstrapServer.lua`, and it was **not guessed**: reading Visible Shields Universal's
own shipped `BootstrapClient.lua` shows a `SHARE_CHOICE` lookup table keyed by the exact English
choice strings, with the comment *"MCM stores the raw English choice, so these keys survive
localisation"* — i.e. `Mods.BG3MCM.MCMAPI:SetSettingValue("share_mode", <value>, uuid)` must be
called with the choice **string**, not a number, or Visible Shields Universal's own reader will not
recognise it. The bridge's own reverse table also normalises whitespace on read
(`gsub("%s+", " ")`), the same defensive step Visible Shields Universal's own client code takes,
since the blueprint's choice strings carry a double space around the slash.

### The debug level stepper: 0-2, not 0-100

Same re-scaling already done for Absolute Defeat's own `debug_level`: the `LSProgressBar Maximum` is
a purely local display constant, so it was set to `2`, `ActionResourceDefinition.MaxValue` set to
`2`, and the goal's `IntegerMin/Max` clamp uses `0`/`2` instead of `0`/`100`. Everything else
(mirror-without-reading, floor-then-add, party-wide carrier passive) follows the framework's
documented law unchanged.

### Osiris side (`Story/RawFiles/Goals/VisibleShields_NMCM_Bridge.txt`)

- Subscribes to `PROC_NMCM_Boot()`: claims the slot, seeds/re-syncs both settings, grants the debug
  carrier passive, enables all 7 tutorial events per player, and fires `PROC_VSNB_RequestSync()`.
- `share_mode`'s three drop-down entries each fire their own `TutorialEvent`, read directly by
  `PROC_VSNB_ShareSet(0/1/2)` — no busy guard needed, direct selection is idempotent, exactly like
  NMCM's own list reference control (`examples/controls/list`). Each of the three bodies removes the
  OTHER two markers and lights its own last (the framework's documented law: removing and re-adding
  the SAME passive in one execution cancels out and the screen reads blank).
- The debug stepper follows NMCM's own numeric reference control (`examples/controls/slider`)
  verbatim, range re-scaled 0-2, identical in structure to `AbsoluteDefeat_NMCM_Bridge`'s own.
- A `Reset` footer button (`VSNB_ACT_RESET`) restores Visible Shields Universal's own blueprint
  defaults (`share_mode` index 0, `debug_level` 0) and pushes them to MCM the same way a normal click
  would. It never clears `NMCM_SLOT4_CLAIMED`.
- **Own addition beyond the minimal contract**: `PROC_VSNB_ApplyShare/ApplyDebug`, PROCs with no
  internal caller in this file — they exist to be called **from Lua** (`Osi.PROC_VSNB_…`) during the
  resync triggered by `PROC_VSNB_RequestSync()`, so this page's display always starts in sync with
  whatever Visible Shields Universal's own native MCM page last set.

### Lua side (Script Extender)

- `PROC_VSNB_SyncSetting(STRING id, INTEGER value)` (arity 2) → for `share_mode`, the INTEGER index
  is converted to the exact blueprint choice string before
  `Mods.BG3MCM.MCMAPI:SetSettingValue("share_mode", <string>, "8cc00893-…")`; for `debug_level`, the
  value is passed through unchanged. Same documented-but-unconfirmed `SetSettingValue` extrapolation
  already flagged in `AbsoluteDefeat_NMCM_Bridge`'s own README (the read counterpart is the one
  confirmed in Visible Shields Universal's own shipped Lua, via its local `MCM.Get` helper).
- `PROC_VSNB_RequestSync()` (arity 0) → reads the two current values via `MCMAPI:GetSettingValue`
  (converting the `share_mode` string back to an index via the same reverse table, whitespace
  normalised) and pushes them back into Osiris via `Osi.PROC_VSNB_ApplyShare/ApplyDebug`.

No client-side relay is needed here (unlike Absolute Defeat's Surrender/Emergency Stop buttons):
Visible Shields Universal's blueprint has no `event_button` setting, so `BootstrapServer.lua` is the
whole Lua side of this bridge.

---

## Static verification performed

All of the following ran in this environment (no game, no toolkit):

- **Well-formed XML/XAML**: every `.lsx`/`.xaml`/`.xml`/`.stats` file under `source/` parses cleanly
  with Python's `xml.etree.ElementTree`.
- **No XML comment in the localisation file** (`Localization/English/english.xml`) — checked by
  substring search for `<!--`.
- **No `--` inside any XAML comment** (illegal in XML comments, caught and fixed twice while
  writing this patch — once in the page, once in the state machine).
- **Cross-reference check** (script-driven, not eyeballed) between:
  - every `TutorialEvent` UUID fired from the XAML page and every UUID declared in
    `TutorialEvents.lsx` — exact match, no orphan on either side;
  - every fired UUID handled by a `TutorialEvent(_E, …)` clause in the goal, and every declared
    event `EnableTutorialEvent`'d per player at boot — exact match;
  - every loca handle referenced from XAML/`.lsx`/`.stats` and every handle declared in
    `english.xml` — exact match (two intentionally-reused vanilla handles, Back/Reset button text,
    excluded on purpose; the slot's own label handle is declared but not referenced from this
    module's own files, expected — it is read by the framework's hub, not by us);
  - the marker passive `Name.Str` literals compared in the XAML's `DataTrigger`s against
    `Passive.stats`'s own `Name` fields — exact match (the carrier passive, `VSNB_DEBUG_CARRIER`, is
    correctly absent from the XAML: it is never compared, only granted);
  - the `TypeId` compared in the stepper row's `DataTrigger` against
    `ActionResourceDefinitions.lsx`'s `Name` — exact match (`VSNB_DebugG`);
  - every `PROC_VSNB_*` called in the goal has either a declared body in the same file, or is one of
    the two deliberately Lua-captured signals (`PROC_VSNB_SyncSetting`, `PROC_VSNB_RequestSync`);
  - every `Osi.PROC_VSNB_Apply*` called from `BootstrapServer.lua` has a matching `PROC` body in the
    goal.
- **Lua syntax**: `luac -p` on `BootstrapServer.lua` — no parse errors.
- **`.pak` packaging**: built with Divine (`create-package` action, LSLib fork per
  `scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh`, which now applies both local-only
  Linux patches automatically) and re-read two independent ways — Divine's own `list-package`
  action, and `bg3_mod_tui/pak_reader.py` — both report the expected files and the correct module
  identity (`d9f90e77-b06b-4f62-b777-7f31718e42e0`, "Visible Shields - NMCM Bridge",
  `VisibleShields_NMCM_Bridge`).

What was **not** and **cannot** be verified without the toolkit or the game running: whether the goal
actually compiles against NMCM's real `PROC_NMCM_*` procedures (the Story build step needs the
GPLex/GPPG-dependent parser this Linux LSLib fork build deliberately excludes — `.claude/TODO.md`
section 19), and everything under "Manual testing checklist" below.

---

## Building the `.pak`

### 1. Build Divine (LSLib fork, Linux)

```bash
./scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh /tmp/lslib_fork_build
```

Unlike the first pilot patch, this now applies **both** local-only patches automatically (see the
script's own header) — no manual step needed for `0002-fix-linux-path-validation.patch` this time.

### 2. Stage the source tree off the `M2` mount before packaging

Same mount quirk already documented in `Tools/nmcm_patches/AbsoluteDefeat/README.md` ("Copying the
exact same file tree to a normal filesystem before running `create-package` produces a fully valid,
fully listable `.pak` every time"):

```bash
mkdir -p /tmp/vsnb_build
cp -r Tools/nmcm_patches/VisibleShields/src/{Mods,Public,Editor} /tmp/vsnb_build/

DIVINE=/tmp/lslib_fork_build/Divine/bin/Release/net8.0/Divine.dll

distrobox enter bg3tools-dotnet -- dotnet "$DIVINE" \
    -g bg3 -s /tmp/vsnb_build -d /tmp/vsnb_build_out.pak -a create-package -c zlib

distrobox enter bg3tools-dotnet -- dotnet "$DIVINE" -g bg3 -s /tmp/vsnb_build_out.pak -a list-package

cp /tmp/vsnb_build_out.pak Tools/nmcm_patches/VisibleShields/dist/VisibleShields_NMCM_Bridge.pak
```

(If `dotnet` is available natively, drop the `distrobox enter bg3tools-dotnet --` prefix.)

### 3. Re-verify with this project's own reader

```bash
python3 -c "
from pathlib import Path
from bg3_mod_tui.pak_reader import PakArchive, parse_meta_lsx_bytes
with PakArchive.open(Path('Tools/nmcm_patches/VisibleShields/dist/VisibleShields_NMCM_Bridge.pak')) as pak:
    for e in sorted(x.name for x in pak.entries): print(e)
    print(parse_meta_lsx_bytes(pak.read(pak.find_suffix('meta.lsx'))))
"
```

Expected: the files listed under "Architecture" above, and
`('d9f90e77-b06b-4f62-b777-7f31718e42e0', 'Visible Shields - NMCM Bridge', 'VisibleShields_NMCM_Bridge')`.

---

## Installing it (for Elwingh to test)

1. Build (or use the already-built) `dist/VisibleShields_NMCM_Bridge.pak` above.
2. Copy it next to `VisibleShieldsU.pak` in `BG3_Managed/Mods/`.
3. Add it to the active profile's mod order **after** MCM, NMCM, and Visible Shields Universal itself
   (this mod's `meta.lsx` declares all three as dependencies, so any load-order tool that respects
   dependencies — including this project's own — should place it correctly on its own).
4. Launch the game, ESC → **Mod Configuration** → **Visible Shields (NMCM)**.

## Manual testing checklist (cannot be done here — no game running)

Mirrors `Tools/bg3-nmcm/docs/integration.md` section 8 ("Testing") and
`Tools/nmcm_patches/AbsoluteDefeat/README.md`'s own checklist:

- [ ] The slot 4 entry appears in the NMCM hub, labelled "Visible Shields (NMCM)", with no slot-claim
      warning (would mean another installed mod also claims slot 4 — check
      `Tools/bg3-nmcm/docs/slot-registry.md` again if so).
- [ ] `log.txt` shows `CreateState NMCM_Slot4` when the entry is opened.
- [ ] The drop-down reflects Visible Shields Universal's actual current MCM `share_mode` value the
      **first** time the page is opened in an existing save (tests the `PROC_VSNB_RequestSync` →
      `Mods.BG3MCM.MCMAPI:GetSettingValue` → `Osi.PROC_VSNB_ApplyShare` resync path, string-to-index
      conversion included) — change the setting from Visible Shields Universal's own native MCM page
      first, then open this bridge's page and confirm it already shows the new value without being
      clicked here.
- [ ] Picking any of the 3 drop-down entries here changes the same value read back from Visible
      Shields Universal's own MCM page (and vice versa), and the **visual effect actually changes**
      in game (shield showing/hiding on the back per the chosen mode) — this is the one check that
      also validates the enum index → exact blueprint string conversion end to end, not just the
      Osiris/MCM plumbing.
- [ ] The debug level stepper moves in steps of 1 between 0 and 2, does not go outside that range,
      and the displayed number matches what Visible Shields Universal's own debug logging responds
      to (its console command `vsus_log <mode>` reports the level, or watch `[VSU/S]`/`[VSU/C]`
      log lines for the verbosity change).
- [ ] Reset button restores Visible Shields Universal's blueprint defaults (`share_mode` = "Melee +
      shield  /  Ranged", `debug_level` = 0) both on this page and on Visible Shields Universal's own
      MCM page, and the slot 4 entry is still present afterwards (i.e. `NMCM_SLOT4_CLAIMED` was not
      cleared).
- [ ] A character created **before** this mod was installed still receives working clicks (tests
      `EnableTutorialEvent` being called for existing `DB_Players` at boot, not just at character
      creation) — load an existing save rather than starting a fresh one.
- [ ] Co-op: the drop-down and stepper write into MCM's party-agnostic storage the same way Visible
      Shields Universal's own page does; there is no per-client relay in this bridge to test (no
      `event_button` setting here), unlike Absolute Defeat's Surrender/Emergency Stop.
- [ ] Gamepad: not implemented (`GUI/StateMachines/Controller.xaml` / a `_c.xaml` page were not built
      for this pilot patch — keyboard-only is a documented, legitimate NMCM choice, same decision
      already made for `AbsoluteDefeat_NMCM_Bridge`). If gamepad support is wanted later, it is a
      second, separate page + state machine, no change to the Osiris/Lua side.

## Known assumptions / not found literally in Visible Shields Universal's shipped Lua

- `Mods.BG3MCM.MCMAPI:SetSettingValue(id, value, moduleUUID)` — same assumption already flagged in
  `AbsoluteDefeat_NMCM_Bridge`'s own README: the read counterpart is confirmed used by Visible
  Shields Universal itself (through its local `MCM.Get` helper), the write form is BG3MCM's own
  documented API but was not seen literally called in Visible Shields Universal's own shipped code.
  If it turns out to have a different signature in the installed BG3MCM version, `BootstrapServer.lua`
  is the only file that needs adjusting.
- **That MCM stores an enum setting's value as the exact choice string** — this one, unlike the
  point above, WAS confirmed by reading Visible Shields Universal's own shipped
  `BootstrapClient.lua` (the `SHARE_CHOICE` table and its comment), not assumed. Documented here
  because it is the load-bearing fact this whole enum bridge depends on, and because it directly
  contradicts what someone might otherwise guess (that MCM stores the numeric index like a normal
  Osiris fact would).
- The exact BG3MCM/NMCM version pinned in this project's `Tools/bg3-nmcm` submodule was assumed
  current with the published 1.1.2.x line the framework's own docs describe as minimum required
  (same assumption as the first pilot patch).

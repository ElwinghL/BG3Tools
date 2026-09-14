-- VisibleShields_NMCM_Bridge :: server-side Lua/Osiris bridge.
--
-- The NMCM page (GUI/Pages/VisibleShields_NMCM.xaml) can only reach Osiris: NMCM's contract gives a
-- control's Click no route to Lua directly (see Tools/bg3-nmcm/docs/integration.md section 7), only
-- a TutorialEvent that the goal (Story/RawFiles/Goals/VisibleShields_NMCM_Bridge.txt) picks up. That
-- goal calls three of its own top-level PROCs whenever something changes, and THIS file listens for
-- those via Ext.Osiris.RegisterListener (documented under "Calling Lua from Osiris" in BG3SE's
-- API.md: "It currently supports capturing events, built-in queries, databases, user-defined PROCs
-- and user-defined QRYs.") to forward the change into Visible Shields Universal's own MCM storage,
-- exactly as if the player had used Visible Shields Universal's native MCM page instead of this
-- NMCM one.
--
-- Visible Shields Universal's own module UUID, read from its real meta.lsx (Mods/VisibleShieldsU/
-- meta.lsx inside VisibleShieldsU.pak), not guessed:
local VISIBLE_SHIELDS_UUID = "8cc00893-60a1-4240-88fb-f0bf87b95e74"

-- share_mode is an "enum" setting in Visible Shields Universal's own MCM_blueprint.json, with three
-- fixed Options.Choices. Confirmed by reading Visible Shields Universal's own shipped Lua
-- (ScriptExtender/Lua/BootstrapClient.lua, the SHARE_CHOICE table and its comment "MCM stores the
-- raw English choice, so these keys survive localisation"): MCM stores the EXACT CHOICE STRING for
-- an enum setting, not its index. This bridge's own goal only ever carries the INDEX (0,1,2) as an
-- Osiris INTEGER (Osiris has no notion of "the third string in an array"), so this table is what
-- turns that index back into the literal string MCM_blueprint.json declares before it is written
-- through MCMAPI:SetSettingValue. Spacing matters here on the way OUT (double space around the
-- slash, copied verbatim from the blueprint's own Options.Choices) because Visible Shields
-- Universal's own reader normalises whitespace on the way IN
-- (`tostring(v):gsub("%s+", " ")` in its BootstrapClient.lua), so writing the padded form it ships
-- with is the safest, most literal choice.
local SHARE_MODE_CHOICES = {
    [0] = "Melee + shield  /  Ranged",
    [1] = "Melee + shield  /  Ranged + shield",
    [2] = "Melee + ranged + shield  /  Melee + ranged + shield",
}

-- Reverse table, whitespace-normalised the same way Visible Shields Universal's own client code
-- does, so a value read back from MCM (however it happens to be spaced) still maps to the right
-- index during PROC_VSNB_RequestSync below.
local SHARE_MODE_INDEX = {}
for index, choice in pairs(SHARE_MODE_CHOICES) do
    SHARE_MODE_INDEX[(choice:gsub("%s+", " "))] = index
end

-- Confirmed by reading Visible Shields Universal's own Lua (BootstrapClient.lua, BootstrapServer.lua):
-- both read their settings through a local `MCM.Get(id)` helper (itself backed by
-- `Mods.BG3MCM.MCMAPI:GetSettingValue`, same convention documented at
-- https://wiki.bg3.community/Tutorials/Mod-Frameworks/mod-configuration-menu). The write side,
-- `Mods.BG3MCM.MCMAPI:SetSettingValue(settingID, value, ModuleUUID)`, is BG3MCM's documented
-- counterpart and was not found literally called anywhere in Visible Shields Universal's own shipped
-- Lua -- this call is therefore this bridge's own addition, exactly the same extrapolation already
-- made (and already flagged as such) by AbsoluteDefeat_NMCM_Bridge's own BootstrapServer.lua.
local function McmSet(settingId, value)
    if not Mods.BG3MCM or not Mods.BG3MCM.MCMAPI then
        Ext.Utils.PrintWarning("[VisibleShields_NMCM_Bridge] Mods.BG3MCM.MCMAPI not available yet, dropping SetSettingValue(" .. tostring(settingId) .. ")")
        return
    end
    Mods.BG3MCM.MCMAPI:SetSettingValue(settingId, value, VISIBLE_SHIELDS_UUID)
end

local function McmGet(settingId)
    if not Mods.BG3MCM or not Mods.BG3MCM.MCMAPI then
        return nil
    end
    return Mods.BG3MCM.MCMAPI:GetSettingValue(settingId, VISIBLE_SHIELDS_UUID)
end

-- share_mode (INTEGER index 0-2, converted to its exact blueprint string below) and debug_level
-- (INTEGER, passed through unchanged) both funnel through this single PROC, arity 2:
-- (STRING settingId, INTEGER value).
Ext.Osiris.RegisterListener("PROC_VSNB_SyncSetting", 2, "after", function(settingId, value)
    if settingId == "share_mode" then
        local choice = SHARE_MODE_CHOICES[value]
        if choice == nil then
            Ext.Utils.PrintWarning("[VisibleShields_NMCM_Bridge] share_mode index out of range: " .. tostring(value))
            return
        end
        McmSet("share_mode", choice)
        return
    end
    McmSet(settingId, value)
end)

-- Zero-arity signal, fired from the goal's own PROC_NMCM_Boot() body: a good moment to pull Visible
-- Shields Universal's REAL current MCM values and push them back into this bridge's own Osiris DB
-- facts/markers (Osi.PROC_VSNB_ApplyShare/ApplyDebug -- "Calling Osiris from Lua", BG3SE API.md), so
-- the NMCM page reflects whatever Visible Shields Universal's native MCM page last set, even in a
-- session where this bridge's own page was never opened before.
Ext.Osiris.RegisterListener("PROC_VSNB_RequestSync", 0, "after", function()
    local shareRaw = McmGet("share_mode")
    local debugLevel = McmGet("debug_level")

    if shareRaw ~= nil then
        local index = SHARE_MODE_INDEX[(tostring(shareRaw):gsub("%s+", " "))]
        if index ~= nil then
            Osi.PROC_VSNB_ApplyShare(index)
        else
            Ext.Utils.PrintWarning("[VisibleShields_NMCM_Bridge] share_mode value not recognised: " .. tostring(shareRaw))
        end
    end
    if debugLevel ~= nil then
        Osi.PROC_VSNB_ApplyDebug(math.floor(debugLevel))
    end
end)

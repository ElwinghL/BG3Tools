-- AbsoluteDefeat_NMCM_Bridge :: server-side Lua/Osiris bridge.
--
-- The NMCM page (GUI/Pages/AbsoluteDefeat_NMCM.xaml) can only reach Osiris: NMCM's contract gives a
-- control's Click no route to Lua directly (see Tools/bg3-nmcm/docs/integration.md section 7), only
-- a TutorialEvent that the goal (Story/RawFiles/Goals/AbsoluteDefeat_NMCM_Bridge.txt) picks up. That
-- goal calls three of its own top-level PROCs whenever something changes, and THIS file listens for
-- those via Ext.Osiris.RegisterListener (documented under "Calling Lua from Osiris" in BG3SE's
-- API.md: "It currently supports capturing events, built-in queries, databases, user-defined PROCs
-- and user-defined QRYs.") to forward the change into Absolute Defeat's own MCM storage, exactly as
-- if the player had used Absolute Defeat's native MCM page instead of this NMCM one.
--
-- Absolute Defeat's own module UUID, read from its real meta.lsx (Mods/AbsoluteDefeat/meta.lsx
-- inside AbsoluteDefeat.pak), not guessed:
local ABSOLUTE_DEFEAT_UUID = "84a166e9-6a68-43a4-82f5-565ec14c349d"

-- Confirmed by reading Absolute Defeat's own Lua (ScriptExtender/Lua/Server/Helpers/Utils.lua,
-- ScriptExtender/Lua/Client/UIHelpers.lua): both read their own settings through
-- `Mods.BG3MCM.MCMAPI:GetSettingValue(settingID, ModuleUUID)`. The write side,
-- `Mods.BG3MCM.MCMAPI:SetSettingValue(settingID, value, ModuleUUID)`, is BG3MCM's documented
-- counterpart (see https://wiki.bg3.community/Tutorials/Mod-Frameworks/mod-configuration-menu) and
-- was not found literally called anywhere in Absolute Defeat's own shipped Lua (only a commented-out
-- IMGUIAPI:SetSettingValue line in Client/UI.lua) -- this call is therefore this bridge's own
-- addition, not something copied from Absolute Defeat.
local function McmSet(settingId, value)
    if not Mods.BG3MCM or not Mods.BG3MCM.MCMAPI then
        Ext.Utils.PrintWarning("[AbsoluteDefeat_NMCM_Bridge] Mods.BG3MCM.MCMAPI not available yet, dropping SetSettingValue(" .. tostring(settingId) .. ")")
        return
    end
    Mods.BG3MCM.MCMAPI:SetSettingValue(settingId, value, ABSOLUTE_DEFEAT_UUID)
end

local function McmGet(settingId)
    if not Mods.BG3MCM or not Mods.BG3MCM.MCMAPI then
        return nil
    end
    return Mods.BG3MCM.MCMAPI:GetSettingValue(settingId, ABSOLUTE_DEFEAT_UUID)
end

-- Checkboxes ("include_summons", "downed_protection") and the debug level stepper
-- ("debug_level") all funnel through this single PROC, arity 2: (STRING settingId, INTEGER value).
Ext.Osiris.RegisterListener("PROC_ADNB_SyncSetting", 2, "after", function(settingId, value)
    -- Osiris INTEGER 0/1 -> Lua boolean for the two checkboxes; debug_level stays a plain number.
    local luaValue = value
    if settingId == "include_summons" or settingId == "downed_protection" then
        luaValue = (value == 1)
    end
    McmSet(settingId, luaValue)
end)

-- The two event_button rows ("btn_surrender", "btn_softlockfix") carry no value, arity 1.
--
-- Absolute Defeat's own event_button wiring (Client/UI.lua) registers
-- `MCM.EventButton.RegisterCallback("btn_surrender", ...)`, which only fires when the click comes
-- from MCM's own IMGUI widget -- our NMCM page is a separate widget tree and never reaches that
-- callback. What Absolute Defeat's callback itself does, however, is the real hook:
--   AD_Surrender()       -> Ext.Net.PostMessageToServer("AD_Surrender", "")
--   AD_AttemptSoftlockFix() -> Ext.Net.PostMessageToServer("AD_AttemptSoftlockFix", "")
-- and Absolute Defeat's own Server/SubscribedEvents.lua answers both channels with
-- `Ext.RegisterNetListener("AD_Surrender", AD.CmdSurrender)` /
-- `Ext.RegisterNetListener("AD_AttemptSoftlockFix", AD.SoftLockFix)`.
-- A server-registered NetListener only fires for a message that actually arrives FROM a client
-- (confirmed in BG3SE's API.md, "Listening for NetMessages": a server-side RegisterNetListener
-- answers client -> server traffic), and PostMessageToServer must be called client-side, so this
-- server-side Osiris listener cannot call AD's channels directly. It relays to
-- BootstrapClient.lua instead, which re-posts on Absolute Defeat's own channel names, restricted to
-- the host's client (Ext.Net.IsHost()) so a co-op session does not fire the action once per
-- connected player.
Ext.Osiris.RegisterListener("PROC_ADNB_Fire", 1, "after", function(settingId)
    Ext.Net.BroadcastMessage("ADNB_Relay_Fire", Ext.Json.Stringify({ Id = settingId }))
end)

-- Zero-arity signal, fired from the goal's own PROC_NMCM_Boot() body: a good moment to pull
-- Absolute Defeat's REAL current MCM values and push them back into this bridge's own Osiris DB
-- facts/markers (Osi.PROC_ADNB_ApplySummons/ApplyDowned/ApplyDebug -- "Calling Osiris from Lua",
-- BG3SE API.md), so the NMCM page reflects whatever Absolute Defeat's native MCM page last set,
-- even in a session where this bridge's own page was never opened before.
Ext.Osiris.RegisterListener("PROC_ADNB_RequestSync", 0, "after", function()
    local summons = McmGet("include_summons")
    local downed = McmGet("downed_protection")
    local debugLevel = McmGet("debug_level")

    if summons ~= nil then
        Osi.PROC_ADNB_ApplySummons(summons and 1 or 0)
    end
    if downed ~= nil then
        Osi.PROC_ADNB_ApplyDowned(downed and 1 or 0)
    end
    if debugLevel ~= nil then
        Osi.PROC_ADNB_ApplyDebug(math.floor(debugLevel))
    end
end)

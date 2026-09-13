-- AbsoluteDefeat_NMCM_Bridge :: client-side relay for the two event_button rows.
--
-- Absolute Defeat's own button handlers (Client/UI.lua) call Ext.Net.PostMessageToServer, which is
-- only callable from client-side Lua, and its own server listeners
-- (Ext.RegisterNetListener("AD_Surrender"/"AD_AttemptSoftlockFix", ...)) only answer messages that
-- actually arrive from a client. BootstrapServer.lua cannot call them directly for that reason, and
-- relays here instead over this bridge's own channel.
--
-- Guarded with Ext.Net.IsHost() so that in a co-op session only the host's client re-posts on
-- Absolute Defeat's channel -- without this guard every connected client would relay independently
-- and the action (surrender / emergency stop) would fire once per connected player.
Ext.RegisterNetListener("ADNB_Relay_Fire", function(_channel, payload)
    if not Ext.Net.IsHost() then
        return
    end

    local ok, data = pcall(Ext.Json.Parse, payload)
    if not ok or not data or not data.Id then
        return
    end

    if data.Id == "btn_surrender" then
        Ext.Net.PostMessageToServer("AD_Surrender", "")
    elseif data.Id == "btn_softlockfix" then
        Ext.Net.PostMessageToServer("AD_AttemptSoftlockFix", "")
    end
end)

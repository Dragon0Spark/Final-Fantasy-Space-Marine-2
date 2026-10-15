-- Read-only FFVII integration probe. Never reports gameplay success.
local Probe = {
    Prefix = "[TitusProbe] ",
    LastEquipment = {},
    PollCount = 0,
    Pending = false,
    Hooked = {},
}

function Probe:Log(message)
    print(self.Prefix .. message .. "\n")
end

function Probe:Describe(parameter)
    local ok, value = pcall(function() return parameter:get() end)
    if not ok then return "unreadable" end
    if type(value) == "number" or type(value) == "boolean" then
        return tostring(value)
    end
    return type(value)
end

function Probe:RegisterCombatHooks()
    local names = {"OnGiveDamage", "OnTakeDamage", "OnBurstBegin", "OnATBLightAttackEvent"}
    for _, name in ipairs(names) do
        if not self.Hooked[name] then
            local path = "/Script/EndGame.EndBattleAIController:" .. name
            local target = StaticFindObject(path)
            if target and target:IsValid() then
                local ok = pcall(function()
                    RegisterHook(path, function(_, ...)
                        local parts = {}
                        for index, parameter in ipairs({...}) do
                            if index > 3 then break end
                            parts[#parts + 1] = self:Describe(parameter)
                        end
                        self:Log("observed " .. name .. " " .. table.concat(parts, " "))
                    end)
                end)
                if ok then
                    self.Hooked[name] = true
                    self:Log("registered " .. name .. "; observation still required")
                end
            end
        end
    end
end

function Probe:ReadEquipment(api, category, label)
    local ok, identity = pcall(function()
        local equipment = api:BPGetCurrentEquipment(0, category)
        return tostring(equipment.UniqueID) .. ":" .. tostring(equipment.UniqueIndex)
    end)
    if ok and identity ~= self.LastEquipment[label] then
        self:Log("equipment " .. label .. " " .. identity)
        self.LastEquipment[label] = identity
    end
    if not ok and self.PollCount == 1 then
        self:Log("equipment " .. label .. " unavailable; runtime API not verified")
    end
end

function Probe:Poll()
    self.PollCount = self.PollCount + 1
    self:RegisterCombatHooks()
    local api = StaticFindObject("/Script/EndGame.Default__EndMenuBPAPI")
    if not api or not api:IsValid() then return end
    local ok, hp = pcall(function() return api:BPGetPlayerHP(0) end)
    if not ok or type(hp) ~= "number" or hp <= 0 then return end
    self:ReadEquipment(api, 0, "weapon")
    self:ReadEquipment(api, 2, "accessory")
    if self.PollCount % 10 == 0 then
        self:Log("host state readable; hp=" .. tostring(hp) .. "; mashup gameplay unverified")
    end
end

-- Serialize UObject reads onto the game thread; do not dump all objects.
LoopAsync(1000, function()
    if not Probe.Pending then
        Probe.Pending = true
        ExecuteInGameThread(function()
            local ok = pcall(function() Probe:Poll() end)
            if not ok then Probe:Log("poll unavailable; retrying next tick") end
            Probe.Pending = false
        end)
    end
    return false
end)

Probe:Log("read-only diagnostics loaded; no gameplay features implemented here")

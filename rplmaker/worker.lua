-- Runs inside the checking copy of REAPER (never the person's own REAPER).
-- Waits for job files in <resource>/rplmaker/jobs, does each, writes <job>.out then <job>.done.
-- Job file, first line, tab separated:
--   CAPTURE  fxname                 the plug-in's default state, preset file name, parameter count
--   VERIFY   fxname  n  start       step through presets start..n-1 of those REAPER lists; per preset
--                                   the name REAPER reports, every parameter, and the state the
--                                   plug-in saves back
--   TOUCH    folder                 open a folder, so macOS asks now (once) whether this copy may
--   QUIT
local base = reaper.GetResourcePath() .. "/rplmaker"
local jobs = base .. "/jobs"
local function exists(p) local f = io.open(p, "r"); if f then f:close(); return true end return false end
local function touch(p) local f = io.open(p, "w"); if f then f:close() end end

-- nothing this copy does should ever make a sound
reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "B_MUTE", 1)
reaper.SetMediaTrackInfo_Value(reaper.GetMasterTrack(0), "D_VOL", 0)
reaper.InsertTrackAtIndex(0, false)
local tr = reaper.GetTrack(0, 0)
reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 1)
reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
touch(base .. "/ready")

local function vstblock()
  local _, chunk = reaper.GetTrackStateChunk(tr, "", false)
  local head, body = chunk:match("\n(<VST[^\n]*)\n(.-)\n%s*>")
  local t = {}
  for l in (body or ""):gmatch("[^\n]+") do t[#t + 1] = l:gsub("%s", "") end
  return head or "", t
end

local function params(fx)
  local pv = {}
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    pv[#pv + 1] = string.format("%.6f", reaper.TrackFX_GetParamNormalized(tr, fx, p))
  end
  return table.concat(pv, ",")
end

local function capture(o, fxname)
  local fx = reaper.TrackFX_AddByName(tr, fxname, false, -1)
  if fx < 0 then o:write("ADDFAIL\n") return end
  local head, lines = vstblock()
  o:write("HEAD\t", head, "\n")
  o:write("STATE\t", table.concat(lines, "|"), "\n")
  o:write("FILE\t", reaper.TrackFX_GetUserPresetFilename(tr, fx) or "", "\n")
  local _, cnt = reaper.TrackFX_GetPresetIndex(tr, fx)
  o:write("COUNT\t", cnt, "\n")
  o:write("PARAMS\t", reaper.TrackFX_GetNumParams(tr, fx), "\n")
  o:write("PV\t", params(fx), "\n")
  reaper.TrackFX_Delete(tr, fx)
end

local function verify(o, fxname, n, start)
  local fx = reaper.TrackFX_AddByName(tr, fxname, false, -1)
  if fx < 0 then o:write("ADDFAIL\n") return end
  local _, cnt = reaper.TrackFX_GetPresetIndex(tr, fx)
  o:write("COUNT\t", cnt, "\n")
  for k = start, math.min(n, cnt) - 1 do
    local okset = reaper.TrackFX_SetPresetByIndex(tr, fx, k)
    local _, pname = reaper.TrackFX_GetPreset(tr, fx, "")
    local cur = reaper.TrackFX_GetPresetIndex(tr, fx)
    local _, lines = vstblock()
    o:write("P\t", k, "\t", tostring(okset), "\t", cur, "\t", (pname or ""):gsub("[\t\n]", " "), "\t",
            params(fx), "\t", table.concat(lines, "|"), "\n")
    o:flush()
  end
  reaper.TrackFX_Delete(tr, fx)
end

local function nextjob()
  local best
  reaper.EnumerateFiles(jobs, -1)  -- REAPER caches folder listings; ask it to look again
  local i = 0
  while true do
    local f = reaper.EnumerateFiles(jobs, i)
    if not f then break end
    local n = f:match("^job%-(%d+)%.txt$")
    if n and (not best or tonumber(n) < best) then best = tonumber(n) end
    i = i + 1
  end
  return best
end

local function loop()
  local n = nextjob()
  if n then
    local path = string.format("%s/job-%d.txt", jobs, n)
    local fh = io.open(path, "r")
    local line = fh and fh:read("l") or ""
    if fh then fh:close() end
    if line == "" then reaper.defer(loop) return end  -- not readable yet: look again next time
    os.remove(path)
    local kind, a, b, c = line:match("^(%u+)\t?([^\t]*)\t?([^\t]*)\t?([^\t]*)")
    local out = string.format("%s/job-%d.out", jobs, n)
    local o = io.open(out, "w")
    if kind == "QUIT" then
      o:write("BYE\n") o:close() touch(out:gsub("%.out$", ".done"))
      return  -- the app ends this copy of REAPER itself
    elseif kind == "CAPTURE" then capture(o, a)
    elseif kind == "TOUCH" then
      reaper.EnumerateFiles(a, -1)
      local f = reaper.EnumerateFiles(a, 0) or reaper.EnumerateSubdirectories(a, 0)
      o:write("OK\t", tostring(f ~= nil), "\n")
    elseif kind == "VERIFY" then verify(o, a, tonumber(b) or 0, tonumber(c) or 0)
    else o:write("UNKNOWN\t", line, "\n") end
    o:write("END\n")
    o:close()
    touch(string.format("%s/job-%d.done", jobs, n))
  end
  reaper.defer(loop)
end
reaper.defer(loop)

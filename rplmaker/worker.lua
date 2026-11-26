-- Runs inside the checking copy of REAPER (never the person's own REAPER).
-- Waits for job files in <resource>/rplmaker/jobs, does each, writes <job>.out then <job>.done.
-- Job file, first line, tab separated:
--   CAPTURE  fxname [settle]        the plug-in's default state, preset file name, parameter count
--   VERIFY   fxname  n  start [settle]  step through presets start..n-1 of those REAPER lists; per
--                                   preset the name REAPER reports, every parameter, and the state
--                                   the plug-in saves back. settle: seconds to let REAPER run between
--                                   choosing a preset and reading it back, for plug-ins that apply a
--                                   preset on their own timer rather than at once (0: at once)
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

local wait   -- below

local function capture(o, fxname, settle)
  local fx = reaper.TrackFX_AddByName(tr, fxname, false, -1)
  if fx < 0 then o:write("ADDFAIL\n") return end
  wait(settle or 0)   -- some plug-ins finish setting themselves up on a timer
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

-- a job runs as a coroutine: waiting (settle) yields to REAPER, which keeps running the
-- plug-in's timers and messages, and the next job waits until this one has finished
function wait(seconds)
  if seconds <= 0 then return end
  local t = reaper.time_precise()
  while reaper.time_precise() - t < seconds do coroutine.yield() end
end

local function verify(o, fxname, n, start, settle)
  local fx = reaper.TrackFX_AddByName(tr, fxname, false, -1)
  if fx < 0 then o:write("ADDFAIL\n") return end
  local _, cnt = reaper.TrackFX_GetPresetIndex(tr, fx)
  o:write("COUNT\t", cnt, "\n")
  for k = start, math.min(n, cnt) - 1 do
    local okset = reaper.TrackFX_SetPresetByIndex(tr, fx, k)
    wait(settle)
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

local running   -- the job being done: {co = coroutine, o = output file, n = job number}

local function finish(job)
  job.o:write("END\n")
  job.o:close()
  touch(string.format("%s/job-%d.done", jobs, job.n))
end

local function loop()
  if running then
    local ok, err = coroutine.resume(running.co)
    if not ok then running.o:write("ERROR\t", tostring(err):gsub("[\t\n]", " "), "\n") end
    if coroutine.status(running.co) == "dead" then
      finish(running)
      running = nil
    end
    reaper.defer(loop)
    return
  end
  local n = nextjob()
  if n then
    local path = string.format("%s/job-%d.txt", jobs, n)
    local fh = io.open(path, "r")
    local line = fh and fh:read("l") or ""
    if fh then fh:close() end
    if line == "" then reaper.defer(loop) return end  -- not readable yet: look again next time
    os.remove(path)
    local kind, a, b, c, d = line:match("^(%u+)\t?([^\t]*)\t?([^\t]*)\t?([^\t]*)\t?([^\t]*)")
    local out = string.format("%s/job-%d.out", jobs, n)
    local o = io.open(out, "w")
    if kind == "QUIT" then
      o:write("BYE\n") o:close() touch(out:gsub("%.out$", ".done"))
      return  -- the app ends this copy of REAPER itself
    end
    local job = {o = o, n = n}
    job.co = coroutine.create(function()
      if kind == "CAPTURE" then capture(o, a, tonumber(b) or 0)
      elseif kind == "TOUCH" then
        reaper.EnumerateFiles(a, -1)
        local f = reaper.EnumerateFiles(a, 0) or reaper.EnumerateSubdirectories(a, 0)
        o:write("OK\t", tostring(f ~= nil), "\n")
      elseif kind == "VERIFY" then verify(o, a, tonumber(b) or 0, tonumber(c) or 0, tonumber(d) or 0)
      else o:write("UNKNOWN\t", line, "\n") end
    end)
    running = job
    loop()   -- start it now: a job that never waits finishes in this same pass, as before
    return
  end
  reaper.defer(loop)
end
reaper.defer(loop)

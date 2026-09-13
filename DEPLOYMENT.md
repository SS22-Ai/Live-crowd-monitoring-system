# Deployment / Event-Day Runbook

This is the single "what do I actually do" doc for running the Event Crowd
Monitor unattended at a real event, on this MacBook Air M2. For how the app
works, see [`HANDOVER.md`](HANDOVER.md); for what's verified vs. not, see
[`DEPLOYMENT_STATUS.md`](DEPLOYMENT_STATUS.md).

The app is supervised by **launchd** (macOS's built-in service manager) via
[`deploy/com.eventcrowdmonitor.app.plist`](deploy/com.eventcrowdmonitor.app.plist),
so it restarts itself automatically if it crashes, gets killed, or the
machine loses power and someone logs back in. Counts survive every restart
already (see `HANDOVER.md` §7) — the supervisor's only job is making sure
the *process* comes back, not the data.

---

## 1. One-time setup (do this before event day, not on the day itself)

1. Confirm `config.local.yaml` has the real venue cameras configured and
   reachable (see `HANDOVER.md` §5, §12 for RTSP troubleshooting). The
   plist runs with `CROWD_MONITOR_CONFIG=config.local.yaml` — **not** the
   safe demo `config.yaml`.
2. If this checkout ever moves to a different machine or path, edit every
   absolute path in `deploy/com.eventcrowdmonitor.app.plist` first
   (`ProgramArguments`, `WorkingDirectory`, `StandardOutPath`,
   `StandardErrorPath`) — launchd does not know about `$HOME` or relative
   paths.
3. Install the agent:
   ```bash
   cp deploy/com.eventcrowdmonitor.app.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.eventcrowdmonitor.app.plist
   ```
   This starts the app immediately (`RunAtLoad`) and registers it to start
   at every future login.
4. **Strongly recommended for real power-loss recovery:** enable automatic
   login for this user (System Settings → Users & Groups → Login Options →
   Automatic login). A `LaunchAgent` only starts once someone is logged in
   — after a real power cut, the Mac will sit at the login screen forever
   without this. This is a system security setting change, so make it
   yourself; it isn't something to script.
5. Verify: open http://localhost:8000, confirm both cameras go ONLINE,
   confirm `tail -f logs/app.log` shows normal startup lines.

## 2. Day-of checklist

1. **Before doors open:** confirm the app is already running (it should be,
   from step 3 above, or from the last time the machine rebooted):
   ```bash
   launchctl print gui/$(id -u)/com.eventcrowdmonitor.app | head -20
   ```
   Look for `state = running` and a `pid`.
2. Open the dashboard (http://localhost:8000) on whatever screen/tablet is
   watching it. Confirm both `event_entrance` and `dining_entrance` show
   ONLINE on the Overview tab.
3. Walk-test each entrance once (one person, one direction) and confirm the
   count moves by exactly 1 on the dashboard before you rely on it.
4. **Zero the counts for the actual event** (do this *after* the walk-test,
   right before doors open): click **Reset counts** (or **Start new
   session**) on the dashboard. This is the only thing that durably zeros
   counts — see `HANDOVER.md` §7. Don't skip this if you just spent time
   walk-testing, or your walk-test steps will be counted as real
   attendance.
5. Leave `logs/app.log` tailing somewhere visible if you have a spare
   terminal:
   ```bash
   tail -f logs/app.log
   ```

## 3. During the event

- The dashboard polls itself (1s status, 2s events) — no manual refresh
  needed. Overview tab for live numbers, Preview tab if you need to
  visually confirm what the camera is actually seeing.
- If a camera shows OFFLINE/RECONNECTING: that's the camera/network, not
  the app — see `HANDOVER.md` §12 "RTSP failure" for the
  ping/arp/nc diagnostic steps. The other camera and the rest of the app
  keep working independently.
- If the whole dashboard stops responding: check whether the process is
  still up (`launchctl print gui/$(id -u)/com.eventcrowdmonitor.app`)
  before assuming the worst — launchd should already be restarting it on
  its own; give it `ThrottleInterval` (10s) before deciding it's stuck.
- If it's genuinely stuck restart-looping, check
  `logs/launchd-stderr.log` and `logs/app.log` for the actual error before
  touching anything else.

## 4. Stopping the app (read this before you `kill` anything)

**Do not `kill` or `Ctrl+C` the process once the launchd agent is loaded —
`KeepAlive` will restart it within ~10 seconds**, which will look like the
stop "didn't work." To actually stop it:

```bash
launchctl bootout gui/$(id -u)/com.eventcrowdmonitor.app
```

To start it again later (without a reboot/login):

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.eventcrowdmonitor.app.plist
```

## 5. Uninstalling the supervisor entirely

```bash
launchctl bootout gui/$(id -u)/com.eventcrowdmonitor.app
rm ~/Library/LaunchAgents/com.eventcrowdmonitor.app.plist
```
The app itself, its data, and its config are untouched — this only removes
the auto-restart/auto-start behavior. You can still run it manually with
`CROWD_MONITOR_CONFIG=config.local.yaml .venv/bin/python run.py` as before.

## 6. What this does NOT solve

- **Sparsh camera reachability** — this only supervises the *process*; if a
  camera is unreachable at the network level, restarting the app changes
  nothing. See `HANDOVER.md` §14 item 9.
- **Multi-hour stability** — restarting on crash is a safety net, not a
  substitute for the multi-hour soak test that still hasn't been run (see
  `TODO.md`). If it crashes repeatedly during the event, that's a real bug
  to investigate afterward, not something to ignore because the supervisor
  papers over it.
- **DB backup** — `data/crowd_monitor.db` is not backed up anywhere. If you
  want a safety copy before the event, `cp data/crowd_monitor.db
  data/crowd_monitor.db.bak` beforehand.

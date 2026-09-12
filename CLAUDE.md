# Read this first

**Before doing anything else, read [`HANDOVER.md`](HANDOVER.md) in full.**
It's the comprehensive, current developer handover doc — architecture, how
counting/occupancy/persistence work, API reference, dashboard structure,
testing, troubleshooting, deployment steps, known problems, and a "do not
change" list of load-bearing behavior. This file (`CLAUDE.md`) only covers
things that will trip you up in the *first five minutes* if you don't know
them going in.

## The 6 things you need to know immediately

1. **This is a live, near-deployment project for a real event**, not a toy.
   Check `DEPLOYMENT_STATUS.md` for the current readiness percentage and
   `TODO.md` for what's actually left — don't assume from the code alone.

2. **You (this Claude session) almost certainly cannot access the camera
   directly.** If you're running in an automated/headless execution
   context (not a real Terminal the user is typing into), macOS Camera
   permission (TCC) will not be grantable to you, and `cv2.VideoCapture`
   will fail with `not authorized`. This is expected, not a bug — camera
   testing and live verification must happen from the user's own Terminal.
   See `HANDOVER.md` §12 ("Camera permission (macOS)").

3. **If you start `run.py` yourself while the user might also be running
   it in their own Terminal, you WILL get `address already in use` port
   conflicts.** Always check `lsof -ti:8000 -sTCP:LISTEN` before starting
   it, and ask the user if they have their own instance running before
   killing anything. See `HANDOVER.md` §12.

4. **Real camera credentials go in `config.local.yaml` (gitignored),
   NEVER in `config.yaml` (tracked in git).** `CROWD_MONITOR_CONFIG=config.local.yaml`
   selects it. See `HANDOVER.md` §5.

5. **Data persists across every restart now — this was a deliberate,
   explicit user requirement, not the original design.** Only "Reset
   counts" / "Start new session" on the dashboard actually zero anything.
   If you touch session/reset logic, read `HANDOVER.md` §7 and
   `DECISIONS.md` D11 first — it's easy to accidentally make a "reset"
   silently undone by the next restart.

6. **Always run the full test suite before and after any change**
   (`python3 -m unittest discover -s tests`, currently 91 tests, a few
   seconds) and check `git status`/`git log` to see the actual current
   state — don't trust a summary (including this one) over what the
   repo and tests actually show right now.

## Everything else

`HANDOVER.md` has the full picture. `ARCHITECTURE.md` and `DECISIONS.md`
have more depth on specific modules and why things were built the way they
were. `DEPLOYMENT_STATUS.md` is the numeric source of truth for what's
actually verified vs. just implemented — treat "code exists" and "works in
the real world" as different claims, always.

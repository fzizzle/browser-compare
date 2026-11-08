# Browser memory benchmark — design

## Intent
Pick the browser that stays lightest on memory with a realistic 10-tab working
session open. Speed and UI customisation were discussed and explicitly dropped
for now; memory is the only metric.

## Decisions (user)
- Metric: memory only.
- Session: 10 tabs, **logged out** — email, WhatsApp Web, YouTube, GitHub,
  a time-zone site, a currency converter.
- Ad blocking: tested **with uBlock Origin** installed (how the user browses).
- Browsers: every installed browser. User installed Firefox, Chrome, Brave,
  Vivaldi on top of existing Zen, Chromium, Helium.
- Common sites picked for the tools: timeanddate.com, xe.com.

## Calls made by the builder (Claude)
- **Tabs:** Gmail, Outlook, WhatsApp Web, YouTube (Big Buck Bunny, autoplay,
  muted), GitHub repo / PR list / issue list, timeanddate world clock,
  xe.com converter, a Wikipedia article.
- **Ad blocker per engine** — Chrome no longer runs full uBlock Origin (MV2):
  - Firefox, Zen: uBlock Origin (full).
  - Chrome, Chromium, Vivaldi: uBlock Origin Lite.
  - Helium: its built-in uBlock Origin.
  - Brave: its built-in Shields (see "Deviations").
  The blocker used is printed next to every result.
  Chrome ignores `--load-extension`, so on all Chromium browsers uBO Lite is
  installed over the DevTools pipe (`Extensions.loadUnpacked`) at each launch,
  and the 10 tabs are opened only after it is active.
- **Isolation:** each run gets a fresh, throwaway profile copied from a
  warmed-up template (first-run tasks, filter-list setup done once). The
  user's real profiles are never touched.
- **Process accounting:** each browser runs in its own systemd user scope
  (cgroup), so every process it spawns is counted and nothing else (e.g. the
  user's own running Zen) is.
- **Metric:** sum of PSS (proportional set size — shared pages split fairly)
  across all processes in the cgroup. cgroup `memory.current` is recorded too.
- **Timeline per run:** launch with all 10 URLs → 60 s load → 120 s idle,
  sampling every 5 s. Reported: "loaded" (median of samples at 45–60 s) and
  "idle" (median of the last 30 s).
- **Repeats:** 3 runs per browser, round-robin across browsers to spread drift.
- **Output:** terminal table + `results/<timestamp>/report.html` (chart) +
  raw JSON.
- **Language:** Python 3 standard library only; reads `/proc` and cgroupfs.

## Deviations
- Brave: disabling Shields needs UI or root-level policy; running uBOL on top
  of Shields would double-block. Brave therefore runs with Shields only.

## Non-goals
Logged-in sessions, speed benchmarks, UI customisation scoring, GPU/VRAM.

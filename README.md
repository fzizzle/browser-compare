<img src="assets/icon.svg" width="64" height="64" alt="">

# browser compare

Compare how much memory the browsers installed on a Linux machine use with the
same realistic 10-tab session open: Gmail, Outlook, WhatsApp Web, YouTube
(playing, muted), three GitHub pages, timeanddate.com, xe.com and Wikipedia.

Every browser runs with an ad blocker, the way most people browse:

| Browser | Blocker |
|---|---|
| Firefox, Zen | uBlock Origin |
| Chrome, Chromium, Vivaldi | uBlock Origin Lite (Chrome no longer runs the full version) |
| Brave | Brave Shields |
| Helium | built-in uBlock Origin |

## Usage

```bash
./bench.py                      # every installed browser, 3 runs each (~80 min)
./bench.py --only firefox,brave # just some browsers
./bench.py --runs 1 --load 30 --idle 30   # quick check
```

Windows open and close while it runs, so leave the machine alone. Results go
to `results/<timestamp>/`: a ranked table in the terminal, `report.html` with
charts, and the raw `results.json`.

## How it measures

- Each run uses a fresh, throwaway profile, so your own profiles are never touched.
- Each browser runs in its own systemd user scope (cgroup). All of its
  processes are counted and nothing else is, even if you have the same browser
  open yourself.
- Memory is total **PSS** (proportional set size) across those processes.
  Shared pages are split between the processes that share them, so nothing is
  double-counted. The cgroup's `memory.current` is recorded alongside it as a
  cross-check.
- Each run takes readings right after the tabs load (60 s) and again after
  2 minutes idle. Runs are interleaved across browsers.

Requirements: Linux with systemd and Python 3 (standard library only).
Supported browsers: Firefox, Zen, Chrome, Chromium, Brave, Vivaldi and Helium.
Add more in the `BROWSERS` list in `bench.py`.

Design notes: [docs/superpowers/specs/](docs/superpowers/specs/2026-11-08-browser-memory-benchmark-design.md)

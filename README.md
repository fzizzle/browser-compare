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

## Results (8 Nov 2026)

CachyOS (Linux 7.3), 16 threads, 30 GB RAM, Wayland. 10 tabs, logged out.
3 runs per browser (one Brave run crashed early and was discarded). Memory is
total PSS across all of the browser's processes. Lower is better.

| # | Browser | Version | Blocker | After load (60 s) | After idle (+2 min) | Idle range | Peak |
|---|---|---|---|---:|---:|---:|---:|
| 1 | Chromium | 156.0.8078.79 | uBlock Origin Lite | 1.10 GB | **975 MB** | 950–991 MB | 1.28 GB |
| 2 | Helium | 0.21.1.1 | built-in uBlock Origin | 1.13 GB | **1005 MB** | 977–1047 MB | 1.38 GB |
| 3 | Brave | 1.99.55 | Brave Shields | 1.10 GB | **1023 MB** | 1009–1037 MB | 1.32 GB |
| 4 | Chrome | 157.0.8103.38 | uBlock Origin Lite | 1.17 GB | **1.03 GB** | 1.00–1.05 GB | 1.41 GB |
| 5 | Vivaldi | 8.3.4191.30 | uBlock Origin Lite | 1.29 GB | **1.13 GB** | 1.08–1.17 GB | 1.52 GB |
| 6 | Zen | 1.24.1b | uBlock Origin | 2.15 GB | **1.88 GB** | 1.85–1.91 GB | 3.02 GB |
| 7 | Firefox | 159.0.1 | uBlock Origin | 2.52 GB | **2.33 GB** | 2.26–2.45 GB | 3.28 GB |

**Takeaways**

- The Chromium-based browsers all settle at about 1.0–1.15 GB. Chromium,
  Helium, Brave and Chrome are within run-to-run noise of each other.
- Firefox and Zen use roughly twice as much, and both briefly exceed 3 GB
  while the tabs load. Zen is about 0.45 GB lighter than plain Firefox.
- PSS totals were cross-checked against the cgroup's `memory.current` and
  agree within a few percent.
- Logged-in Gmail and WhatsApp Web are much heavier than their logged-out
  pages. Absolute numbers in real use will be higher; the ranking was not
  tested logged in.

Full interactive report: [`results/20261108-140633/report.html`](results/20261108-140633/report.html)
(download and open it in a browser). Raw per-sample data is in
[`results.json`](results/20261108-140633/results.json).

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

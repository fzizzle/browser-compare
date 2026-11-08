#!/usr/bin/env python3
"""Compare memory use of installed browsers with the same 10-tab session.

Each browser runs in its own systemd user scope (cgroup) with a throwaway
profile, so every process it spawns is counted and nothing else is.
Metric: total PSS (proportional set size) across the browser's processes.

Usage: ./bench.py [--runs 3] [--load 60] [--idle 120] [--only firefox,chrome]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import select
import statistics
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
RESULTS = ROOT / "results"

URLS = [
    "https://mail.google.com/",
    "https://outlook.live.com/mail/",
    "https://web.whatsapp.com/",
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",  # Big Buck Bunny, plays muted
    "https://github.com/torvalds/linux",
    "https://github.com/microsoft/vscode/pulls",
    "https://github.com/microsoft/vscode/issues",
    "https://www.timeanddate.com/worldclock/",
    "https://www.xe.com/currencyconverter/",
    "https://en.wikipedia.org/wiki/Web_browser",
]

# blocker: "ubo" (full uBlock Origin, Gecko), "ubol" (uBlock Origin Lite,
# Chromium), "builtin" (browser ships its own blocker, nothing added).
BROWSERS = [
    {"name": "Firefox", "bins": ["firefox"], "engine": "gecko", "blocker": "ubo"},
    {"name": "Zen", "bins": ["zen-browser"], "engine": "gecko", "blocker": "ubo"},
    {"name": "Chrome", "bins": ["google-chrome-stable", "google-chrome"], "engine": "chromium", "blocker": "ubol"},
    {"name": "Chromium", "bins": ["chromium"], "engine": "chromium", "blocker": "ubol"},
    {"name": "Brave", "bins": ["brave", "brave-browser"], "engine": "chromium", "blocker": "builtin"},
    {"name": "Vivaldi", "bins": ["vivaldi-stable", "vivaldi"], "engine": "chromium", "blocker": "ubol"},
    {"name": "Helium", "bins": ["helium-browser"], "engine": "chromium", "blocker": "builtin"},
]
BLOCKER_LABEL = {
    "ubo": "uBlock Origin",
    "ubol": "uBlock Origin Lite",
    "builtin": "built-in blocker",
}
BUILTIN_LABEL = {"Brave": "Brave Shields", "Helium": "built-in uBlock Origin"}

UBO_XPI_URL = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi"
UBO_ID = "uBlock0@raymondhill.net"
UBOL_API = "https://api.github.com/repos/uBlockOrigin/uBOL-home/releases/latest"

GECKO_PREFS = {
    "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "startup.homepage_welcome_url.additional": "",
    "startup.homepage_first_run_url": "",
    "browser.shell.checkDefaultBrowser": False,
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    "datareporting.policy.dataSubmissionEnabled": False,
    "datareporting.policy.firstRunURL": "",
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.tabs.warnOnClose": False,
    "browser.warnOnQuit": False,
    "browser.sessionstore.resume_from_crash": False,
    "extensions.autoDisableScopes": 0,
    "extensions.enabledScopes": 15,
    "media.autoplay.default": 0,
    "media.volume_scale": "0.0",
    "zen.welcome-screen.seen": True,
}

SAMPLE_EVERY = 5


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- extensions

def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "browser-compare"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def ensure_extensions() -> dict[str, Path]:
    CACHE.mkdir(exist_ok=True)
    xpi = CACHE / "ublock-origin.xpi"
    if not xpi.exists():
        log("downloading uBlock Origin (Firefox)")
        download(UBO_XPI_URL, xpi)
    ubol_dir = CACHE / "ubol"
    if not (ubol_dir / "manifest.json").exists():
        log("downloading uBlock Origin Lite (Chromium)")
        req = urllib.request.Request(UBOL_API, headers={"User-Agent": "browser-compare"})
        with urllib.request.urlopen(req, timeout=60) as r:
            release = json.load(r)
        asset = next(a for a in release["assets"] if a["name"].endswith(".chromium.zip"))
        zpath = CACHE / asset["name"]
        download(asset["browser_download_url"], zpath)
        shutil.rmtree(ubol_dir, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(ubol_dir)
    return {"ubo": xpi, "ubol": ubol_dir}


# ------------------------------------------------------------------ launching

class CdpPipe:
    """Minimal Chrome DevTools Protocol client over --remote-debugging-pipe
    (browser reads commands on fd 3, writes replies on fd 4, NUL-separated)."""

    def __init__(self, cmd: list[str]):
        to_r, self._w = os.pipe()
        self._r, from_w = os.pipe()
        self.proc = subprocess.Popen(
            ["bash", "-c", f'exec "$@" 3<&{to_r} 4>&{from_w}', "_", *cmd],
            pass_fds=(to_r, from_w), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        os.close(to_r)
        os.close(from_w)
        self._buf = b""
        self._id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        os.write(self._w, json.dumps(msg).encode() + b"\0")
        deadline = time.time() + timeout
        while time.time() < deadline:
            while b"\0" in self._buf:
                raw, self._buf = self._buf.split(b"\0", 1)
                reply = json.loads(raw)
                if reply.get("id") == self._id:
                    if "error" in reply:
                        return {"error": reply["error"]}
                    return reply.get("result", {})
            r, _, _ = select.select([self._r], [], [], 1)
            if r:
                chunk = os.read(self._r, 1 << 16)
                if not chunk:
                    raise RuntimeError("browser closed the DevTools pipe")
                self._buf += chunk
        raise TimeoutError(method)

    def close(self) -> None:
        for fd in (self._w, self._r):
            try:
                os.close(fd)
            except OSError:
                pass


def build_cmd(b: dict, profile: Path, urls: list[str]) -> list[str]:
    if b["engine"] == "gecko":
        return [b["bin"], "--new-instance", "--profile", str(profile), *urls]
    cmd = [
        b["bin"],
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--password-store=basic",
        "--autoplay-policy=no-user-gesture-required",
        "--mute-audio",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--window-size=1600,1000",
        # DevTools protocol over fds 3/4: lets us install uBO Lite (Chrome
        # dropped --load-extension) and open the tabs only once it is active.
        "--remote-debugging-pipe",
        "--enable-unsafe-extension-debugging",
    ]
    return cmd + ["about:blank"]


def prepare_template(b: dict, exts: dict, workdir: Path) -> Path:
    tpl = workdir / f"template-{b['name'].lower()}"
    shutil.rmtree(tpl, ignore_errors=True)
    tpl.mkdir(parents=True)
    if b["engine"] == "gecko":
        lines = [f'user_pref("{k}", {json.dumps(v)});' for k, v in GECKO_PREFS.items()]
        (tpl / "user.js").write_text("\n".join(lines) + "\n")
        if b["blocker"] == "ubo":
            (tpl / "extensions").mkdir()
            shutil.copy(exts["ubo"], tpl / "extensions" / f"{UBO_ID}.xpi")
    return tpl


class Session:
    """One browser instance inside its own systemd user scope."""

    def __init__(self, b: dict, profile: Path, urls: list[str], exts: dict):
        self.b = b
        self.unit = f"bcmp-{b['name'].lower()}-{os.getpid()}-{int(time.time() * 1000)}"
        self.blocker = None
        self.cdp = None
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
               f"--unit={self.unit}", "--", *build_cmd(b, profile, urls)]
        if b["engine"] == "chromium":
            self.cdp = CdpPipe(cmd)
            self.proc = self.cdp.proc
        else:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         start_new_session=True)
        self.cgroup = self._find_cgroup()
        if self.cdp:
            self._chromium_setup(urls, exts)

    def _chromium_setup(self, urls: list[str], exts: dict) -> None:
        targets = self.cdp.call("Target.getTargets")["targetInfos"]
        blank = [t["targetId"] for t in targets if t["type"] == "page"]
        if self.b["blocker"] == "ubol":
            r = self.cdp.call("Extensions.loadUnpacked", {"path": str(exts["ubol"])})
            ext_id = r.get("id")
            version = json.loads((exts["ubol"] / "manifest.json").read_text())["version"]
            self.blocker = f"uBlock Origin Lite {version}" if ext_id else \
                f"uBlock Origin Lite NOT LOADED ({r.get('error', {}).get('message', '?')})"
            time.sleep(2)  # let its rulesets register before any page loads
        if urls != ["about:blank"]:
            for u in urls:
                self.cdp.call("Target.createTarget", {"url": u})
            for t in blank:
                self.cdp.call("Target.closeTarget", {"targetId": t})

    def _find_cgroup(self) -> Path:
        for _ in range(50):
            p = Path(f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/"
                     f"user@{os.getuid()}.service/app.slice/{self.unit}.scope")
            if p.exists():
                return p
            try:
                rel = Path(f"/proc/{self.proc.pid}/cgroup").read_text().strip().split("::", 1)[1]
                if self.unit in rel:
                    return Path("/sys/fs/cgroup" + rel)
            except (OSError, IndexError):
                pass
            time.sleep(0.1)
        raise RuntimeError(f"could not find cgroup for {self.unit}")

    def pids(self) -> list[int]:
        pids = []
        for f in self.cgroup.rglob("cgroup.procs"):
            try:
                pids += [int(x) for x in f.read_text().split()]
            except OSError:
                pass
        return pids

    def sample(self) -> dict:
        pss = 0
        n = 0
        content = 0
        for pid in self.pids():
            try:
                for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                    if line.startswith("Pss:"):
                        pss += int(line.split()[1])
                        break
                n += 1
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
                if b"--type=renderer" in cmdline or b"-isForBrowser" in cmdline:
                    content += 1
            except (OSError, ValueError):
                pass
        try:
            current = int((self.cgroup / "memory.current").read_text())
        except OSError:
            current = 0
        return {"pss_mb": pss / 1024, "cgroup_mb": current / 2**20,
                "procs": n, "content_procs": content}

    def tabs(self) -> int | None:
        if not self.cdp:
            return None
        try:
            infos = self.cdp.call("Target.getTargets")["targetInfos"]
            return sum(1 for t in infos if t["type"] == "page" and t["url"].startswith("http"))
        except Exception:
            return None

    def stop(self) -> None:
        try:
            os.kill(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.time() + 20
        while time.time() < deadline and self.pids():
            time.sleep(0.5)
        if self.pids():
            subprocess.run(["systemctl", "--user", "kill", "--signal=KILL", f"{self.unit}.scope"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.time() + 10
            while time.time() < deadline and self.pids():
                time.sleep(0.5)
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if self.cdp:
            self.cdp.close()


# --------------------------------------------------------------- verification

def blocker_status(b: dict, profile: Path, session: "Session | None" = None) -> str:
    """Check the ad blocker really is installed and enabled."""
    if session is not None and session.blocker:
        return session.blocker
    if b["blocker"] == "builtin":
        return BUILTIN_LABEL.get(b["name"], "built-in")
    if b["blocker"] == "ubo":
        try:
            data = json.loads((profile / "extensions.json").read_text())
            for a in data.get("addons", []):
                if a.get("id") == UBO_ID:
                    return f"uBlock Origin {a.get('version')}" + ("" if a.get("active") else " (INACTIVE)")
        except (OSError, ValueError):
            pass
        return "uBlock Origin NOT LOADED"
    return "uBlock Origin Lite NOT LOADED"


# ------------------------------------------------------------------- running

def warm_up(b: dict, tpl: Path, exts: dict, seconds: int = 40) -> str:
    """First launch on the template: first-run tasks, extension install,
    filter-list setup. The template is then copied for every measured run."""
    s = Session(b, tpl, ["about:blank"], exts)
    time.sleep(seconds)
    status = blocker_status(b, tpl, s)
    s.stop()
    for junk in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lock", ".parentlock"):
        try:
            (tpl / junk).unlink()
        except OSError:
            pass
    return blocker_status(b, tpl) if b["engine"] == "gecko" else status


def measure(b: dict, tpl: Path, exts: dict, workdir: Path, load: int, idle: int) -> dict:
    prof = workdir / f"run-{b['name'].lower()}"
    shutil.rmtree(prof, ignore_errors=True)
    shutil.copytree(tpl, prof, symlinks=True)
    s = Session(b, prof, URLS, exts)
    samples = []
    t0 = time.time()
    tabs = None
    try:
        while (t := time.time() - t0) < load + idle:
            smp = s.sample()
            smp["t"] = round(t, 1)
            samples.append(smp)
            if tabs is None and t > 20:
                tabs = s.tabs()
            time.sleep(max(0.0, SAMPLE_EVERY - ((time.time() - t0) % SAMPLE_EVERY)))
        blocker = blocker_status(b, prof, s)
    finally:
        s.stop()
        shutil.rmtree(prof, ignore_errors=True)

    def med(lo: float, hi: float, key: str = "pss_mb") -> float:
        vals = [x[key] for x in samples if lo <= x["t"] <= hi]
        return round(statistics.median(vals), 1) if vals else 0.0

    end = load + idle
    return {
        "loaded_mb": med(load - 15, load),
        "idle_mb": med(end - 30, end),
        "peak_mb": round(max(x["pss_mb"] for x in samples), 1),
        "cgroup_idle_mb": med(end - 30, end, "cgroup_mb"),
        "procs": samples[-1]["procs"],
        "content_procs": samples[-1]["content_procs"],
        "tabs": tabs,
        "blocker": blocker,
        "samples": samples,
    }


def summarise(results: dict) -> list[dict]:
    rows = []
    for name, info in results.items():
        runs = [r for r in info["runs"] if r["procs"] > 2]
        if not runs:
            rows.append({"name": name, "failed": True, **{k: info[k] for k in ("version", "blocker")}})
            continue
        def stat(key):
            v = [r[key] for r in runs]
            return {"mean": round(statistics.mean(v), 1), "min": min(v), "max": max(v)}
        rows.append({
            "name": name, "version": info["version"], "blocker": info["blocker"],
            "runs": len(runs), "loaded": stat("loaded_mb"), "idle": stat("idle_mb"),
            "peak": stat("peak_mb"), "procs": runs[-1]["procs"], "tabs": runs[-1]["tabs"],
        })
    rows.sort(key=lambda r: r.get("idle", {}).get("mean", float("inf")))
    return rows


def print_table(rows: list[dict]) -> None:
    print()
    hdr = f"{'#':>2}  {'Browser':<10} {'After load':>11} {'After idle':>11} {'Peak':>8} {'Procs':>6}  Blocker"
    print(hdr)
    print("-" * (len(hdr) + 20))
    for i, r in enumerate(rows, 1):
        if r.get("failed"):
            print(f"{i:>2}  {r['name']:<10} {'FAILED':>11}")
            continue
        print(f"{i:>2}  {r['name']:<10} {r['loaded']['mean']:>8.0f} MB {r['idle']['mean']:>8.0f} MB "
              f"{r['peak']['mean']:>5.0f} MB {r['procs']:>6}  {r['blocker']}")
    print("\nMemory = total PSS of all the browser's processes, mean of runs. Ranked by 'after idle'.")


def browser_version(binary: str) -> str:
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=20).stdout
        return out.strip().splitlines()[0] if out.strip() else "?"
    except Exception:
        return "?"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--load", type=int, default=60, help="seconds to let tabs load")
    ap.add_argument("--idle", type=int, default=120, help="seconds idle after loading")
    ap.add_argument("--only", help="comma-separated browser names")
    args = ap.parse_args()

    browsers = []
    for b in BROWSERS:
        if args.only and b["name"].lower() not in args.only.lower().split(","):
            continue
        binary = next((shutil.which(x) for x in b["bins"] if shutil.which(x)), None)
        if binary:
            browsers.append({**b, "bin": binary})
        else:
            log(f"skipping {b['name']}: not installed")
    if not browsers:
        sys.exit("no browsers found")

    exts = ensure_extensions()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = RESULTS / stamp
    outdir.mkdir(parents=True)
    workdir = CACHE / "profiles"
    workdir.mkdir(parents=True, exist_ok=True)

    per_run = args.load + args.idle + 25
    total = len(browsers) * (40 + 25 + args.runs * per_run)
    log(f"{len(browsers)} browsers x {args.runs} runs — about {total // 60} min. "
        "Windows will open and close; please leave the machine alone.")

    results: dict = {}
    templates = {}
    for b in browsers:
        log(f"warm-up {b['name']}")
        tpl = prepare_template(b, exts, workdir)
        status = warm_up(b, tpl, exts)
        templates[b["name"]] = tpl
        results[b["name"]] = {"version": browser_version(b["bin"]), "blocker": status, "runs": []}
        log(f"  {results[b['name']]['version']} — {status}")

    for run in range(args.runs):
        order = browsers[run % len(browsers):] + browsers[:run % len(browsers)]
        for b in order:
            log(f"run {run + 1}/{args.runs} {b['name']}")
            r = measure(b, templates[b["name"]], exts, workdir, args.load, args.idle)
            results[b["name"]]["runs"].append(r)
            results[b["name"]]["blocker"] = r["blocker"]
            log(f"  loaded {r['loaded_mb']:.0f} MB, idle {r['idle_mb']:.0f} MB, "
                f"{r['procs']} procs, tabs={r['tabs']}")
            (outdir / "results.json").write_text(json.dumps(
                {"config": vars(args), "urls": URLS, "browsers": results}, indent=1))

    rows = summarise(results)
    (outdir / "summary.json").write_text(json.dumps(rows, indent=1))
    print_table(rows)
    try:
        from report import write_report
        path = write_report(outdir, rows, results, vars(args))
        print(f"\nReport: {path}")
    except ImportError:
        pass
    shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()

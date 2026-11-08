"""Write a self-contained HTML report for a benchmark run."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Browser Memory Comparison</title>
<style>
:root{color-scheme:light;--bg:#f5f5f3;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;
--grid:#e4e3df;--bar:#2a78d6;--tick:#0b0b0b;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#111110;--surface:#1a1a19;
--ink:#f0efec;--ink2:#c3c2b7;--muted:#8d8c86;--grid:#2c2c2a;--bar:#3987e5;--tick:#f0efec;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111110;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8d8c86;
--grid:#2c2c2a;--bar:#3987e5;--tick:#f0efec;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--s6:#008300;--s7:#9085e9;--s8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:17px;margin:0 0 4px}
.sub{color:var(--ink2);margin:0 0 24px}
.card{background:var(--surface);border:1px solid var(--grid);border-radius:12px;padding:20px;margin-bottom:20px}
.note{color:var(--ink2);font-size:13px;margin:4px 0 14px}
.hero{display:flex;gap:28px;flex-wrap:wrap}
.hero div b{display:block;font-size:28px;font-variant-numeric:tabular-nums}
.hero div span{color:var(--ink2);font-size:13px}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--ink2);font-size:12px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin-bottom:8px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.legend i.tick{width:3px;height:14px;border-radius:1px;background:var(--tick)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}
th,td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--grid)}
th:nth-child(-n+2),td:nth-child(-n+2){text-align:left}
th{color:var(--ink2);font-weight:600;font-size:13px}
td small{color:var(--muted)}
.scroll{overflow-x:auto}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--grid);border-radius:8px;
padding:8px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.15);opacity:0;transition:opacity .1s;z-index:9;color:var(--ink)}
ul{margin:6px 0 0;padding-left:20px;color:var(--ink2);font-size:13px}
</style></head><body><main>
<h1>Browser memory with 10 tabs</h1>
<p class="sub" id="sub"></p>
<div class="card"><div class="hero" id="hero"></div></div>
<div class="card">
<h2>Memory after idle (lower is better)</h2>
<p class="note">Total PSS of all browser processes. Bar = mean after idle; line = range across runs; tick = mean right after load.</p>
<div class="legend"><span><i style="background:var(--bar)"></i>After idle</span><span><i class="tick"></i>After load</span></div>
<svg id="bars"></svg></div>
<div class="card">
<h2>Memory over time</h2>
<p class="note">Run with the median idle value for each browser. Dashed line marks the end of the load phase.</p>
<div class="legend" id="tlLegend"></div>
<svg id="timeline"></svg></div>
<div class="card"><h2>All numbers</h2>
<div class="scroll"><table id="tbl"></table></div></div>
<div class="card"><h2>How this was measured</h2><ul id="method"></ul></div>
</main><div id="tip"></div>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]); parent && parent.appendChild(e); return e; };
const fmt = mb => mb >= 1024 ? (mb/1024).toFixed(2) + " GB" : Math.round(mb) + " MB";
const tip = $("tip");
const showTip = (ev, html) => { tip.innerHTML = html; tip.style.opacity = 1;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px"; tip.style.top = (ev.clientY + 14) + "px"; };
const hideTip = () => tip.style.opacity = 0;

const rows = D.rows.filter(r => !r.failed);
$("sub").textContent = `${D.config.runs} runs per browser · ${D.config.load}s load + ${D.config.idle}s idle · ${D.when}`;

// hero
const best = rows[0], worst = rows[rows.length - 1];
$("hero").innerHTML = rows.length ? `
  <div><b>${best.name}</b><span>lightest · ${fmt(best.idle.mean)} after idle</span></div>
  <div><b>${worst.name}</b><span>heaviest · ${fmt(worst.idle.mean)}</span></div>
  <div><b>${(worst.idle.mean / best.idle.mean).toFixed(1)}×</b><span>heaviest vs lightest</span></div>` : "No successful runs.";

// bar chart
(() => {
  const svg = $("bars"), W = 900, rowH = 34, L = 150, R = 70, T = 8;
  const H = T + rows.length * rowH + 28;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const max = Math.max(...rows.map(r => Math.max(r.idle.max, r.loaded.mean))) * 1.05;
  const x = v => L + (W - L - R) * v / max;
  const step = max > 4000 ? 1000 : max > 2000 ? 500 : 250;
  for (let v = 0; v <= max; v += step) {
    el("line", {x1: x(v), x2: x(v), y1: T, y2: H - 22, stroke: "var(--grid)"}, svg);
    el("text", {x: x(v), y: H - 6, "text-anchor": "middle"}, svg).textContent = v >= 1000 ? (v/1000) + "k" : v;
  }
  rows.forEach((r, i) => {
    const y = T + i * rowH, cy = y + rowH / 2, bh = 18;
    const g = el("g", {}, svg);
    const n = el("text", {x: L - 12, y: cy + 4, "text-anchor": "end", style: "fill:var(--ink);font-size:13px"}, g);
    n.textContent = r.name;
    el("text", {x: L - 12, y: cy + 17, "text-anchor": "end", style: "font-size:10px;fill:var(--muted)"}, g).textContent = r.blocker;
    const w = x(r.idle.mean) - L;
    el("path", {d: `M${L},${cy-bh/2} h${w-4} a4,4 0 0 1 4,4 v${bh-8} a4,4 0 0 1 -4,4 h${-(w-4)} z`, fill: "var(--bar)"}, g);
    el("line", {x1: x(r.idle.min), x2: x(r.idle.max), y1: cy, y2: cy, stroke: "var(--tick)", "stroke-width": 1.5, opacity: .55}, g);
    el("rect", {x: x(r.loaded.mean) - 1.5, y: cy - bh/2 - 3, width: 3, height: bh + 6, rx: 1, fill: "var(--tick)"}, g);
    el("text", {x: Math.max(x(r.idle.max), x(r.loaded.mean)) + 8, y: cy + 4, style: "fill:var(--ink);font-size:12px"}, g).textContent = fmt(r.idle.mean);
    const hit = el("rect", {x: 0, y, width: W, height: rowH, fill: "transparent"}, g);
    hit.addEventListener("mousemove", ev => showTip(ev, `<b>${r.name}</b><br>After idle: ${fmt(r.idle.mean)} <small>(${fmt(r.idle.min)}–${fmt(r.idle.max)})</small><br>After load: ${fmt(r.loaded.mean)}<br>Peak: ${fmt(r.peak.mean)}<br>${r.procs} processes · ${r.blocker}`));
    hit.addEventListener("mouseleave", hideTip);
  });
})();

// timeline
(() => {
  const svg = $("timeline"), W = 900, H = 320, L = 50, R = 16, T = 10, B = 28;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const order = D.order;  // fixed browser order -> fixed colors
  const series = order.map((name, i) => ({name, color: `var(--s${i + 1})`, s: D.timeline[name] || []})).filter(s => s.s.length);
  $("tlLegend").innerHTML = series.map(s => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("");
  const tmax = Math.max(...series.flatMap(s => s.s.map(p => p[0])));
  const vmax = Math.max(...series.flatMap(s => s.s.map(p => p[1]))) * 1.08;
  const x = t => L + (W - L - R) * t / tmax, y = v => T + (H - T - B) * (1 - v / vmax);
  const step = vmax > 4000 ? 1000 : vmax > 2000 ? 500 : 250;
  for (let v = 0; v <= vmax; v += step) {
    el("line", {x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: "var(--grid)"}, svg);
    el("text", {x: L - 8, y: y(v) + 4, "text-anchor": "end"}, svg).textContent = v >= 1000 ? (v/1000) + "k" : v;
  }
  for (let t = 0; t <= tmax; t += 30) el("text", {x: x(t), y: H - 8, "text-anchor": "middle"}, svg).textContent = t + "s";
  el("line", {x1: x(D.config.load), x2: x(D.config.load), y1: T, y2: H - B, stroke: "var(--muted)", "stroke-dasharray": "4 4"}, svg);
  series.forEach(s => el("polyline", {points: s.s.map(p => `${x(p[0])},${y(p[1])}`).join(" "), fill: "none",
    stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round"}, svg));
  const cross = el("line", {y1: T, y2: H - B, stroke: "var(--muted)", opacity: 0}, svg);
  const hit = el("rect", {x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent"}, svg);
  hit.addEventListener("mousemove", ev => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    const t = (p.x - L) / (W - L - R) * tmax;
    cross.setAttribute("x1", p.x); cross.setAttribute("x2", p.x); cross.setAttribute("opacity", 1);
    const vals = series.map(s => { const q = s.s.reduce((a, b) => Math.abs(b[0] - t) < Math.abs(a[0] - t) ? b : a);
      return {name: s.name, color: s.color, v: q[1]}; }).sort((a, b) => b.v - a.v);
    showTip(ev, `<b>${Math.round(t)}s</b><br>` + vals.map(v => `<i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${v.color};margin-right:6px"></i>${v.name}: ${fmt(v.v)}`).join("<br>"));
  });
  hit.addEventListener("mouseleave", () => { hideTip(); cross.setAttribute("opacity", 0); });
})();

// table
$("tbl").innerHTML = `<tr><th>#</th><th>Browser</th><th>After load</th><th>After idle</th><th>Idle range</th><th>Peak</th><th>Procs</th><th>Tabs</th></tr>` +
  D.rows.map((r, i) => r.failed ? `<tr><td>${i+1}</td><td>${r.name}</td><td colspan="6">failed</td></tr>` :
  `<tr><td>${i+1}</td><td>${r.name}<br><small>${r.version} · ${r.blocker}</small></td><td>${fmt(r.loaded.mean)}</td><td><b>${fmt(r.idle.mean)}</b></td>
   <td>${fmt(r.idle.min)}–${fmt(r.idle.max)}</td><td>${fmt(r.peak.mean)}</td><td>${r.procs}</td><td>${r.tabs ?? "–"}</td></tr>`).join("");

$("method").innerHTML = [
  "Same 10 tabs in every browser, logged out: " + D.urls.map(u => new URL(u).hostname.replace(/^www\./, "")).join(", ") + ".",
  "Each run uses a fresh throwaway profile; your own profiles are never touched.",
  "Each browser runs in its own systemd scope (cgroup), so all its processes are counted and nothing else is.",
  "Memory = PSS (proportional set size): shared pages are split between the processes that share them, so nothing is double-counted.",
  "Firefox and Zen use full uBlock Origin; Chrome, Chromium and Vivaldi use uBlock Origin Lite (Chrome no longer runs the full version); Brave uses Shields; Helium uses its built-in uBlock Origin.",
  "Runs are interleaved across browsers to spread out network and system noise.",
].map(s => `<li>${s}</li>`).join("");
</script></body></html>
"""


def write_report(outdir: Path, rows: list[dict], results: dict, config: dict) -> Path:
    timeline = {}
    for name, info in results.items():
        runs = [r for r in info["runs"] if r["procs"] > 2]
        if not runs:
            continue
        runs = sorted(runs, key=lambda r: r["idle_mb"])
        median_run = runs[len(runs) // 2]
        timeline[name] = [[s["t"], round(s["pss_mb"], 1)] for s in median_run["samples"]]
    data = {
        "rows": rows,
        "order": list(results.keys()),
        "timeline": timeline,
        "config": config,
        "urls": json.loads((outdir / "results.json").read_text())["urls"],
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    path = outdir / "report.html"
    path.write_text(TEMPLATE.replace("__DATA__", json.dumps(data).replace("</", "<\\/")))
    return path


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1])
    res = json.loads((d / "results.json").read_text())
    rows = json.loads((d / "summary.json").read_text())
    print(write_report(d, rows, res["browsers"], res["config"]))

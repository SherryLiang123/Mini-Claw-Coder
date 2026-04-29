from __future__ import annotations

import json
from html import escape
from pathlib import Path


def load_viewer_source(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Viewer input is empty: {path}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    else:
        if isinstance(payload, dict) and "iteration" in payload and "snapshot" in payload:
            return {
                "mode": "watch",
                "source_path": str(path),
                "entries": [payload],
            }
        return {
            "mode": "snapshot",
            "source_path": str(path),
            "snapshot": payload,
        }
    lines = [line for line in text.splitlines() if line.strip()]
    return {
        "mode": "watch",
        "source_path": str(path),
        "entries": [json.loads(line) for line in lines],
    }


def render_viewer_html(
    document: dict[str, object],
    *,
    title: str = "Mini Claw Runtime Viewer",
    refresh_seconds: float = 0.0,
    demo_mode: bool = False,
    demo_language: str = "bilingual",
    demo_focus: str = "auto",
    demo_script: str = "full",
) -> str:
    data_json = json.dumps(document, ensure_ascii=False).replace("</", "<\\/")
    safe_title = escape(title)
    refresh_tag = ""
    if float(refresh_seconds) > 0:
        refresh_tag = f'<meta http-equiv="refresh" content="{float(refresh_seconds):g}">'
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  __REFRESH_TAG__
  <title>__TITLE__</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #08111c;
      --bg-soft: #0d1928;
      --panel: rgba(16, 28, 46, 0.84);
      --panel-solid: #11213a;
      --panel-alt: #0d1a2c;
      --border: rgba(151, 184, 214, 0.18);
      --text: #edf6ff;
      --muted: #9cb1c5;
      --accent: #69f0d0;
      --accent-2: #ffbe6b;
      --accent-3: #7ac8ff;
      --ok: #8ce99a;
      --warn: #ffd166;
      --fail: #ff8ea1;
      --shadow: 0 24px 60px rgba(3, 7, 18, 0.42);
      --radius-xl: 28px;
      --radius-lg: 20px;
      --radius-md: 14px;
      --font-sans: "Aptos", "Trebuchet MS", "Segoe UI", sans-serif;
      --font-mono: "Cascadia Code", "Consolas", "SFMono-Regular", monospace;
    }

    * {
      box-sizing: border-box;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      color: var(--text);
      font-family: var(--font-sans);
      background:
        radial-gradient(circle at top left, rgba(105, 240, 208, 0.16), transparent 32%),
        radial-gradient(circle at top right, rgba(122, 200, 255, 0.18), transparent 28%),
        linear-gradient(160deg, #08111c 0%, #0c1523 44%, #08111c 100%);
      min-height: 100vh;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(rgba(255, 255, 255, 0.02) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.02) 1px, transparent 1px);
      background-size: 88px 88px;
      mask-image: linear-gradient(to bottom, rgba(0, 0, 0, 0.65), transparent 92%);
      opacity: 0.55;
    }

    .page {
      position: relative;
      max-width: 1320px;
      margin: 0 auto;
      padding: 28px 22px 56px;
    }

    .hero-panel,
    .panel,
    .story-card,
    .metric-card,
    .mini-metric {
      animation: rise 420ms ease-out both;
    }

    .hero-panel,
    .panel {
      border: 1px solid var(--border);
      border-radius: var(--radius-xl);
      background: linear-gradient(180deg, rgba(21, 36, 58, 0.88), rgba(10, 19, 33, 0.92));
      box-shadow: var(--shadow);
      backdrop-filter: blur(20px);
    }

    .hero-panel {
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.9fr);
      gap: 24px;
      padding: 28px;
      overflow: hidden;
      position: relative;
    }

    .hero-panel::after {
      content: "";
      position: absolute;
      width: 340px;
      height: 340px;
      border-radius: 50%;
      right: -140px;
      top: -120px;
      background: radial-gradient(circle, rgba(255, 190, 107, 0.18), transparent 68%);
      pointer-events: none;
    }

    .hero-copy {
      position: relative;
      z-index: 1;
      display: grid;
      gap: 14px;
      align-content: start;
    }

    .eyebrow,
    .section-label {
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
    }

    h1,
    h2,
    h3,
    p {
      margin: 0;
    }

    h1 {
      font-size: clamp(2.1rem, 5vw, 4rem);
      line-height: 0.96;
      letter-spacing: -0.045em;
      max-width: 12ch;
    }

    .lede {
      max-width: 64ch;
      font-size: 1.05rem;
      line-height: 1.7;
      color: var(--muted);
    }

    .hero-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 8px;
    }

    .meta-pill,
    .timeline button,
    .view-tabs button,
    .pill,
    .status-pill {
      border-radius: 999px;
      border: 1px solid var(--border);
      padding: 8px 14px;
      background: rgba(13, 26, 44, 0.72);
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1;
    }

    .demo-note {
      border-color: rgba(105, 240, 208, 0.35);
      color: var(--accent);
    }

    .hero-side {
      display: grid;
      gap: 16px;
      align-content: start;
      position: relative;
      z-index: 1;
    }

    .status-shell {
      border-radius: var(--radius-lg);
      background: linear-gradient(180deg, rgba(11, 23, 38, 0.88), rgba(17, 33, 58, 0.98));
      border: 1px solid var(--border);
      padding: 18px;
      display: grid;
      gap: 14px;
    }

    .status-pill {
      width: fit-content;
      padding: 10px 16px;
      font-size: 0.98rem;
      font-weight: 700;
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
    }

    .status-pill.ok {
      border-color: rgba(140, 233, 154, 0.35);
      color: var(--ok);
    }

    .status-pill.warn {
      border-color: rgba(255, 209, 102, 0.35);
      color: var(--warn);
    }

    .status-pill.fail {
      border-color: rgba(255, 142, 161, 0.35);
      color: var(--fail);
    }

    .mini-grid,
    .metrics-grid,
    .story-grid,
    .raw-grid {
      display: grid;
      gap: 14px;
    }

    .mini-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .mini-metric {
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: rgba(10, 19, 33, 0.72);
      padding: 12px 14px;
    }

    .mini-metric .metric-label {
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }

    .mini-metric .metric-value {
      margin-top: 8px;
      font-size: 1.45rem;
      font-weight: 700;
      letter-spacing: -0.04em;
    }

    .timeline {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 20px;
    }

    .timeline button,
    .view-tabs button {
      cursor: pointer;
      transition: transform 140ms ease, border-color 140ms ease, color 140ms ease, background 140ms ease;
      font-family: inherit;
    }

    .timeline button:hover,
    .view-tabs button:hover {
      transform: translateY(-1px);
      border-color: rgba(122, 200, 255, 0.35);
      color: var(--text);
    }

    .timeline button.active,
    .view-tabs button.active {
      color: var(--text);
      border-color: rgba(105, 240, 208, 0.42);
      background: linear-gradient(90deg, rgba(105, 240, 208, 0.16), rgba(122, 200, 255, 0.1));
      box-shadow: inset 0 0 0 1px rgba(105, 240, 208, 0.12);
    }

    .story-grid {
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      margin-top: 20px;
    }

    .story-card {
      position: relative;
      overflow: hidden;
      border-radius: var(--radius-lg);
      padding: 18px 18px 20px;
      border: 1px solid var(--border);
      background: linear-gradient(160deg, rgba(17, 33, 58, 0.92), rgba(9, 18, 31, 0.9));
      box-shadow: var(--shadow);
    }

    .story-card::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 3px;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      opacity: 0.85;
    }

    .story-kicker {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--accent-3);
    }

    .story-title {
      margin-top: 10px;
      font-size: 1.18rem;
      letter-spacing: -0.03em;
    }

    .story-body {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.68;
      font-size: 0.96rem;
    }

    .metrics-grid {
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      margin-top: 20px;
    }

    .metric-card {
      border-radius: var(--radius-lg);
      border: 1px solid var(--border);
      background: linear-gradient(180deg, rgba(14, 26, 44, 0.9), rgba(9, 18, 31, 0.92));
      padding: 16px 18px;
      box-shadow: var(--shadow);
    }

    .metric-card .metric-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .metric-card .metric-value {
      margin-top: 10px;
      font-size: 2rem;
      line-height: 1;
      font-weight: 700;
      letter-spacing: -0.06em;
    }

    .metric-card .metric-note {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.92rem;
    }

    .view-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 22px;
    }

    .content-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.85fr);
      gap: 18px;
      align-items: start;
      margin-top: 18px;
    }

    .panel {
      padding: 22px;
    }

    .panel-header {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: start;
    }

    .panel-header h2 {
      margin-top: 6px;
      font-size: 1.5rem;
      letter-spacing: -0.04em;
    }

    .panel-body {
      display: grid;
      gap: 18px;
      margin-top: 18px;
    }

    .body-block {
      display: grid;
      gap: 10px;
    }

    .body-block h3,
    .raw-grid h3 {
      font-size: 1rem;
      letter-spacing: -0.02em;
    }

    .body-copy,
    .talk-track,
    .rail-copy {
      color: var(--muted);
      line-height: 1.72;
      font-size: 0.97rem;
    }

    .detail-list,
    .rail-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 10px;
    }

    .detail-list li,
    .rail-item {
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: rgba(11, 23, 38, 0.68);
      padding: 12px 14px;
    }

    .detail-list li {
      color: var(--muted);
      line-height: 1.65;
    }

    .compact-grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }

    .compact-card {
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: rgba(11, 23, 38, 0.68);
      padding: 14px;
    }

    .compact-card .metric-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .compact-card .metric-value {
      margin-top: 8px;
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: -0.04em;
    }

    .pill-row {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .pill {
      font-size: 0.88rem;
    }

    .sidebar {
      display: grid;
      gap: 18px;
    }

    .rail-meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 8px;
    }

    .rail-tag {
      border-radius: 999px;
      border: 1px solid var(--border);
      padding: 4px 9px;
      font-size: 0.78rem;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.03);
    }

    .rail-title {
      font-size: 0.96rem;
      letter-spacing: -0.02em;
    }

    .rail-copy {
      margin-top: 8px;
      font-size: 0.9rem;
    }

    .rail-copy code,
    .body-copy code {
      font-family: var(--font-mono);
      color: var(--text);
      background: rgba(255, 255, 255, 0.04);
      padding: 2px 6px;
      border-radius: 999px;
    }

    .rail-copy code {
      border-radius: 8px;
    }

    .status-ok {
      color: var(--ok);
    }

    .status-warn {
      color: var(--warn);
    }

    .status-fail {
      color: var(--fail);
    }

    .raw-panel {
      margin-top: 18px;
    }

    .raw-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      margin-top: 16px;
    }

    pre {
      margin: 10px 0 0;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
      background: rgba(5, 12, 22, 0.92);
      color: #d9e8f7;
      padding: 14px;
      overflow: auto;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.58;
      max-height: 520px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .hidden {
      display: none !important;
    }

    @media (max-width: 1080px) {
      .hero-panel,
      .content-grid,
      .raw-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 760px) {
      .page {
        padding: 16px 14px 42px;
      }

      .hero-panel,
      .panel {
        padding: 18px;
      }

      h1 {
        max-width: none;
      }

      .metrics-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .mini-grid {
        grid-template-columns: 1fr 1fr;
      }
    }

    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
  </style>
</head>
<body>
  <div class="page">
    <section class="hero-panel">
      <div class="hero-copy">
        <div class="eyebrow">Mini Claw Runtime Demo</div>
        <h1>__TITLE__</h1>
        <p class="lede" id="hero-summary"></p>
        <div class="hero-meta">
          <span class="meta-pill" id="source-line"></span>
          <span class="meta-pill" id="mode-line"></span>
          <span class="meta-pill demo-note" id="demo-note"></span>
        </div>
      </div>
      <div class="hero-side">
        <div class="status-shell">
          <div class="section-label">Live health</div>
          <div class="status-pill" id="status-pill"></div>
          <div class="mini-grid" id="hero-mini-stats"></div>
        </div>
      </div>
    </section>

    <div class="timeline" id="iteration-toolbar"></div>

    <section class="story-grid" id="story-grid"></section>

    <section class="metrics-grid" id="headline-stats"></section>

    <div class="view-tabs" id="view-tabs"></div>

    <div class="content-grid">
      <section class="panel">
        <div class="panel-header">
          <div>
            <div class="section-label" id="panel-kicker"></div>
            <h2 id="panel-title"></h2>
          </div>
          <div class="meta-pill" id="panel-meta"></div>
        </div>
        <div class="panel-body" id="panel-body"></div>
      </section>

      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header">
            <div>
              <div class="section-label">Narrative</div>
              <h2>Talk Track</h2>
            </div>
          </div>
          <p class="talk-track" id="talk-track"></p>
        </section>

        <section class="panel">
          <div class="panel-header">
            <div>
              <div class="section-label">Signal rail</div>
              <h2>Evidence</h2>
            </div>
          </div>
          <div class="rail-list" id="evidence-rail"></div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <div>
              <div class="section-label">Section delta</div>
              <h2>Change Map</h2>
            </div>
          </div>
          <pre id="delta-view"></pre>
        </section>
      </aside>
    </div>

    <section class="panel raw-panel" id="raw-panel">
      <div class="panel-header">
        <div>
          <div class="section-label">Source payload</div>
          <h2>Raw Data</h2>
        </div>
        <div class="meta-pill" id="raw-meta"></div>
      </div>
      <div class="raw-grid">
        <div>
          <h3>Changes By Section</h3>
          <pre id="changes-by-section"></pre>
        </div>
        <div>
          <h3>Snapshot JSON</h3>
          <pre id="snapshot-view"></pre>
        </div>
      </div>
    </section>
  </div>

  <script id="viewer-data" type="application/json">__DATA__</script>
  <script>
    const doc = JSON.parse(document.getElementById("viewer-data").textContent);
    const demoMode = __DEMO_MODE__;
    const demoLanguage = "__DEMO_LANGUAGE__";
    const demoFocus = "__DEMO_FOCUS__";
    const demoScript = "__DEMO_SCRIPT__";

    const sourceLine = document.getElementById("source-line");
    const modeLine = document.getElementById("mode-line");
    const demoNote = document.getElementById("demo-note");
    const statusPill = document.getElementById("status-pill");
    const heroSummary = document.getElementById("hero-summary");
    const heroMiniStats = document.getElementById("hero-mini-stats");
    const storyGrid = document.getElementById("story-grid");
    const stats = document.getElementById("headline-stats");
    const toolbar = document.getElementById("iteration-toolbar");
    const tabs = document.getElementById("view-tabs");
    const panelKicker = document.getElementById("panel-kicker");
    const panelTitle = document.getElementById("panel-title");
    const panelMeta = document.getElementById("panel-meta");
    const panelBody = document.getElementById("panel-body");
    const talkTrack = document.getElementById("talk-track");
    const evidenceRail = document.getElementById("evidence-rail");
    const deltaView = document.getElementById("delta-view");
    const rawPanel = document.getElementById("raw-panel");
    const rawMeta = document.getElementById("raw-meta");
    const changesBySection = document.getElementById("changes-by-section");
    const snapshotView = document.getElementById("snapshot-view");

    const TAB_ORDER = ["overview", "runtime", "team", "evidence", "raw"];
    const TAB_META = {
      overview: {
        label: "Overview",
        kicker: "Story-first",
        title: "Why this runtime is worth demoing",
      },
      runtime: {
        label: "Runtime",
        kicker: "Execution surface",
        title: "Trace, routing, and runtime pressure",
      },
      team: {
        label: "Team",
        kicker: "Control surface",
        title: "Queue state, sessions, and operators",
      },
      evidence: {
        label: "Evidence",
        kicker: "Proof chain",
        title: "Doctor findings, failures, and tool evidence",
      },
      raw: {
        label: "Raw Data",
        kicker: "Protocol",
        title: "Structured payload behind the presentation layer",
      },
    };

    const state = {
      activeIndex: 0,
      activeTab: "overview",
    };

    sourceLine.textContent = `${doc.mode} source: ${doc.source_path}`;
    modeLine.textContent = `demo_language=${demoLanguage} | demo_focus=${demoFocus}`;
    demoNote.textContent = demoMode ? "Demo mode: first screen tuned for interview walkthroughs." : "Presentation view: structured data turned into a product-style walkthrough.";

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function stringify(value) {
      return JSON.stringify(value, null, 2);
    }

    function compactText(value, maxChars = 180) {
      const text = String(value ?? "").replace(/\s+/g, " ").trim();
      if (!text) return "(empty)";
      return text.length > maxChars ? `${text.slice(0, maxChars - 1)}…` : text;
    }

    function statusClass(value) {
      if (value === "fail") return "status-fail";
      if (value === "warn") return "status-warn";
      if (value === "ok") return "status-ok";
      return "";
    }

    function statusModifier(value) {
      if (value === "fail" || value === "warn" || value === "ok") return value;
      return "";
    }

    function readArray(value) {
      return Array.isArray(value) ? value : [];
    }

    function readObject(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function snapshotFromEntry(entry) {
      return entry && typeof entry === "object" && "snapshot" in entry ? (entry.snapshot || {}) : (entry || {});
    }

    function getTeamBoardSnapshot(snapshot) {
      if (snapshot && snapshot.team_board) return readObject(snapshot.team_board);
      if (snapshot && snapshot.team_status && snapshot.runtime_health && snapshot.runtime_counts) return readObject(snapshot);
      return null;
    }

    function getDashboardSnapshot(snapshot) {
      if (snapshot && snapshot.dashboard) return readObject(snapshot.dashboard);
      if (snapshot && (snapshot.trace_summary || snapshot.session_count !== undefined || snapshot.tool_output_count !== undefined)) {
        return readObject(snapshot);
      }
      return null;
    }

    function getDoctorSnapshot(snapshot) {
      if (snapshot && snapshot.doctor) return readObject(snapshot.doctor);
      const teamBoard = getTeamBoardSnapshot(snapshot);
      if (teamBoard && teamBoard.runtime_health) return readObject(teamBoard.runtime_health);
      return null;
    }

    function getReplaySnapshot(snapshot) {
      return snapshot && snapshot.session_replay ? readObject(snapshot.session_replay) : null;
    }

    function getExportTarget(entry, snapshot) {
      if (entry && entry.export_target) return String(entry.export_target);
      if (getTeamBoardSnapshot(snapshot) && !getDashboardSnapshot(snapshot)) return "team-board";
      if (getDashboardSnapshot(snapshot) && !snapshot.team_board && !snapshot.doctor) return "dashboard";
      return doc.mode === "watch" ? "watch" : "bundle";
    }

    function resolveDemoFocus(snapshot) {
      const hasTeam = !!getTeamBoardSnapshot(snapshot);
      const hasRuntime = !!getDashboardSnapshot(snapshot);
      if (demoFocus === "team") {
        if (hasTeam) return "team";
        if (hasRuntime) return "runtime";
      }
      if (demoFocus === "runtime") {
        if (hasRuntime) return "runtime";
        if (hasTeam) return "team";
      }
      if (hasTeam) return "team";
      return "runtime";
    }

    function deriveCounts(snapshot) {
      const dashboard = getDashboardSnapshot(snapshot) || {};
      const trace = readObject(dashboard.trace_summary);
      const teamBoard = getTeamBoardSnapshot(snapshot) || {};
      const runtimeCounts = readObject(teamBoard.runtime_counts);
      const teamStatus = readObject(teamBoard.team_status);
      const latestReplay = readObject(dashboard.latest_session_replay);

      return {
        traceEvents: trace.total_events || runtimeCounts.trace_events || 0,
        toolCalls: trace.tool_calls || runtimeCounts.tool_calls || 0,
        failedToolCalls: trace.failed_tool_calls || runtimeCounts.failed_tool_calls || 0,
        contextBuilds: trace.context_builds || runtimeCounts.context_builds || 0,
        toolOutputs: dashboard.tool_output_count || 0,
        truncatedToolOutputs: dashboard.truncated_tool_output_count || trace.truncated_tool_outputs || 0,
        sessions: dashboard.session_count || 0,
        replayTurns: getReplaySnapshot(snapshot) ? getReplaySnapshot(snapshot).total_turns || 0 : 0,
        readyTasks: readArray(dashboard.ready_tasks).length || readArray(teamStatus.ready_tasks).length,
        activeTasks: readArray(teamStatus.active_tasks).length,
        blockedTasks: readArray(teamStatus.blocked_tasks).length,
        backgroundRuns: readObject(teamBoard.background_runs).total || 0,
        pendingMemory:
          readObject(dashboard.memory_candidate_status_counts).pending ||
          readObject(readObject(runtimeCounts).memory_candidate_status_counts).pending ||
          0,
        latestReplayToolCalls: latestReplay.tool_calls || 0,
      };
    }

    function overallStatus(snapshot) {
      const doctor = getDoctorSnapshot(snapshot);
      if (doctor && doctor.status) return String(doctor.status);
      const teamBoard = getTeamBoardSnapshot(snapshot);
      if (teamBoard && teamBoard.runtime_health && teamBoard.runtime_health.status) {
        return String(teamBoard.runtime_health.status);
      }
      return "n/a";
    }

    function heroSummaryText(entry) {
      const snapshot = snapshotFromEntry(entry);
      const focus = resolveDemoFocus(snapshot);
      const counts = deriveCounts(snapshot);
      const status = overallStatus(snapshot);
      if (focus === "team") {
        return `A front-end demo for the team control surface: ${counts.readyTasks} ready tasks, ${counts.activeTasks} active tasks, ${counts.backgroundRuns} background runs, and runtime health currently ${status}.`;
      }
      return `A front-end demo for the coding-agent runtime: ${counts.traceEvents} trace events, ${counts.toolCalls} tool calls, ${counts.truncatedToolOutputs} truncated outputs, and runtime health currently ${status}.`;
    }

    function renderMiniStats(snapshot) {
      const counts = deriveCounts(snapshot);
      const items = [
        ["Trace events", counts.traceEvents],
        ["Tool calls", counts.toolCalls],
        ["Ready tasks", counts.readyTasks],
        ["Sessions", counts.sessions],
      ];
      heroMiniStats.innerHTML = items
        .map(
          ([label, value]) => `
            <div class="mini-metric">
              <div class="metric-label">${escapeHtml(label)}</div>
              <div class="metric-value">${escapeHtml(value)}</div>
            </div>
          `
        )
        .join("");
    }

    function storyCards(entry) {
      const snapshot = snapshotFromEntry(entry);
      const dashboard = getDashboardSnapshot(snapshot) || {};
      const teamBoard = getTeamBoardSnapshot(snapshot) || {};
      const counts = deriveCounts(snapshot);
      const doctor = getDoctorSnapshot(snapshot) || {};
      const latestSession = readObject(teamBoard.latest_session || dashboard.latest_session_replay || {});
      const failureReports = readArray(readObject(dashboard.trace_summary).failure_reports);

      return [
        {
          kicker: "Control",
          title: "Execution is constrained on purpose",
          body: `This snapshot shows ${counts.readyTasks} ready tasks, ${counts.activeTasks} active tasks, and ${counts.backgroundRuns} background runs. The demo starts from control surface data instead of dropping straight into raw logs.`,
        },
        {
          kicker: "Observability",
          title: "The runtime explains itself",
          body: `Health is ${doctor.status || "n/a"}, with ${counts.traceEvents} trace events, ${counts.toolCalls} tool calls, and ${counts.truncatedToolOutputs} truncated outputs captured for follow-up inspection.`,
        },
        {
          kicker: "Evidence",
          title: "Failures stay attached to proof",
          body: failureReports.length
            ? `There are ${failureReports.length} captured failure reports in the trace, so the demo can move from symptom to root-cause evidence without leaving the page.`
            : `The latest replay path records ${counts.latestReplayToolCalls} tool calls, which lets you show not only the final answer but also how the runtime got there.`,
        },
      ];
    }

    function metricCards(snapshot) {
      const counts = deriveCounts(snapshot);
      const doctor = getDoctorSnapshot(snapshot) || {};
      return [
        ["Health", doctor.status || overallStatus(snapshot), doctor.summary || "No doctor summary available."],
        ["Trace Events", counts.traceEvents, "How much runtime activity is available for replay and diagnosis."],
        ["Tool Calls", counts.toolCalls, "Actual tool traffic, not only final assistant prose."],
        ["Failed Calls", counts.failedToolCalls, "Pressure indicator for debugging and reliability demos."],
        ["Ready Tasks", counts.readyTasks, "Queue depth that makes the control-surface story tangible."],
        ["Tool Outputs", counts.toolOutputs, "Stored outputs available for evidence lookup and replay."],
      ];
    }

    function listMarkup(items, emptyText = "Nothing to show yet.") {
      const safeItems = readArray(items);
      if (!safeItems.length) {
        return `<ul class="detail-list"><li>${escapeHtml(emptyText)}</li></ul>`;
      }
      return `<ul class="detail-list">${safeItems
        .map((item) => `<li>${item}</li>`)
        .join("")}</ul>`;
    }

    function compactGridMarkup(items) {
      return `<div class="compact-grid">${items
        .map(
          ([label, value, note]) => `
            <div class="compact-card">
              <div class="metric-label">${escapeHtml(label)}</div>
              <div class="metric-value">${escapeHtml(value)}</div>
              <div class="body-copy">${escapeHtml(note)}</div>
            </div>
          `
        )
        .join("")}</div>`;
    }

    function overviewMarkup(entry) {
      const snapshot = snapshotFromEntry(entry);
      const counts = deriveCounts(snapshot);
      const doctor = getDoctorSnapshot(snapshot) || {};
      const exportTarget = getExportTarget(entry, snapshot);
      const changes = readArray(entry.changes);
      const pills = [
        `target=${exportTarget}`,
        `focus=${resolveDemoFocus(snapshot)}`,
        `doctor=${doctor.status || "n/a"}`,
        `sessions=${counts.sessions}`,
      ];
      const bullets = [
        `This page turns runtime bundle data into a story-first demo rather than a raw JSON dump.`,
        `The current snapshot carries ${counts.traceEvents} trace events, ${counts.toolCalls} tool calls, and ${counts.toolOutputs} stored tool outputs.`,
        `Health is ${doctor.status || "n/a"}, so the audience can see operational status before they inspect low-level details.`,
      ];
      return `
        <div class="body-block">
          <h3>Positioning</h3>
          <div class="pill-row">${pills.map((pill) => `<div class="pill">${escapeHtml(pill)}</div>`).join("")}</div>
        </div>
        <div class="body-block">
          <h3>What to say first</h3>
          ${listMarkup(bullets.map((item) => escapeHtml(item)))}
        </div>
        <div class="body-block">
          <h3>Current change lines</h3>
          ${listMarkup(
            changes.map((line) => escapeHtml(line)),
            "No delta lines in this snapshot. Use this when you want to present a stable baseline."
          )}
        </div>
      `;
    }

    function runtimeMarkup(entry) {
      const snapshot = snapshotFromEntry(entry);
      const dashboard = getDashboardSnapshot(snapshot) || {};
      const trace = readObject(dashboard.trace_summary);
      const routeReasons = Object.entries(readObject(trace.route_reason_counts));
      const failureReports = readArray(trace.failure_reports);
      const rows = [
        ["Trace events", trace.total_events || 0, "Stored runtime events that can be replayed later."],
        ["Tool calls", trace.tool_calls || 0, "Concrete tool usage inside the runtime."],
        ["Failed tool calls", trace.failed_tool_calls || 0, "Calls that need investigation."],
        ["Context builds", trace.context_builds || 0, "How many prompt packets were assembled."],
      ];
      const routeLines = routeReasons.length
        ? routeReasons.map(([reason, count]) => `${escapeHtml(reason)}: ${escapeHtml(count)}`)
        : ["No route reason counts recorded in this snapshot."];
      const failureLines = failureReports.length
        ? failureReports.map((item) => `${escapeHtml(item.root_cause || "UNKNOWN")}: ${escapeHtml(compactText(item.suggested_action || item.evidence || ""))}`)
        : ["No failure reports captured in this snapshot."];
      return `
        <div class="body-block">
          <h3>Runtime pressure</h3>
          ${compactGridMarkup(rows)}
        </div>
        <div class="body-block">
          <h3>Route reasons</h3>
          ${listMarkup(routeLines)}
        </div>
        <div class="body-block">
          <h3>Failure reports</h3>
          ${listMarkup(failureLines)}
        </div>
      `;
    }

    function teamMarkup(entry) {
      const snapshot = snapshotFromEntry(entry);
      const teamBoard = getTeamBoardSnapshot(snapshot) || {};
      const teamStatus = readObject(teamBoard.team_status);
      const latestSession = readObject(teamBoard.latest_session);
      const latestReplay = readObject(teamBoard.latest_session_replay);
      const queueCards = [
        ["Ready", readArray(teamStatus.ready_tasks).length, "Tasks that can be picked up immediately."],
        ["Active", readArray(teamStatus.active_tasks).length, "Tasks already assigned to a worker."],
        ["Blocked", readArray(teamStatus.blocked_tasks).length, "Tasks waiting on dependencies or manual help."],
        ["Background", readObject(teamBoard.background_runs).total || 0, "Long-running commands tracked outside the main loop."],
      ];
      const readyLines = readArray(teamStatus.ready_tasks).map((item) => escapeHtml(compactText(`${item.task_id || "task"} - ${item.objective || "ready task"}`)));
      const activeLines = readArray(teamStatus.active_tasks).map((item) => escapeHtml(compactText(`${item.task_id || "task"} - ${item.status || "in_progress"} - ${item.workspace_path || ""}`)));
      const sessionLines = latestSession.session_id
        ? [
            `Latest session: ${escapeHtml(latestSession.session_id)} (${escapeHtml(latestSession.name || "-")})`,
            `Replay snapshot: completed=${escapeHtml(latestReplay.completed_turns || 0)}, success=${escapeHtml(latestReplay.successful_turns || 0)}, failed=${escapeHtml(latestReplay.failed_turns || 0)}`,
          ]
        : ["No session metadata recorded in this snapshot."];
      return `
        <div class="body-block">
          <h3>Queue health</h3>
          ${compactGridMarkup(queueCards)}
        </div>
        <div class="body-block">
          <h3>Ready work</h3>
          ${listMarkup(readyLines, "No ready tasks right now.")}
        </div>
        <div class="body-block">
          <h3>Active work</h3>
          ${listMarkup(activeLines, "No active tasks right now.")}
        </div>
        <div class="body-block">
          <h3>Session trail</h3>
          ${listMarkup(sessionLines)}
        </div>
      `;
    }

    function evidenceMarkup(entry) {
      const snapshot = snapshotFromEntry(entry);
      const doctor = getDoctorSnapshot(snapshot) || {};
      const dashboard = getDashboardSnapshot(snapshot) || {};
      const findings = readArray(doctor.findings);
      const latestOutputs = readArray(dashboard.latest_tool_outputs).slice(0, 4);
      const failureReports = readArray(readObject(dashboard.trace_summary).failure_reports);
      const findingLines = findings.length
        ? findings.map((finding) => `${escapeHtml(finding.code || finding.category || "finding")}: ${escapeHtml(compactText(finding.summary || finding.detail || ""))}`)
        : ["No doctor findings captured in this snapshot."];
      const outputLines = latestOutputs.length
        ? latestOutputs.map((item) => `${escapeHtml(item.tool || "tool")} ${escapeHtml(item.output_id || "")}: ${escapeHtml(compactText(item.preview || ""))}`)
        : ["No stored tool outputs yet."];
      const failureLines = failureReports.length
        ? failureReports.map((item) => `${escapeHtml(item.root_cause || "UNKNOWN")}: ${escapeHtml(compactText(item.evidence || item.suggested_action || ""))}`)
        : ["No failure reports attached to the current trace."];
      return `
        <div class="body-block">
          <h3>Doctor findings</h3>
          ${listMarkup(findingLines)}
        </div>
        <div class="body-block">
          <h3>Failure evidence</h3>
          ${listMarkup(failureLines)}
        </div>
        <div class="body-block">
          <h3>Recent tool outputs</h3>
          ${listMarkup(outputLines)}
        </div>
      `;
    }

    function rawMarkup(entry) {
      const snapshot = snapshotFromEntry(entry);
      return `
        <div class="body-block">
          <h3>What this tab is for</h3>
          <p class="body-copy">Use the raw view when you need to prove that the presentation layer is only a lens over the original protocol objects. The JSON block below is the exact snapshot currently driving the page.</p>
        </div>
        <div class="body-block">
          <h3>Snapshot shape</h3>
          ${listMarkup(
            Object.keys(readObject(snapshot)).map((key) => escapeHtml(key)),
            "This snapshot is empty."
          )}
        </div>
      `;
    }

    function panelMarkup(entry, tab) {
      if (tab === "runtime") return runtimeMarkup(entry);
      if (tab === "team") return teamMarkup(entry);
      if (tab === "evidence") return evidenceMarkup(entry);
      if (tab === "raw") return rawMarkup(entry);
      return overviewMarkup(entry);
    }

    function buildTalkTrack(entry) {
      const snapshot = snapshotFromEntry(entry);
      const counts = deriveCounts(snapshot);
      const status = overallStatus(snapshot);
      const focus = resolveDemoFocus(snapshot);

      const englishTeam = [
        "Open with the control surface, not the final answer. That makes queue state and execution pressure visible before you talk about models.",
        `Right now the team layer shows ${counts.readyTasks} ready tasks, ${counts.activeTasks} active tasks, ${counts.backgroundRuns} background runs, and runtime health ${status}.`,
        "Then pivot to the evidence rail on the right to explain why the health score looks the way it does.",
      ];
      const englishRuntime = [
        "This page is about runtime behavior, not only assistant prose.",
        `The current snapshot carries ${counts.traceEvents} trace events, ${counts.toolCalls} tool calls, ${counts.failedToolCalls} failed tool calls, and ${counts.toolOutputs} stored tool outputs.`,
        "That lets you demo controllability, observability, and failure diagnosis in one screen.",
      ];
      const chineseTeam = [
        "先从 control surface 讲，不先讲最终答案。这样队列状态、执行压力和运行健康度会更清楚。",
        `当前 team 层有 ${counts.readyTasks} 个 ready task、${counts.activeTasks} 个 active task、${counts.backgroundRuns} 个 background run，runtime health 是 ${status}。`,
        "然后再切到右侧 evidence rail，解释这个 health 状态是怎么来的。",
      ];
      const chineseRuntime = [
        "这个页面不是只看模型最后说了什么，而是把 runtime 行为本身展示出来。",
        `当前快照里有 ${counts.traceEvents} 个 trace event、${counts.toolCalls} 次 tool call、${counts.failedToolCalls} 次失败调用，以及 ${counts.toolOutputs} 份可回放的 tool output。`,
        "这样演示时可以把可控性、可观测性和失败诊断放在同一条叙事线上讲清楚。",
      ];

      const english = focus === "team" ? englishTeam : englishRuntime;
      const chinese = focus === "team" ? chineseTeam : chineseRuntime;
      const englishTrack = demoScript === "short" ? english.slice(0, 2) : english;
      const chineseTrack = demoScript === "short" ? chinese.slice(0, 2) : chinese;

      if (demoLanguage === "en") return englishTrack.join("\\n\\n");
      if (demoLanguage === "zh") return chineseTrack.join("\\n\\n");
      return `${englishTrack.join("\\n\\n")}\\n\\n---\\n\\n${chineseTrack.join("\\n\\n")}`;
    }

    function buildEvidenceRail(entry) {
      const snapshot = snapshotFromEntry(entry);
      const doctor = getDoctorSnapshot(snapshot) || {};
      const dashboard = getDashboardSnapshot(snapshot) || {};
      const findings = readArray(doctor.findings).slice(0, 3).map((finding) => ({
        tags: [finding.severity || "info", finding.category || "doctor"],
        title: finding.summary || "Doctor finding",
        copy: finding.detail || "No detail supplied.",
      }));
      const outputs = readArray(dashboard.latest_tool_outputs).slice(0, 2).map((item) => ({
        tags: [item.tool || "tool", item.truncated ? "truncated" : "stored"],
        title: item.output_id || "tool-output",
        copy: item.lookup_hint || compactText(item.preview || ""),
      }));
      const failures = readArray(readObject(dashboard.trace_summary).failure_reports).slice(0, 2).map((item) => ({
        tags: [item.root_cause || "failure", "trace"],
        title: compactText(item.suggested_action || "Failure report"),
        copy: compactText(item.evidence || ""),
      }));

      const items = [...findings, ...failures, ...outputs];
      if (!items.length) {
        return [
          {
            tags: ["stable"],
            title: "No high-signal evidence yet",
            copy: "Run a task or export a richer bundle to populate the rail.",
          },
        ];
      }
      return items.slice(0, 5);
    }

    function defaultTab(snapshot) {
      if (resolveDemoFocus(snapshot) === "team") return "team";
      return demoMode ? "overview" : "runtime";
    }

    function renderTabs() {
      tabs.innerHTML = TAB_ORDER.map((key) => {
        const item = TAB_META[key];
        const activeClass = key === state.activeTab ? "active" : "";
        return `<button class="${activeClass}" data-tab="${key}">${escapeHtml(item.label)}</button>`;
      }).join("");
      tabs.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
          state.activeTab = button.dataset.tab || "overview";
          renderCurrent();
        });
      });
    }

    function renderIterationToolbar(entries) {
      if (doc.mode !== "watch") {
        toolbar.classList.add("hidden");
        return;
      }
      toolbar.classList.remove("hidden");
      toolbar.innerHTML = entries
        .map((entry, index) => {
          const label = entry.iteration ? `Iteration ${entry.iteration}` : `Iteration ${index + 1}`;
          const activeClass = index === state.activeIndex ? "active" : "";
          return `<button class="${activeClass}" data-index="${index}">${escapeHtml(label)}</button>`;
        })
        .join("");
      toolbar.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
          state.activeIndex = Number(button.dataset.index || 0);
          renderCurrent();
        });
      });
    }

    function renderCurrent() {
      const entries = doc.mode === "watch" ? readArray(doc.entries) : [{ snapshot: doc.snapshot || {} }];
      if (!entries.length) {
        return;
      }
      const entry = entries[Math.min(state.activeIndex, entries.length - 1)];
      const snapshot = snapshotFromEntry(entry);
      const status = overallStatus(snapshot);
      const counts = deriveCounts(snapshot);
      const exportTarget = getExportTarget(entry, snapshot);
      const tab = state.activeTab || defaultTab(snapshot);

      heroSummary.textContent = heroSummaryText(entry);
      statusPill.className = `status-pill ${statusModifier(status)}`;
      statusPill.textContent = status.toUpperCase();
      renderMiniStats(snapshot);

      storyGrid.innerHTML = storyCards(entry)
        .map(
          (card) => `
            <article class="story-card">
              <div class="story-kicker">${escapeHtml(card.kicker)}</div>
              <div class="story-title">${escapeHtml(card.title)}</div>
              <div class="story-body">${escapeHtml(card.body)}</div>
            </article>
          `
        )
        .join("");

      stats.innerHTML = metricCards(snapshot)
        .map(
          ([label, value, note]) => `
            <article class="metric-card">
              <div class="metric-label">${escapeHtml(label)}</div>
              <div class="metric-value ${statusClass(String(value).toLowerCase())}">${escapeHtml(value)}</div>
              <div class="metric-note">${escapeHtml(note)}</div>
            </article>
          `
        )
        .join("");

      const meta = TAB_META[tab];
      panelKicker.textContent = meta.kicker;
      panelTitle.textContent = meta.title;
      panelMeta.textContent = `iteration=${entry.iteration || state.activeIndex + 1} | target=${exportTarget}`;
      panelBody.innerHTML = panelMarkup(entry, tab);

      talkTrack.textContent = buildTalkTrack(entry);

      evidenceRail.innerHTML = buildEvidenceRail(entry)
        .map(
          (item) => `
            <article class="rail-item">
              <div class="rail-meta">${readArray(item.tags)
                .map((tag) => `<span class="rail-tag">${escapeHtml(tag)}</span>`)
                .join("")}</div>
              <div class="rail-title">${escapeHtml(item.title)}</div>
              <div class="rail-copy">${escapeHtml(item.copy)}</div>
            </article>
          `
        )
        .join("");

      deltaView.textContent = stringify(entry.changes_by_section_delta || {});
      rawMeta.textContent = `changes=${readArray(entry.changes).length} | ready_tasks=${counts.readyTasks} | failed_calls=${counts.failedToolCalls}`;
      changesBySection.textContent = stringify(entry.changes_by_section || {});
      snapshotView.textContent = stringify(snapshot);
      rawPanel.classList.toggle("hidden", tab !== "raw");

      tabs.querySelectorAll("button").forEach((button) => {
        button.classList.toggle("active", button.dataset.tab === tab);
      });

      toolbar.querySelectorAll("button").forEach((button, index) => {
        button.classList.toggle("active", index === state.activeIndex);
      });
    }

    const initialEntries = doc.mode === "watch" ? readArray(doc.entries) : [{ snapshot: doc.snapshot || {} }];
    const initialSnapshot = snapshotFromEntry(initialEntries[0] || {});
    state.activeTab = defaultTab(initialSnapshot);
    renderIterationToolbar(initialEntries);
    renderTabs();
    renderCurrent();
  </script>
</body>
</html>
"""
    return (
        template.replace("__REFRESH_TAG__", refresh_tag)
        .replace("__DEMO_MODE__", "true" if demo_mode else "false")
        .replace("__DEMO_LANGUAGE__", demo_language)
        .replace("__DEMO_FOCUS__", demo_focus)
        .replace("__DEMO_SCRIPT__", demo_script)
        .replace("__TITLE__", safe_title)
        .replace("__DATA__", data_json)
    )

"""
XTP Analyser — Dashboard
========================
A lightweight Flask web UI that lets the user:
  • Generate a fresh pair of XTP programs + Bin2Bin report via the AI pipeline.
  • Upload / drag-and-drop existing Program A, Program B, and Bin2Bin files.
  • View all three files side-by-side in a clean browser dashboard.

Usage
-----
    python -m XTPAnalyser.dashboard
    # then open http://127.0.0.1:5000
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template_string, request

load_dotenv(dotenv_path=".env" if os.path.exists(".env") else ".env.example")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB upload limit

OUTPUT_FOLDER = Path("Programas")
OUTPUT_FOLDER.mkdir(exist_ok=True)

_PROG_A   = OUTPUT_FOLDER / "Program_A.xtp"
_PROG_B   = OUTPUT_FOLDER / "Program_B.xtp"
_BIN2BIN  = OUTPUT_FOLDER / "Bin2Bin_Matrix.csv"

# Generation state (thread-safe via lock)
_gen_lock = threading.Lock()
_gen_state: dict = {"running": False, "log": [], "done": False, "error": None}

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>XTP Analyser — Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system,"Segoe UI",system-ui,sans-serif; background:#0f1117; color:#e2e8f0; min-height:100vh; }

  /* ── Header ── */
  header { display:flex; align-items:center; justify-content:space-between;
    padding:14px 28px; background:#161b27; border-bottom:1px solid #2d3748; }
  header h1 { font-size:1.1rem; font-weight:700; letter-spacing:.04em; color:#a78bfa; }
  header span { font-size:.78rem; color:#64748b; }

  /* ── Toolbar ── */
  .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center;
    padding:14px 28px; background:#161b27; border-bottom:1px solid #2d3748; }
  button { cursor:pointer; border:none; border-radius:6px; padding:8px 18px;
    font-size:.83rem; font-weight:600; transition:opacity .15s; }
  button:hover { opacity:.85; }
  button:disabled { opacity:.4; cursor:not-allowed; }
  .btn-primary   { background:#7c3aed; color:#fff; }
  .btn-secondary { background:#1e293b; color:#94a3b8; border:1px solid #334155; }
  .sep { width:1px; height:22px; background:#2d3748; }

  /* ── Upload dropzone ── */
  .drop-zone { display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:6px; border:2px dashed #334155; border-radius:8px;
    padding:20px 30px; min-width:180px; cursor:pointer; transition:border-color .2s;
    background:#0f1117; }
  .drop-zone:hover, .drop-zone.over { border-color:#7c3aed; }
  .drop-zone input[type=file] { display:none; }
  .drop-zone .dz-label { font-size:.75rem; color:#64748b; text-align:center; }
  .drop-zone .dz-title { font-size:.82rem; font-weight:600; color:#94a3b8; }

  /* ── Main layout ── */
  .layout { display:flex; flex-direction:column; height:calc(100vh - 113px); overflow:hidden; }

  /* top row: two programs side by side — takes all remaining height */
  .top-row { display:grid; grid-template-columns:1fr 1fr; flex:1; min-height:0; overflow:hidden; }

  /* bottom row: matrix full width, fixed height, scrollable */
  .bottom-row { display:flex; flex-direction:column; height:260px;
    border-top:2px solid #2d3748; flex-shrink:0; }

  .panel { display:flex; flex-direction:column; overflow:hidden;
    border-right:1px solid #1e293b; }
  .panel:last-child { border-right:none; }
  .panel-header { display:flex; align-items:center; justify-content:space-between;
    padding:10px 16px; background:#161b27; border-bottom:1px solid #2d3748;
    font-size:.78rem; font-weight:700; letter-spacing:.08em; color:#7c3aed;
    flex-shrink:0; }
  .panel-header .badge { font-size:.68rem; font-weight:500; color:#64748b;
    background:#1e293b; padding:2px 8px; border-radius:20px; letter-spacing:.03em; }
  .panel-body { flex:1; overflow:auto; padding:0; min-height:0; }

  /* ── Code viewer ── */
  pre.xtp-code { margin:0; padding:16px 20px; font-family:"Cascadia Code","Fira Code",
    "Consolas",monospace; font-size:.78rem; line-height:1.65; white-space:pre-wrap;
    word-break:break-word; color:#cbd5e1; background:#0c0f1a; }
  pre.xtp-code .kw  { color:#c084fc; font-weight:600; }
  pre.xtp-code .cm  { color:#475569; font-style:italic; }
  pre.xtp-code .val { color:#34d399; }
  pre.xtp-code .pin { color:#60a5fa; }
  pre.xtp-code .arrow { color:#f59e0b; }

  /* ── Bin2Bin table ── */
  .bin-wrap { padding:16px 20px; background:#0c0f1a; min-height:100%; }
  .bin-wrap table { border-collapse:collapse; font-family:"Cascadia Code","Fira Code","Consolas",monospace;
    font-size:.74rem; white-space:nowrap; }
  .bin-wrap th { background:#1e293b; color:#a78bfa; padding:6px 14px;
    border:1px solid #2d3748; text-align:center; font-weight:700; }
  .bin-wrap th:first-child { text-align:left; }
  .bin-wrap td { padding:5px 14px; border:1px solid #2d3748; text-align:center; color:#cbd5e1; }
  .bin-wrap td:first-child { text-align:left; color:#94a3b8; font-weight:600; }
  .bin-wrap tr:nth-child(even) td { background:#111827; }
  .bin-wrap strong { color:#e2e8f0; }
  .bin-wrap em { color:#94a3b8; font-style:italic; }
  .bin-wrap code { background:#1e293b; padding:1px 5px; border-radius:3px; color:#c084fc; }

  /* ── Generation log ── */
  #gen-log-wrap { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7);
    z-index:100; align-items:center; justify-content:center; }
  #gen-log-wrap.active { display:flex; }
  #gen-log-box { background:#0f1117; border:1px solid #334155; border-radius:10px;
    width:min(700px,94vw); max-height:80vh; display:flex; flex-direction:column;
    padding:20px; gap:12px; }
  #gen-log-box h2 { font-size:.9rem; color:#a78bfa; font-weight:700; }
  #gen-log-scroll { flex:1; overflow-y:auto; background:#0c0f1a; border-radius:6px;
    padding:12px 14px; font-family:"Cascadia Code","Consolas",monospace; font-size:.72rem;
    color:#94a3b8; line-height:1.6; max-height:55vh; }
  .log-line { margin:0; }
  .log-done { color:#34d399; }
  .log-err  { color:#f87171; }

  .spinner { width:14px; height:14px; border:2px solid #334155;
    border-top-color:#7c3aed; border-radius:50%; animation:spin .6s linear infinite;
    display:inline-block; vertical-align:middle; margin-right:6px; }
  @keyframes spin { to { transform:rotate(360deg); } }

  .empty-state { display:flex; flex-direction:column; align-items:center;
    justify-content:center; gap:10px; height:100%; color:#334155;
    font-size:.82rem; padding:40px; text-align:center; }
  .empty-icon { font-size:2.5rem; }
</style>
</head>
<body>

<header>
  <h1>⬡ XTP Analyser</h1>
  <span>ATE Test Program Dashboard</span>
</header>

<div class="toolbar">
  <button class="btn-primary" id="btn-generate" onclick="startGeneration()">
    ✦ Generate New Pair
  </button>
  <div class="sep"></div>

  <!-- Program A upload -->
  <div class="drop-zone" id="dz-a" onclick="document.getElementById('file-a').click()"
       ondragover="dzOver(event,'dz-a')" ondragleave="dzLeave('dz-a')" ondrop="dzDrop(event,'a')">
    <input type="file" id="file-a" accept=".xtp,.txt" onchange="uploadFile(this,'a')"/>
    <span class="dz-title">Program A</span>
    <span class="dz-label">Drop .xtp or click</span>
  </div>

  <!-- Program B upload -->
  <div class="drop-zone" id="dz-b" onclick="document.getElementById('file-b').click()"
       ondragover="dzOver(event,'dz-b')" ondragleave="dzLeave('dz-b')" ondrop="dzDrop(event,'b')">
    <input type="file" id="file-b" accept=".xtp,.txt" onchange="uploadFile(this,'b')"/>
    <span class="dz-title">Program B</span>
    <span class="dz-label">Drop .xtp or click</span>
  </div>

  <!-- Bin2Bin upload -->
  <div class="drop-zone" id="dz-bin" onclick="document.getElementById('file-bin').click()"
       ondragover="dzOver(event,'dz-bin')" ondragleave="dzLeave('dz-bin')" ondrop="dzDrop(event,'bin')">
    <input type="file" id="file-bin" accept=".csv,.txt" onchange="uploadFile(this,'bin')"/>
    <span class="dz-title">Bin2Bin</span>
    <span class="dz-label">Drop .csv or click</span>
  </div>

  <button class="btn-secondary" onclick="reloadAll()" style="margin-left:auto;">↺ Refresh</button>
</div>

<div class="layout">
  <!-- Top: Program A (left) + Program B (right) -->
  <div class="top-row">
    <div class="panel">
      <div class="panel-header">
        Program A
        <span class="badge" id="badge-a">—</span>
      </div>
      <div class="panel-body" id="body-a">
        <div class="empty-state"><span class="empty-icon">📄</span>No file loaded</div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header">
        Program B
        <span class="badge" id="badge-b">—</span>
      </div>
      <div class="panel-body" id="body-b">
        <div class="empty-state"><span class="empty-icon">📄</span>No file loaded</div>
      </div>
    </div>
  </div>

  <!-- Bottom: Bin2Bin matrix full width -->
  <div class="bottom-row panel">
    <div class="panel-header">
      Bin2Bin Matrix
      <span class="badge" id="badge-bin">—</span>
    </div>
    <div class="panel-body" id="body-bin">
      <div class="empty-state"><span class="empty-icon">📊</span>No matrix loaded</div>
    </div>
  </div>
</div>

<!-- Generation log modal -->
<div id="gen-log-wrap">
  <div id="gen-log-box">
    <h2><span class="spinner" id="gen-spinner"></span>Generating XTP pair + Bin2Bin…</h2>
    <div id="gen-log-scroll"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end;">
      <button class="btn-secondary" id="btn-close-log" onclick="closeLog()" disabled>Close</button>
    </div>
  </div>
</div>

<script>
// ── Syntax highlight for XTP code ──────────────────────────────────────────
function highlightXtp(src) {
  const esc = src.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  return esc
    .replace(/\/\/.*$/gm, m => `<span class="cm">${m}</span>`)
    .replace(/\b(PINMAP|LEVELS|TIMING|PARAMETRICS|FUNCTIONS|BINNING|PIN|TYPE|VECTOR)\b/g,
             m => `<span class="kw">${m}</span>`)
    .replace(/\b(POWER|GROUND|INPUT|OUTPUT|INOUT)\b/g,
             m => `<span class="pin">${m}</span>`)
    .replace(/(-&gt;|->)/g, m => `<span class="arrow">-></span>`)
    .replace(/\b(\d+\.?\d*(?:V|mA|uA|ns|MHz)?)\b/g,
             m => `<span class="val">${m}</span>`);
}

// ── CSV table renderer (bin slot) ───────────────────────────────────────────
function renderBinTable(csv) {
  const rows = csv.trim().split('\n').map(line => {
    // Basic CSV split: handles quoted fields with commas inside
    const cells = []; let cur = '', inQ = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') { inQ = !inQ; }
      else if (c === ',' && !inQ) { cells.push(cur.trim()); cur = ''; }
      else { cur += c; }
    }
    cells.push(cur.trim());
    return cells;
  });
  if (!rows.length) return '';

  const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const headHtml = '<tr>' + rows[0].map(c => `<th>${esc(c)}</th>`).join('') + '</tr>';
  const bodyHtml = rows.slice(1).map(r =>
    '<tr>' + r.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>'
  ).join('');

  return `<div class="bin-wrap"><table><thead>${headHtml}</thead><tbody>${bodyHtml}</tbody></table></div>`;
}

// ── Load file content from server ──────────────────────────────────────────
async function loadFile(slot) {
  const res = await fetch(`/api/file/${slot}`);
  const data = await res.json();
  if (data.content === null) return;
  renderSlot(slot, data.content, data.filename);
}

function renderSlot(slot, content, filename) {
  const body = document.getElementById(`body-${slot}`);
  const badge = document.getElementById(`badge-${slot}`);
  if (!body) return;
  if (slot === 'bin') {
    body.innerHTML = renderBinTable(content);
  } else {
    body.innerHTML = `<pre class="xtp-code">${highlightXtp(content)}</pre>`;
  }
  if (badge && filename) badge.textContent = filename;
}

function reloadAll() {
  loadFile('a'); loadFile('b'); loadFile('bin');
}

// ── Upload ──────────────────────────────────────────────────────────────────
async function uploadFile(input, slot) {
  if (!input.files.length) return;
  const fd = new FormData();
  fd.append('file', input.files[0]);
  fd.append('slot', slot);
  const res = await fetch('/api/upload', { method:'POST', body:fd });
  const data = await res.json();
  if (data.ok) renderSlot(slot, data.content, data.filename);
  else alert('Upload failed: ' + (data.error || 'unknown error'));
}

// ── Drag-and-drop helpers ───────────────────────────────────────────────────
function dzOver(e, id)  { e.preventDefault(); document.getElementById(id).classList.add('over'); }
function dzLeave(id)    { document.getElementById(id).classList.remove('over'); }
function dzDrop(e, slot){ e.preventDefault(); dzLeave(`dz-${slot}`);
  if (!e.dataTransfer.files.length) return;
  const fd = new FormData(); fd.append('file', e.dataTransfer.files[0]); fd.append('slot', slot);
  fetch('/api/upload', {method:'POST',body:fd}).then(r=>r.json()).then(d=>{
    if (d.ok) renderSlot(slot, d.content, d.filename);
  });
}

// ── Generation ─────────────────────────────────────────────────────────────
let _pollTimer = null;

function startGeneration() {
  document.getElementById('gen-log-wrap').classList.add('active');
  document.getElementById('gen-log-scroll').innerHTML = '';
  document.getElementById('btn-close-log').disabled = true;
  document.getElementById('btn-generate').disabled = true;
  document.getElementById('gen-spinner').style.display = 'inline-block';

  fetch('/api/generate', {method:'POST'})
    .then(r => r.json())
    .then(() => { _pollTimer = setInterval(pollLog, 800); });
}

function pollLog() {
  fetch('/api/gen_status').then(r=>r.json()).then(data => {
    const scroll = document.getElementById('gen-log-scroll');
    scroll.innerHTML = data.log.map(l =>
      `<p class="log-line ${l.startsWith('✓')||l.includes('SUCCESS')?'log-done':l.startsWith('✗')||l.includes('ERROR')?'log-err':''}">${escHtml(l)}</p>`
    ).join('');
    scroll.scrollTop = scroll.scrollHeight;

    if (data.done || data.error) {
      clearInterval(_pollTimer);
      document.getElementById('btn-close-log').disabled = false;
      document.getElementById('btn-generate').disabled = false;
      document.getElementById('gen-spinner').style.display = 'none';
      if (!data.error) reloadAll();
    }
  });
}

function closeLog() {
  document.getElementById('gen-log-wrap').classList.remove('active');
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Init ────────────────────────────────────────────────────────────────────
window.onload = () => reloadAll();
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template_string(_HTML)


@app.get("/api/file/<slot>")
def get_file(slot: str):
    path = _slot_path(slot)
    if path is None or not path.exists():
        return jsonify({"content": None, "filename": None})
    content = path.read_text(encoding="utf-8")
    return jsonify({"content": content, "filename": path.name})


@app.post("/api/upload")
def upload_file():
    slot = request.form.get("slot")
    f = request.files.get("file")
    if not f or not slot:
        return jsonify({"ok": False, "error": "missing file or slot"}), 400
    path = _slot_path(slot)
    if path is None:
        return jsonify({"ok": False, "error": "unknown slot"}), 400
    content = f.read().decode("utf-8", errors="replace")
    path.write_text(content, encoding="utf-8")
    return jsonify({"ok": True, "content": content, "filename": f.filename or path.name})


@app.post("/api/generate")
def generate():
    with _gen_lock:
        if _gen_state["running"]:
            return jsonify({"ok": False, "error": "already running"}), 409
        _gen_state.update({"running": True, "log": [], "done": False, "error": None})

    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()
    return jsonify({"ok": True})


@app.get("/api/gen_status")
def gen_status():
    with _gen_lock:
        return jsonify({
            "running": _gen_state["running"],
            "log": list(_gen_state["log"]),
            "done": _gen_state["done"],
            "error": _gen_state["error"],
        })


# ---------------------------------------------------------------------------
# Background generation pipeline
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    with _gen_lock:
        _gen_state["log"].append(msg)


def _run_pipeline() -> None:
    try:
        from XTPAnalyser.graph import XTPState, build_graph

        app = build_graph()
        initial_state: XTPState = {
            "output_folder": str(OUTPUT_FOLDER),
            "log": [],
        }

        # Each chunk from stream() is {"node_name": node_state_dict} in LangGraph 1.x.
        for chunk in app.stream(initial_state):
            for node_state in chunk.values():
                for line in node_state.get("log", []):
                    _log(line)
                if node_state.get("error"):
                    raise RuntimeError(node_state["error"])

        with _gen_lock:
            _gen_state["done"] = True
            _gen_state["running"] = False

    except Exception as exc:  # noqa: BLE001
        _log(f"✗ Pipeline error: {exc}")
        with _gen_lock:
            _gen_state["error"] = str(exc)
            _gen_state["done"] = True
            _gen_state["running"] = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slot_path(slot: str) -> Path | None:
    return {"a": _PROG_A, "b": _PROG_B, "bin": _BIN2BIN}.get(slot)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=False, port=5000, host="0.0.0.0")

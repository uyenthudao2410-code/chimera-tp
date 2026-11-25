"""24/7 CHIMERA-HYPER v3.0 Zero-Weight Mission-Control Daemon, Scheduler & Web Cockpit."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

from .active_pipe import (
    ActiveQueryServer,
    ComputePlan,
    remote_active_query,
)
from .autopilot import (
    VALID_PROFILES,
    OpsConfig,
    TelemetryStore,
    _build_incremental_sample,
    _http_get_json,
    _http_post_json,
    default_ops_dir,
    format_cluster_markdown_report,
    get_zero_weight_status,
    prepare_merkle_demo_workspace,
    run_daily_autopilot,
)
from .fabric import BeamServer, beam_send
from .hyper_wire import HedgedRpcServer, ImmortalMultiPathReceiver, ImmortalMultiPathSender
from .merkle_sync import (
    ShadowMerkleIndex,
    diff_manifests,
    merkle_beam_sync,
    sanitize_workspace_id,
)
from .native import cpu_caps
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
from .telepathy import DomainDictionary, TelepathicStore, train_domain_dictionary
from .warp import WarpServer

_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA-HYPER v3.0 Zero-Weight HyperGrid</title>
<style>
  :root {
    --bg: #0b0f17;
    --card: #121826;
    --card2: #182032;
    --border: rgba(148,163,184,0.18);
    --fg: #e2e8f0;
    --muted: #94a3b8;
    --cyan: #22d3ee;
    --green: #34d399;
    --amber: #fbbf24;
    --red: #f87171;
    --purple: #a78bfa;
    --mono: ui-monospace, "Cascadia Code", Consolas, monospace;
    --sans: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--fg); font-family: var(--sans); font-size: 13px; line-height: 1.45; padding: 18px; }
  .shell { max-width: 1280px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  .topbar {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;
    background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px;
  }
  .brand h1 { font-size: 17px; font-weight: 700; letter-spacing: 0.02em; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .badge { font-family: var(--mono); font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgba(34,211,238,0.14); color: var(--cyan); border: 1px solid rgba(34,211,238,0.3); }
  .badge.ok { background: rgba(52,211,153,0.14); color: var(--green); border-color: rgba(52,211,153,0.35); }
  .badge.warn { background: rgba(251,191,36,0.14); color: var(--amber); border-color: rgba(251,191,36,0.35); }
  .meta-line { color: var(--muted); font-size: 11.5px; font-family: var(--mono); margin-top: 4px; }

  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button, select, input {
    font-family: inherit; font-size: 12px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--card2); color: var(--fg); padding: 7px 12px; outline: none;
  }
  button { cursor: pointer; font-weight: 600; transition: 0.15s ease; }
  button:hover { border-color: var(--cyan); background: #1e293b; }
  button.primary { background: rgba(34,211,238,0.18); border-color: rgba(34,211,238,0.5); color: #67e8f9; }
  button:disabled { opacity: 0.5; cursor: wait; }

  .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  @media (max-width: 900px) { .grid-4, .grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 580px) { .grid-4, .grid-2 { grid-template-columns: 1fr; } }

  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 15px 17px; }
  .card-title { font-size: 12.5px; font-weight: 700; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .kpi-val { font-size: 24px; font-weight: 800; font-family: var(--mono); line-height: 1.15; }
  .kpi-sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  td.mono { font-family: var(--mono); }

  .query-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .query-bar input { flex: 1; min-width: 120px; font-family: var(--mono); }
  .log-box {
    background: #090d14; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
    font-family: var(--mono); font-size: 11px; max-height: 220px; overflow: auto; white-space: pre-wrap;
  }
  .cmp-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 12px; }
  .cmp-row:last-child { border-bottom: none; }
</style>
</head>
<body>
<div class="shell">
  <div class="topbar">
    <div class="brand">
      <h1>
        CHIMERA-HYPER v3.0 Zero-Weight
        <span class="badge" id="node-badge">...</span>
        <span class="badge ok" id="zw-badge">RAM -- MB</span>
        <span class="badge ok" id="sched-badge">DAILY ...</span>
      </h1>
      <div class="meta-line" id="hw-meta">Probing hardware &amp; zero-weight telemetry...</div>
    </div>
    <div class="controls">
      <select id="profile-select" title="Contextual Bandit Policy">
        <option value="auto-darwin">auto-darwin (24h Contextual UCB1)</option>
        <option value="max-speed">max-speed (Turbo Pipeline)</option>
        <option value="lossy-armor">lossy-armor (Proactive GFNI)</option>
        <option value="exotic-v05">exotic-v05 (Multi-Realm)</option>
      </select>
      <button class="primary" id="btn-run" onclick="triggerRun()">&#9654; Chạy đánh giá ngay</button>
      <button onclick="openMarkdownReport()">&#128196; Báo cáo (.md)</button>
      <button onclick="triggerMerkle()">&#127795; Merkle 0-RTT Sync</button>
      <button onclick="triggerImmortal()">&#128293; Immortal Cắt IPv4</button>
      <button onclick="triggerBeam()">&#9889; DNA Beam</button>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>Tailscale Cluster Hub — Sức Khỏe Toàn Cụm &amp; Đánh Giá Đồng Bộ (24/7 trên Hub)</span>
      <span class="badge ok" id="cluster-grade">HẠNG: ...</span>
    </div>
    <div class="kpi-sub" id="cluster-highlights" style="margin-bottom:10px;">Đang nạp báo cáo từ các node trong mạng Tailscale...</div>
    <div class="grid-2" id="cluster-nodes"></div>
  </div>

  <div class="grid-4">
    <div class="card">
      <div class="card-title">Sức Khỏe &amp; Zero-Weight</div>
      <div class="kpi-val" id="kpi-health" style="color:var(--green)">--</div>
      <div class="kpi-sub" id="kpi-health-sub">CHIMERA-HYPER v2.0 / v3.0 API</div>
    </div>
    <div class="card">
      <div class="card-title">Mạng WAN 5% Rớt Gói</div>
      <div class="kpi-val" id="kpi-wan" style="color:var(--cyan)">--</div>
      <div class="kpi-sub" id="kpi-wan-sub">RLNC GFNI/AVX2 vs TCP</div>
    </div>
    <div class="card">
      <div class="card-title">Telepathic + DNA Beam</div>
      <div class="kpi-val" id="kpi-beam" style="color:var(--purple)">--</div>
      <div class="kpi-sub" id="kpi-beam-sub">Giảm dây truyền tải thực tế</div>
    </div>
    <div class="card">
      <div class="card-title">Merkle Sync &amp; Link RTT</div>
      <div class="kpi-val" id="kpi-shm" style="color:var(--amber)">--</div>
      <div class="kpi-sub" id="kpi-shm-sub">0-RTT Hash &amp; Immortal Lanes</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        <span>Đối chiếu Trước vs Sau (Zero-Weight HyperGrid v3.0)</span>
        <span class="meta-line" id="latest-ts"></span>
      </div>
      <div id="compare-panel"><div class="meta-line">Nhấn "Chạy đánh giá ngay" để lấy số đo trực tiếp...</div></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Fluid Compute Pushdown &amp; Telepathic Wire (Chạy tại Peer)</span>
        <span class="meta-line" id="query-badge">AQ02 UDP 9704</span>
      </div>
      <div class="query-bar">
        <select id="q-op">
          <option value="log_analytics">log_analytics (Mẫu lỗi &amp; Theo giờ)</option>
          <option value="filter_lines">filter_lines (Lọc từ khóa + Telepathy)</option>
          <option value="multi_grep">multi_grep (Quét file / thư mục)</option>
          <option value="sqlite_query">sqlite_query (Read-Only DB Peer)</option>
          <option value="remote_digest">remote_digest (Hash nhanh trên Peer)</option>
        </select>
        <input id="q-needle" value="ERROR" placeholder="Từ khóa / SQL (SELECT ...)">
        <input id="q-file" value="" placeholder="File/Thư mục đích (mặc định log)">
        <button class="primary" onclick="triggerFluid()">&#128269; Chạy Fluid Pushdown</button>
      </div>
      <div class="log-box" id="query-out">Sẵn sàng chạy lệnh tính toán trực tiếp trên svhome mà không tốn RAM Windows.</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        <span>24h Link Weather &amp; Thời Điểm Đồng Bộ Tốt Nhất</span>
        <span class="meta-line" id="weather-rec">Đề xuất: ...</span>
      </div>
      <table>
        <thead><tr><th>Khung giờ</th><th>Mẫu</th><th>RTT p50</th><th>WAN</th><th>Genome Tốt</th></tr></thead>
        <tbody id="weather-tbody"></tbody>
      </table>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Contextual Darwinian Genome Leaderboard</span>
        <span class="meta-line" id="trend-count">0 runs</span>
      </div>
      <table>
        <thead><tr><th>Genome</th><th>Pulls</th><th>Avg Reward</th><th>Params</th></tr></thead>
        <tbody id="genome-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>Xu hướng &amp; Nhật ký Hoạt động Tự động</span>
      <span class="meta-line" id="services-meta"></span>
    </div>
    <svg id="trend-svg" viewBox="0 0 900 130" style="width:100%;height:130px;display:block;margin-bottom:8px;"></svg>
    <div class="log-box" id="events-box">Loading...</div>
  </div>
</div>

<script>
async function api(path, opts) {
  const res = await fetch(path, opts || {});
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function renderTrend(history) {
  const svg = document.getElementById('trend-svg');
  document.getElementById('trend-count').textContent = history.length + ' phiên';
  if (!history.length) {
    svg.innerHTML = '<text x="450" y="65" text-anchor="middle" fill="#64748b" font-size="12">Chưa có lịch sử chạy</text>';
    return;
  }
  const W = 900, H = 130, L = 36, R = 16, T = 14, B = 22;
  const pw = W - L - R, ph = H - T - B;
  let html = '';
  for (let g of [0, 50, 100]) {
    const y = T + ph - (g / 100) * ph;
    html += `<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="rgba(148,163,184,0.16)" stroke-dasharray="3 3"/>`;
    html += `<text x="${L-6}" y="${y+4}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="monospace">${g}</text>`;
  }
  const n = history.length;
  const maxWan = Math.max(25, ...history.map(h => h.wan_5pct_speedup || 0));
  const ptsH = [], ptsW = [];
  history.forEach((h, i) => {
    const x = n === 1 ? L + pw / 2 : L + (i / (n - 1)) * pw;
    const yh = T + ph - (Math.min(100, h.health_score) / 100) * ph;
    const yw = T + ph - (Math.min(maxWan, h.wan_5pct_speedup) / maxWan) * ph;
    ptsH.push(`${x.toFixed(1)},${yh.toFixed(1)}`);
    ptsW.push(`${x.toFixed(1)},${yw.toFixed(1)}`);
  });
  html += `<polyline fill="none" stroke="#34d399" stroke-width="2" points="${ptsH.join(' ')}"/>`;
  html += `<polyline fill="none" stroke="#22d3ee" stroke-width="1.8" stroke-dasharray="4 2" points="${ptsW.join(' ')}"/>`;
  html += `<text x="${L}" y="${H-5}" fill="#34d399" font-size="10">● Health</text>`;
  html += `<text x="${L+75}" y="${H-5}" fill="#22d3ee" font-size="10">--- WAN Speedup (max ${maxWan.toFixed(0)}x)</text>`;
  svg.innerHTML = html;
}

function renderState(st) {
  const cfg = st.config || {};
  const hw = st.hardware || {};
  const zw = st.zero_weight || {};
  document.getElementById('node-badge').textContent = `${cfg.node_name || 'node'} (${cfg.role || 'ctrl'})`;
  const zwEl = document.getElementById('zw-badge');
  zwEl.textContent = `RAM ${zw.daemon_ram_mb || 0}MB • Free ${zw.host_free_ram_gb || 0}GB`;
  zwEl.className = 'badge ' + (zw.zero_weight_ok !== false ? 'ok' : 'warn');
  document.getElementById('sched-badge').textContent = `DAILY ${cfg.daily_time || '08:00'} • ${st.today_daily_done ? 'ĐÃ CHẠY' : 'CHỜ LỊCH'}`;
  document.getElementById('hw-meta').textContent =
    `HW: native=${hw.native} gfni=${hw.gfni} avx2=${hw.avx2} | Peer: ${cfg.peer_name || '-'} (${cfg.peer_ipv4 || 'local'}) | Dicts: ${(st.telepathy_dicts||[]).length}`;
  document.getElementById('profile-select').value = cfg.active_profile || 'auto-darwin';
  document.getElementById('services-meta').textContent =
    `Beam=${cfg.beam_port} RPC=${cfg.rpc_v4_port}/${cfg.rpc_v6_port} Query=${cfg.query_port} Immortal=${cfg.immortal_v4_port}/${cfg.immortal_v6_port}`;
  if (!document.getElementById('q-file').value && cfg.watched_query_file) {
    document.getElementById('q-file').placeholder = cfg.watched_query_file;
  }

  const db = st.telemetry || {};
  const cl = st.cluster || {};
  const verdict = cl.evaluation_verdict || {};
  const clBadge = document.getElementById('cluster-grade');
  clBadge.textContent = `HẠNG: ${verdict.grade || '--'} • TB ${verdict.avg_health_score || 0}/100`;
  clBadge.className = 'badge ' + ((verdict.grade === 'A+' || verdict.grade === 'A') ? 'ok' : 'warn');
  document.getElementById('cluster-highlights').textContent =
    (verdict.highlights || []).join(' • ') || 'Chưa có báo cáo cross-host; bấm "Chạy đánh giá ngay" từ Windows để đẩy lên Hub.';

  const clNodes = cl.nodes || [];
  document.getElementById('cluster-nodes').innerHTML = clNodes.length ? clNodes.map(n => `
    <div style="background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:11px 13px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
        <strong class="mono">${n.node_name} <span class="badge">${n.role}</span></strong>
        <span class="badge ${n.health_score>=85?'ok':'warn'}">${n.health_score}/100</span>
      </div>
      <div class="meta-line">RAM: ${n.daemon_ram_mb} MB | WAN 5%: ${n.wan_5pct_speedup}x | GF(256): ${n.gfni_speedup}x | SHM: ${n.wormhole_gbps} Gbps</div>
      <div class="meta-line">${n.peer_reachable ? `Cross-Host Beam: ${n.beam_speedup}x | Query: -${n.query_saved_pct}% (${n.query_speedup}x) | Merkle: -${n.merkle_saved_pct}%` : 'Node Hub Server (nhận dữ liệu qua Tailscale)'} • ${n.ts_local}</div>
    </div>
  `).join('') : '<div class="meta-line">Chưa có node nào ghi vào cluster_reports.</div>';

  const latest = db.latest;
  const eff = (latest && latest.peer && latest.peer.reachable) ? latest : (cl.latest_cross_host || latest);
  if (eff) {
    document.getElementById('latest-ts').textContent = `${eff.ts_local} (${eff.node_name || ''} • ${eff.time_bucket || ''}) • ${eff.genome_id}`;
    const sc = eff.health_score;
    const hEl = document.getElementById('kpi-health');
    hEl.textContent = `${sc}/100`;
    hEl.style.color = sc >= 85 ? 'var(--green)' : 'var(--amber)';
    const lzw = eff.zero_weight || zw;
    document.getElementById('kpi-health-sub').textContent = `Daemon ${lzw.daemon_ram_mb} MB / ${lzw.host_threads} threads • Hub ${zw.daemon_ram_mb || 0} MB`;

    const loc = eff.local || {};
    document.getElementById('kpi-wan').textContent = `${loc.wan_5pct_speedup || 0}x`;
    document.getElementById('kpi-wan-sub').textContent = `GFNI/AVX2 ${loc.wan_5pct_chimera_mbps} vs TCP ${loc.wan_5pct_tcp_mbps} Mbps`;

    const pr = eff.peer || {};
    if (pr.reachable) {
      document.getElementById('kpi-beam').textContent = `-${pr.query_saved_pct}% dây`;
      document.getElementById('kpi-beam-sub').textContent = `Beam -${pr.beam_saved_pct}% (${pr.beam_speedup}x) • ${pr.query_codec_mode || 'zlib'}`;
      const mk = pr.merkle || {};
      document.getElementById('kpi-shm').textContent = `${pr.rtt_p50_ms} ms`;
      document.getElementById('kpi-shm-sub').textContent = mk.verified_root_match ? `Merkle -${mk.total_reduction_pct}% | SHM ${loc.wormhole_gbps}Gbps` : `SHM ${loc.wormhole_gbps} Gbps`;
    } else {
      document.getElementById('kpi-beam').textContent = `-${loc.telepathy_vs_raw_pct || 0}%`;
      document.getElementById('kpi-beam-sub').textContent = `Telepathy local (${loc.telepathy_vs_zlib_pct || 0}% < zlib)`;
      document.getElementById('kpi-shm').textContent = `${loc.wormhole_gbps} Gbps`;
      document.getElementById('kpi-shm-sub').textContent = `TCP loopback: ${loc.tcp_loopback_gbps} Gbps`;
    }

    let cmp = '';
    cmp += `<div class="cmp-row"><span>Lõi Silicon GF(256) (${eff.node_name})</span><span class="mono">Python ${loc.gfni_py_ms}ms &rarr; <b>Native ${loc.gfni_native_ms}ms (${loc.gfni_speedup}x)</b></span></div>`;
    cmp += `<div class="cmp-row"><span>Telepathic Local Dict</span><span class="mono">Zlib ${loc.telepathy_zlib_bytes}B &rarr; <b>CHTC1 ${loc.telepathy_wire_bytes}B (-${loc.telepathy_vs_raw_pct}%)</b></span></div>`;
    cmp += `<div class="cmp-row"><span>WAN 5% Drop</span><span class="mono">TCP ${loc.wan_5pct_tcp_mbps} Mbps &rarr; <b>RLNC ${loc.wan_5pct_chimera_mbps} Mbps (${loc.wan_5pct_speedup}x)</b></span></div>`;
    if (pr.reachable) {
      cmp += `<div class="cmp-row"><span>Live Telepathic Query (${pr.query_codec_mode})</span><span class="mono">TCP ${pr.query_tcp_ms}ms &rarr; <b>${pr.query_chimera_ms}ms (${pr.query_wire_bytes}B / -${pr.query_saved_pct}%)</b></span></div>`;
      if (pr.merkle && pr.merkle.verified_root_match) {
        cmp += `<div class="cmp-row"><span>Live Merkle 16-file Sync</span><span class="mono">${pr.merkle.total_bytes}B &rarr; <b>${pr.merkle.udp_wire_bytes}B (-${pr.merkle.total_reduction_pct}% / ${pr.merkle.elapsed_ms}ms)</b></span></div>`;
      }
      if (pr.immortal && pr.immortal.ok) {
        cmp += `<div class="cmp-row"><span>Immortal Cắt IPv4 Giữa Dòng</span><span class="mono">TX ${JSON.stringify(pr.immortal.lane_tx)} &rarr; <b>Sống 100% (0 reconnect, ${pr.immortal.elapsed_ms}ms)</b></span></div>`;
      }
    }
    document.getElementById('compare-panel').innerHTML = cmp;
  }

  renderTrend(db.history || []);
  document.getElementById('weather-rec').textContent = `Giờ sạch nhất: ${db.recommended_sync_window || 'NIGHT_CLEAN'} (Hiện tại: ${db.active_bucket || ''})`;
  document.getElementById('weather-tbody').innerHTML = (db.link_weather || []).map(w =>
    `<tr><td class="mono">${w.bucket}</td><td class="mono">${w.samples}</td><td class="mono">${w.ema_rtt_ms}ms</td><td class="mono">${w.ema_wan_speedup}x</td><td class="mono" style="color:var(--green)">${w.best_genome || '-'}</td></tr>`
  ).join('');

  document.getElementById('genome-tbody').innerHTML = (db.genomes || []).map(g => {
    const p = g.params || {};
    return `<tr><td class="mono">${g.genome_id}</td><td class="mono">${g.pulls}</td><td class="mono" style="color:var(--cyan)">${g.avg_reward.toFixed(2)}</td><td class="mono">k=${p.gen_k} loss=${p.loss_hint}</td></tr>`;
  }).join('');

  const evs = (db.events || []).map(e => `[${e.ts_local}] [${e.level}] [${e.category}] ${e.message}`).join('\n');
  document.getElementById('events-box').textContent = evs || 'No events recorded yet.';
}

async function refresh() {
  try { renderState(await api('/api/status')); } catch (e) { console.error(e); }
}

async function triggerRun() {
  const b = document.getElementById('btn-run');
  b.disabled = true; b.textContent = 'Đang chạy...';
  try { await api('/api/run?sync=1', { method: 'POST' }); await refresh(); }
  catch (e) { alert('Lỗi: ' + e.message); }
  finally { b.disabled = false; b.textContent = '▶ Chạy đánh giá ngay'; }
}

function openMarkdownReport() {
  window.open('/api/cluster/report?format=md', '_blank');
}

async function triggerBeam() {
  try {
    const res = await api('/api/live-beam', { method: 'POST' });
    alert(`DNA Beam: ${res.udp_wire_bytes}B / ${res.raw_bytes}B (-${res.reduction_pct}%) trong ${res.elapsed_ms}ms`);
    await refresh();
  } catch (e) { alert(e.message); }
}

async function triggerMerkle() {
  try {
    const res = await api('/api/live-merkle', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({}) });
    alert(`Merkle Sync: root=${res.remote_root_hash}\nChanged=${res.changed_files}/${res.total_files} files | UDP Wire=${res.udp_wire_bytes}B (-${res.total_reduction_pct}%)\n2nd 0-RTT Pass noop=${res.second_pass_noop} in ${res.second_pass_ms}ms`);
    await refresh();
  } catch (e) { alert(e.message); }
}

async function triggerImmortal() {
  try {
    const res = await api('/api/live-immortal', { method: 'POST' });
    alert(`Immortal Multi-Path Chaos Survival!\nSurvived Blackout: ${res.survived_blackout}\nLane TX: ${JSON.stringify(res.lane_tx_counts)}\nLane RX (Peer): ${JSON.stringify(res.lane_rx_counts)}\nReconnects: ${res.reconnects} | Time: ${res.elapsed_ms}ms`);
    await refresh();
  } catch (e) { alert(e.message); }
}

async function triggerFluid() {
  const op = document.getElementById('q-op').value;
  const val = document.getElementById('q-needle').value || '';
  const fpath = document.getElementById('q-file').value || '';
  const out = document.getElementById('query-out');
  out.textContent = 'Đang chạy Fluid Pushdown trực tiếp trên peer...';
  try {
    const body = { op, file_path: fpath, needle: val, patterns: [val], sql: val, use_telepathy: true };
    const res = await api('/api/live-fluid', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    });
    out.textContent =
      `[${res.op}] Codec=${res.codec_mode} | Raw=${res.raw_bytes}B -> Uncomp=${res.uncompressed_output_bytes}B -> Zlib=${res.plain_zlib_bytes}B -> Wire=${res.wire_bytes}B (-${res.wire_reduction_pct}%)\n` +
      `P0=${res.preview_first_ms}ms | Total=${res.total_ms}ms | ServerExec=${res.server_exec_ms}ms | Matched=${res.matched_records}\n--- Output Preview ---\n` +
      (res.output_preview_text || (res.preview_items || []).join('\n'));
    await refresh();
  } catch (e) { out.textContent = 'Lỗi: ' + e.message; }
}

document.getElementById('profile-select').addEventListener('change', async (ev) => {
  await api('/api/profile', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ active_profile: ev.target.value })
  });
  await refresh();
});

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""


class _ThreadingControlServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ChimeraDaemon:
    """24/7 Zero-Weight Mission-Control HTTP + UDP service host & daily self-scheduling daemon."""

    def __init__(
        self,
        config: OpsConfig | None = None,
        ops_dir: Path | None = None,
        auto_seed_on_empty: bool = False,
    ) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else default_ops_dir()
        self.config = config if config is not None else OpsConfig.load(self.ops_dir)
        self.store = TelemetryStore(self.ops_dir / "telemetry.db")
        self.telepathy_store = TelepathicStore(self.ops_dir / "dicts")
        self.merkle_root = self.ops_dir / "merkle_workspaces"
        self.merkle_root.mkdir(parents=True, exist_ok=True)
        self.auto_seed_on_empty = auto_seed_on_empty

        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._beam_srv: BeamServer | None = None
        self._rpc_srv: HedgedRpcServer | None = None
        self._query_srv: ActiveQueryServer | None = None
        self._immortal_rx: ImmortalMultiPathReceiver | None = None
        self._warp_srv: WarpServer | None = None
        self._httpd: _ThreadingControlServer | None = None
        self._threads: list[threading.Thread] = []
        self.http_addr: tuple[str, int] = ("127.0.0.1", 0)

    def _allowed_roots(self) -> list[Path]:
        roots = [Path(p) for p in self.config.allowed_query_roots]
        roots.append(self.ops_dir)
        if self.config.watched_query_file and self.config.watched_query_file != "@synthetic":
            roots.append(Path(self.config.watched_query_file).parent)
        return roots

    def start(self) -> "ChimeraDaemon":
        ephemeral_mode = int(self.config.beam_port) == 0 and int(self.config.query_port) == 0

        # 1) Start persistent BeamServer (supporting kind=3 Merkle patches)
        self._beam_srv = BeamServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.beam_port),
            vault_dir=self.ops_dir / "rx_vault",
            out_dir=self.ops_dir / "received_beam",
            merkle_root=self.merkle_root,
        ).start()
        self.config.beam_port = self._beam_srv.ctrl_addr[1]

        # 2) Start Dual-Stack HedgedRpcServer (IPv4 + optional IPv6)
        rpc_binds: list[tuple[str, int]] = [("0.0.0.0", int(self.config.rpc_v4_port))]
        if int(self.config.rpc_v6_port) >= 0:
            try:
                self._rpc_srv = HedgedRpcServer(
                    rpc_binds + [("::", int(self.config.rpc_v6_port))],
                    handler=lambda b: b"CHIMERA-PONG:" + b[:32],
                ).start()
            except OSError:
                self._rpc_srv = HedgedRpcServer(
                    rpc_binds, handler=lambda b: b"CHIMERA-PONG:" + b[:32]
                ).start()
        else:
            self._rpc_srv = HedgedRpcServer(
                rpc_binds, handler=lambda b: b"CHIMERA-PONG:" + b[:32]
            ).start()
        self.config.rpc_v4_port = self._rpc_srv.addrs[0][1]
        if len(self._rpc_srv.addrs) > 1:
            self.config.rpc_v6_port = self._rpc_srv.addrs[1][1]

        # 3) Start ActiveQueryServer (AQ01/AQ02 + Fluid Compute + Telepathy)
        self._query_srv = ActiveQueryServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.query_port),
            allowed_roots=self._allowed_roots(),
            telepathy_store=self.telepathy_store,
        ).start()
        self.config.query_port = self._query_srv.addr[1]

        # 4) Start ImmortalMultiPathReceiver (IPv4 + optional IPv6)
        imm_v4_p = 0 if ephemeral_mode else int(self.config.immortal_v4_port)
        imm_v6_p = 0 if ephemeral_mode else int(self.config.immortal_v6_port)
        if imm_v4_p >= 0:
            imm_binds = [("0.0.0.0", imm_v4_p)]
            if imm_v6_p >= 0:
                try:
                    self._immortal_rx = ImmortalMultiPathReceiver(
                        imm_binds + [("::", imm_v6_p)]
                    ).start()
                except OSError:
                    self._immortal_rx = ImmortalMultiPathReceiver(imm_binds).start()
            else:
                self._immortal_rx = ImmortalMultiPathReceiver(imm_binds).start()
            self.config.immortal_v4_port = self._immortal_rx.addrs[0][1]
            if len(self._immortal_rx.addrs) > 1:
                self.config.immortal_v6_port = self._immortal_rx.addrs[1][1]

            def _drain_immortal() -> None:
                while not self._stop.is_set() and self._immortal_rx is not None:
                    try:
                        self._immortal_rx.wait_any_stats(timeout_s=0.3)
                    except TimeoutError:
                        continue
                    except Exception:
                        break

            th_imm = threading.Thread(target=_drain_immortal, daemon=True)
            th_imm.start()
            self._threads.append(th_imm)

        # 5) Start HTTP Control Cockpit
        daemon_ref = self
        host_b, port_b = self.config.dashboard_bind.rsplit(":", 1)
        host_b = host_b.strip("[]") or "127.0.0.1"

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send_json(self, code: int, obj: Any) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> bytes:
                clen = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(clen) if clen > 0 else b""

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/":
                    page = _DASHBOARD_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "version": "3.0.0",
                            "node_name": daemon_ref.config.node_name,
                            "role": daemon_ref.config.role,
                            "hardware": cpu_caps(),
                            "zero_weight": get_zero_weight_status(),
                        },
                    )
                    return
                if parsed.path == "/api/status":
                    self._send_json(200, daemon_ref.status_payload())
                    return
                if parsed.path == "/api/cluster/report":
                    qs = urllib.parse.parse_qs(parsed.query)
                    fmt = qs.get("format", ["json"])[0]
                    st_payload = daemon_ref.status_payload()
                    if fmt == "md":
                        md_bytes = format_cluster_markdown_report(st_payload).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/markdown; charset=utf-8")
                        self.send_header("Content-Disposition", 'inline; filename="chimera_eval_report.md"')
                        self.send_header("Content-Length", str(len(md_bytes)))
                        self.end_headers()
                        self.wfile.write(md_bytes)
                        return
                    self._send_json(
                        200,
                        {
                            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "version": "3.0.0",
                            "cluster": st_payload.get("cluster", {}),
                            "status": st_payload,
                        },
                    )
                    return
                if parsed.path == "/api/immortal/result":
                    qs = urllib.parse.parse_qs(parsed.query)
                    sid = int(qs.get("stream_id", ["0"])[0])
                    st = (
                        daemon_ref._immortal_rx.get_recent_stats(sid)
                        if daemon_ref._immortal_rx is not None
                        else None
                    )
                    self._send_json(200, {"found": st is not None, **(st or {})})
                    return
                if parsed.path == "/api/raw_query_file":
                    qs = urllib.parse.parse_qs(parsed.query)
                    req_path = qs.get("path", [daemon_ref.config.watched_query_file])[0] or "@synthetic"
                    try:
                        raw = daemon_ref._query_srv._load_target_bytes(req_path)  # type: ignore[union-attr]
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self._send_json(404, {"error": "Not found"})

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/api/tcp_sink":
                    t0 = time.perf_counter()
                    clen = int(self.headers.get("Content-Length", "0"))
                    rem = clen
                    hasher = hashlib.sha256()
                    while rem > 0:
                        chunk = self.rfile.read(min(65536, rem))
                        if not chunk:
                            break
                        hasher.update(chunk)
                        rem -= len(chunk)
                    ms = (time.perf_counter() - t0) * 1000.0
                    self._send_json(
                        200,
                        {"bytes": clen - rem, "sha256": hasher.hexdigest(), "server_ms": round(ms, 2)},
                    )
                    return

                if parsed.path == "/api/run":
                    sync = "sync=1" in parsed.query
                    if sync:
                        rep = daemon_ref.run_cycle(trigger="manual_dashboard")
                        self._send_json(200, rep)
                    else:
                        threading.Thread(
                            target=daemon_ref.run_cycle,
                            kwargs={"trigger": "manual_dashboard"},
                            daemon=True,
                        ).start()
                        self._send_json(202, {"queued": True})
                    return

                if parsed.path == "/api/cluster/ingest":
                    try:
                        body = json.loads(self._read_body().decode("utf-8"))
                        if not body.get("node_name") or not body.get("ts_local"):
                            self._send_json(400, {"error": "Missing node_name or ts_local"})
                            return
                        rid = daemon_ref.store.record_cluster_report(body)
                        daemon_ref.store.log_event(
                            "INFO",
                            "CLUSTER",
                            f"Ingested report #{rid} from {body.get('node_name')} score={body.get('health_score')}",
                        )
                        self._send_json(200, {"ok": True, "report_id": rid})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/profile":
                    try:
                        body = json.loads(self._read_body().decode("utf-8"))
                        prof = str(body.get("active_profile", ""))
                        if prof not in VALID_PROFILES:
                            self._send_json(400, {"error": f"Invalid profile: {prof}"})
                            return
                        daemon_ref.config.active_profile = prof
                        daemon_ref.config.save(daemon_ref.ops_dir)
                        daemon_ref.store.log_event("INFO", "CONFIG", f"Switched profile -> {prof}")
                        self._send_json(200, {"active_profile": prof})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/merkle/diff":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        ws_id = sanitize_workspace_id(str(body.get("workspace_id", "default")))
                        ws_dir = daemon_ref.merkle_root / ws_id
                        snap = ShadowMerkleIndex().scan(ws_dir)
                        diff = diff_manifests(
                            local_files=body.get("files", {}),
                            local_root=str(body.get("root_hash", "")),
                            remote_files=snap.files,
                            remote_root=snap.root_hash,
                        )
                        diff["remote_root_hash"] = snap.root_hash
                        diff["workspace_id"] = ws_id
                        self._send_json(200, diff)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/telepathy/train":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        fpath = str(body.get("file_path") or daemon_ref.config.watched_query_file or "@synthetic")
                        domain = str(body.get("domain", "default"))
                        raw = daemon_ref._query_srv._load_target_bytes(fpath)  # type: ignore[union-attr]
                        d = train_domain_dictionary([raw[: 512 * 1024]], domain=domain)
                        daemon_ref.telepathy_store.put(d)
                        daemon_ref.store.log_event(
                            "INFO", "TELEPATHY", f"Trained dict={d.dict_id} ({len(d.zdict)}B) for {domain}"
                        )
                        self._send_json(200, d.to_wire_dict())
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-merkle":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        ws_id = sanitize_workspace_id(str(body.get("workspace_id", "autopilot_demo")))
                        local_dir_arg = str(body.get("local_dir", ""))
                        if local_dir_arg:
                            target_dir = Path(local_dir_arg).resolve()
                        else:
                            target_dir = prepare_merkle_demo_workspace(daemon_ref.ops_dir)
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_bport = (
                            daemon_ref.config.peer_beam_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.beam_port
                        )
                        peer_http = (
                            f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                            if daemon_ref.config.peer_ipv4
                            else f"http://127.0.0.1:{daemon_ref.http_addr[1]}"
                        )
                        rep1 = merkle_beam_sync(
                            peer_http_base=peer_http,
                            peer_beam_addr=(peer_ip, peer_bport),
                            local_dir=target_dir,
                            workspace_id=ws_id,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            shadow_dir=daemon_ref.ops_dir / "merkle_shadows",
                            est_loss=0.02,
                        )
                        rep2 = merkle_beam_sync(
                            peer_http_base=peer_http,
                            peer_beam_addr=(peer_ip, peer_bport),
                            local_dir=target_dir,
                            workspace_id=ws_id,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            shadow_dir=daemon_ref.ops_dir / "merkle_shadows",
                            est_loss=0.02,
                        )
                        rep1["second_pass_noop"] = rep2["noop"]
                        rep1["second_pass_ms"] = rep2["elapsed_ms"]
                        daemon_ref.store.log_event(
                            "INFO",
                            "MERKLE",
                            f"Sync ws={ws_id} changed={rep1['changed_files']}/{rep1['total_files']} wire={rep1['udp_wire_bytes']}B 2nd_noop={rep2['noop']}({rep2['elapsed_ms']}ms)",
                        )
                        self._send_json(200, rep1)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-fluid":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        op = str(body.get("op", "log_analytics"))
                        fpath = str(
                            body.get("file_path")
                            or daemon_ref.config.watched_query_file
                            or "@synthetic"
                        )
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_qport = (
                            daemon_ref.config.peer_query_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.query_port
                        )
                        peer_http = (
                            f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                            if daemon_ref.config.peer_ipv4
                            else f"http://127.0.0.1:{daemon_ref.http_addr[1]}"
                        )
                        dd: DomainDictionary | None = daemon_ref.telepathy_store.latest_for_domain("watched_log")
                        if dd is None and bool(body.get("use_telepathy", True)) and op in ("filter_lines", "multi_grep", "log_analytics"):
                            try:
                                tr = _http_post_json(
                                    f"{peer_http}/api/telepathy/train",
                                    {"file_path": fpath, "domain": "watched_log"},
                                    timeout_s=8.0,
                                )
                                if tr.get("zdict_b64"):
                                    dd = DomainDictionary.from_wire_dict(tr)
                                    daemon_ref.telepathy_store.put(dd)
                            except Exception:
                                pass

                        plan = ComputePlan(
                            op=op,  # type: ignore[arg-type]
                            needle=str(body.get("needle", "ERROR")),
                            patterns=tuple(body.get("patterns", [])),
                            match_mode="all" if body.get("match_mode") == "all" else "any",
                            regex=bool(body.get("regex", False)),
                            ignore_case=bool(body.get("ignore_case", False)),
                            file_glob=str(body.get("file_glob", "*")),
                            sql=str(body.get("sql", "")),
                            max_rows=int(body.get("max_rows", 200)),
                            use_telepathy=bool(body.get("use_telepathy", True)),
                            dict_id=dd.dict_id if dd else "",
                        )
                        res, meta = remote_active_query(
                            (peer_ip, peer_qport),
                            file_path=fpath,
                            plan=plan,
                            est_loss=0.02,
                            timeout_s=15.0,
                            telepathy_store=daemon_ref.telepathy_store,
                            domain_dict=dd,
                        )
                        out = res.to_dict()
                        out.update(meta)
                        txt = res.output_bytes.decode("utf-8", errors="replace")
                        out["output_preview_text"] = txt[:1600]
                        daemon_ref.store.log_event(
                            "INFO",
                            "FLUID",
                            f"op={op} codec={meta.get('codec_mode')} wire={res.wire_bytes}B (-{res.wire_reduction_pct}%) {res.total_ms}ms",
                        )
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-immortal":
                    try:
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        if daemon_ref.config.peer_ipv4:
                            targets = [(peer_ip, daemon_ref.config.peer_immortal_v4_port)]
                            if daemon_ref.config.peer_ipv6 and daemon_ref.config.peer_immortal_v6_port > 0:
                                targets.append((daemon_ref.config.peer_ipv6, daemon_ref.config.peer_immortal_v6_port))
                            peer_http = f"http://{peer_ip}:{daemon_ref.config.peer_dashboard_port}"
                        else:
                            targets = [
                                ("127.0.0.1", daemon_ref.config.immortal_v4_port),
                                (
                                    "::1" if daemon_ref._immortal_rx and len(daemon_ref._immortal_rx.addrs) > 1 else "127.0.0.1",
                                    daemon_ref.config.immortal_v6_port
                                    if (daemon_ref._immortal_rx and len(daemon_ref._immortal_rx.addrs) > 1)
                                    else daemon_ref.config.immortal_v4_port,
                                ),
                            ]
                            peer_http = f"http://127.0.0.1:{daemon_ref.http_addr[1]}"

                        sid = (int(time.time()) % 200) + 20
                        payload = os.urandom(128 * 1024)
                        irep = ImmortalMultiPathSender(
                            targets, gen_k=32, initial_loss_hint=0.03
                        ).send_stream(
                            payload,
                            stream_id=sid,
                            timeout_s=12.0,
                            chaos_kill_lane=0 if len(targets) >= 2 else None,
                            chaos_kill_after_gens=1,
                        )
                        rx_check: dict[str, Any] = {}
                        for _ in range(5):
                            try:
                                rx_check = _http_get_json(
                                    f"{peer_http}/api/immortal/result?stream_id={sid}", timeout_s=2.0
                                )
                                if rx_check.get("found"):
                                    break
                            except Exception:
                                pass
                            time.sleep(0.05)
                        out = irep.to_dict()
                        out["lane_rx_counts"] = rx_check.get("lane_rx_counts", [])
                        out["peer_sha256_match"] = rx_check.get("sha256") == irep.sha256
                        daemon_ref.store.log_event(
                            "INFO",
                            "IMMORTAL",
                            f"lanes={irep.lanes_total} killed={irep.lanes_killed} tx={irep.lane_tx_counts} rx={out['lane_rx_counts']} ok={out['peer_sha256_match']}",
                        )
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-beam":
                    try:
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_port = (
                            daemon_ref.config.peer_beam_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.beam_port
                        )
                        work = daemon_ref.ops_dir / "beam_work"
                        work.mkdir(parents=True, exist_ok=True)
                        bfile = work / "live_button_1mb.bin"
                        data = _build_incremental_sample(1024 * 1024, int(time.time()) % 10000)
                        bfile.write_bytes(data)
                        rep = beam_send(
                            (peer_ip, peer_port),
                            bfile,
                            vault_dir=daemon_ref.ops_dir / "tx_vault",
                            est_loss=0.02,
                            timeout_s=20.0,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "LIVE_BEAM",
                            f"Synced {rep.raw_bytes}B in {rep.elapsed_ms}ms (saved {rep.reduction_pct}%)",
                        )
                        self._send_json(200, rep.to_dict())
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/live-query":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        needle = str(body.get("needle", "ERROR"))
                        fpath = str(
                            body.get("file_path")
                            or daemon_ref.config.watched_query_file
                            or "@synthetic"
                        )
                        peer_ip = daemon_ref.config.peer_ipv4 or "127.0.0.1"
                        peer_qport = (
                            daemon_ref.config.peer_query_port
                            if daemon_ref.config.peer_ipv4
                            else daemon_ref.config.query_port
                        )
                        dd = daemon_ref.telepathy_store.latest_for_domain("watched_log")
                        res, meta = remote_active_query(
                            (peer_ip, peer_qport),
                            file_path=fpath,
                            plan=ComputePlan(
                                op="filter_lines",
                                needle=needle,
                                use_telepathy=True,
                                dict_id=dd.dict_id if dd else "",
                            ),
                            est_loss=0.02,
                            timeout_s=15.0,
                            telepathy_store=daemon_ref.telepathy_store,
                            domain_dict=dd,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "LIVE_QUERY",
                            f"needle={needle!r} matched={res.matched_records} wire_saved={res.wire_reduction_pct}% in {res.total_ms}ms",
                        )
                        out = res.to_dict()
                        out.update(meta)
                        self._send_json(200, out)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/exotic-audit":
                    try:
                        env = probe_environment()
                        if os.name == "nt":
                            rx = ChimeraReceiver(env, droplet_size=20)
                            offer = rx.start()
                            try:
                                tx = ChimeraSender(env, offer)
                                sample = b"CHIMERA-EXOTIC-AUDIT-" + os.urandom(64)
                                rec, rep = tx.send_metamorphic(
                                    rx, sample, FaultProfile(packet_drop_rate=0.2), timeout_s=8.0
                                )
                                res_obj = {
                                    "os": "windows",
                                    "active_realms": env.active_droplet_lanes(),
                                    "sha256_match": rec == sample and rep.sha256_match,
                                    "elapsed_ms": rep.elapsed_ms,
                                }
                            finally:
                                rx.close()
                        else:
                            res_obj = {
                                "os": "linux",
                                "active_realms": list(env.realms.keys()),
                                "note": "8-lane Windows quirks are Windows-specific; Linux runs C AVX2 HyperWire/DNA/Wormhole.",
                            }
                        daemon_ref.store.log_event("INFO", "EXOTIC", json.dumps(res_obj))
                        self._send_json(200, res_obj)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                self._send_json(404, {"error": "Not found"})

            def log_message(self, *_args: object) -> None:
                pass

        self._httpd = _ThreadingControlServer((host_b, int(port_b)), Handler)
        self.http_addr = self._httpd.server_address[:2]

        if int(self.config.warp_port) >= 0:
            self._warp_srv = WarpServer(
                udp_bind=("0.0.0.0", int(self.config.warp_port)),
                forward_tcp_addr=("127.0.0.1", self.http_addr[1]),
                est_loss=0.02,
            ).start()
            self.config.warp_port = self._warp_srv.udp_addr[1]

        t_http = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t_sched = threading.Thread(target=self._scheduler_loop, daemon=True)
        t_http.start()
        t_sched.start()
        self._threads.extend([t_http, t_sched])
        zw = get_zero_weight_status()
        self.store.log_event(
            "INFO",
            "DAEMON",
            f"v3.0 Started on http://{self.http_addr[0]}:{self.http_addr[1]} | RAM={zw['daemon_ram_mb']}MB | Beam={self.config.beam_port} Query={self.config.query_port} Immortal={self.config.immortal_v4_port}/{self.config.immortal_v6_port}",
        )
        return self

    def status_payload(self) -> dict[str, Any]:
        return {
            "version": "3.0.0",
            "config": self.config.to_dict(),
            "hardware": cpu_caps(),
            "zero_weight": get_zero_weight_status(),
            "telepathy_dicts": self.telepathy_store.list_dicts(),
            "today_daily_done": self.store.has_daily_run_today(),
            "telemetry": self.store.get_dashboard_state(limit=30),
            "cluster": self.store.get_cluster_overview(limit=30),
        }

    def run_cycle(self, trigger: str = "manual") -> dict[str, Any]:
        with self._run_lock:
            return run_daily_autopilot(
                self.config, self.store, trigger=trigger, ops_dir=self.ops_dir
            )

    def _scheduler_loop(self) -> None:
        if self.auto_seed_on_empty:
            st = self.store.get_dashboard_state(limit=1)
            if st["total_runs"] == 0 and not self._stop.wait(timeout=1.5):
                try:
                    self.run_cycle(trigger="startup_seed")
                except Exception:
                    pass

        while not self._stop.wait(timeout=30.0):
            try:
                now_hm = datetime.now().astimezone().strftime("%H:%M")
                if now_hm >= self.config.daily_time and not self.store.has_daily_run_today():
                    self.run_cycle(trigger="daemon_daily")
            except Exception as exc:
                self.store.log_event("ERROR", "SCHEDULER", str(exc))

    def close(self) -> None:
        self._stop.set()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        for srv in (
            self._warp_srv,
            self._immortal_rx,
            self._query_srv,
            self._rpc_srv,
            self._beam_srv,
        ):
            if srv is not None:
                srv.close()
        self.store.close()

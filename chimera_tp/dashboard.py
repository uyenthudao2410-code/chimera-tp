"""24/7 CHIMERA-HYPER v4.0 Zero-Weight HyperOS Daemon, Scheduler & Web Cockpit."""

from __future__ import annotations

import base64
import gzip
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
from .code_search import CodeSearchIndex
from .edge_proxy import EdgeGateway, LocalEdgeProxy, edge_fetch_remote
from .fabric import BeamServer, beam_send
from .holo_backup import (
    create_holo_backup,
    list_holo_backups,
    restore_holo_backup,
    sanitize_backup_id,
    store_received_shard,
)
from .hyper_wire import HedgedRpcServer, ImmortalMultiPathReceiver, ImmortalMultiPathSender
from .merkle_sync import (
    ShadowMerkleIndex,
    diff_manifests,
    merkle_beam_sync,
    sanitize_workspace_id,
)
from .nat_buster import NatPunchResponder, attempt_direct_punch, discover_nat_profile
from .native import cpu_caps
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
from .sentinel import SentinelEngine
from .telepathy import DomainDictionary, TelepathicStore, train_domain_dictionary
from .warp import WarpServer

_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA-HYPER v4.0 Zero-Weight HyperOS</title>
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
        CHIMERA-HYPER v4.0 Zero-Weight HyperOS
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
      <button onclick="forceRefresh()">&#8635; Làm mới</button>
      <button onclick="triggerNatBust()">&#128640; NAT Buster</button>
      <button onclick="triggerEdgeTest()">&#9889; Edge Warp</button>
      <button onclick="triggerHoloBackup()">&#128272; Holo GF256</button>
      <button onclick="triggerMerkle()">&#127795; Merkle Sync</button>
      <button onclick="triggerImmortal()">&#128293; Immortal</button>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>Tailscale Cluster Hub — Sức Khỏe Toàn Cụm &amp; HyperOS Action Console</span>
      <span class="badge ok" id="cluster-grade">HẠNG: ...</span>
    </div>
    <div class="kpi-sub" id="cluster-highlights" style="margin-bottom:10px;">Đang nạp báo cáo từ các node trong mạng Tailscale...</div>
    <div class="grid-2" id="cluster-nodes"></div>
    <div class="log-box" id="v4-console" style="margin-top:10px;max-height:130px;display:none;"></div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        <span>0-Download Instant Search (SQLite FTS5 + Merkle)</span>
        <span class="meta-line" id="search-meta">0 files</span>
      </div>
      <div class="query-bar">
        <input id="search-q" value="ERROR" placeholder="Tìm trong toàn bộ code &amp; log (vd: HyperWire, V_Finance)...">
        <input id="search-repo" value="" placeholder="Repo (tùy chọn)" style="max-width:140px;">
        <button class="primary" onclick="triggerSearch()">&#128269; Tìm</button>
        <button onclick="triggerReindex()">&#128260; Reindex</button>
      </div>
      <div class="log-box" id="search-out">Nhập từ khóa để tìm BM25 trên svhome mà không tốn RAM Windows.</div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>CHIMERA-SENTINEL — Watchdog Tự Hành &amp; Dịch Vụ</span>
        <span class="badge ok" id="sentinel-badge">...</span>
      </div>
      <div class="controls" style="justify-content:space-between;margin-bottom:8px;">
        <div class="meta-line" id="sentinel-res">Đang chờ quét dịch vụ, đĩa &amp; log...</div>
        <button onclick="triggerSentinel()">&#128737; Quét Sentinel</button>
      </div>
      <div id="sentinel-svcs" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;"></div>
      <div class="log-box" id="sentinel-out" style="max-height:150px;">Chưa có cảnh báo.</div>
    </div>
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
window.__INIT_STATE__ = /*__INIT_STATE__*/null;
let _lastEtag = /*__INIT_ETAG__*/"";

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

  const cs = st.code_search || {};
  document.getElementById('search-meta').textContent =
    `${cs.indexed_files || 0} files / ${cs.repos_count || 0} repos (${cs.db_size_kb || 0} KB)`;

  const sent = st.sentinel || {};
  const sb = document.getElementById('sentinel-badge');
  const sStat = sent.status || 'PENDING';
  sb.textContent = `SENTINEL: ${sStat}`;
  sb.className = 'badge ' + (sStat === 'OK' ? 'ok' : 'warn');
  const sRes = sent.resources || {};
  document.getElementById('sentinel-res').textContent =
    sRes.disk_free_gb !== undefined
      ? `Disk trống: ${sRes.disk_free_gb}/${sRes.disk_total_gb}GB (${sRes.disk_free_pct}%) | Scan: ${sent.ts_local || '-'}`
      : 'Bấm "Quét Sentinel" để kiểm tra toàn hệ thống.';
  document.getElementById('sentinel-svcs').innerHTML = (sent.services || []).map(s =>
    `<span class="badge ${s.up ? 'ok' : 'warn'}">${s.app_id}: ${s.up ? 'UP ' + s.latency_ms + 'ms' : 'DOWN'}</span>`
  ).join('');
  const sAlerts = sent.alerts || sent.recent_alerts || [];
  document.getElementById('sentinel-out').textContent = sAlerts.length
    ? sAlerts.slice(0, 6).map(a => `[${a.severity}] ${a.title}\n  ${a.detail}\n  Gợi ý: ${a.diagnosis}`).join('\n---\n')
    : 'Hệ thống khỏe mạnh — chưa ghi nhận cảnh báo bất thường.';
}

function logV4(msg) {
  const el = document.getElementById('v4-console');
  el.style.display = 'block';
  el.textContent = msg;
}

async function triggerSearch() {
  const q = document.getElementById('search-q').value || '';
  const repo = document.getElementById('search-repo').value || '';
  const out = document.getElementById('search-out');
  out.textContent = 'Đang tìm BM25 FTS5...';
  try {
    const r = await api('/api/search', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ query: q, repo, limit: 10 })
    });
    document.getElementById('search-meta').textContent = `${r.indexed_files} files • ${r.elapsed_ms}ms`;
    out.textContent = r.hits && r.hits.length
      ? `Tìm thấy ${r.total_hits} kết quả (${r.elapsed_ms}ms):\n` +
        r.hits.map(h => `[${h.repo}] ${h.rel_path} (score=${h.score})\n  ${h.snippet}`).join('\n')
      : `Không có kết quả cho "${q}" (${r.elapsed_ms}ms).`;
  } catch (e) { out.textContent = 'Lỗi: ' + e.message; }
}

async function triggerReindex() {
  const out = document.getElementById('search-out');
  out.textContent = 'Đang cập nhật Merkle FTS5 index...';
  try {
    const r = await api('/api/search/reindex', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    out.textContent = `Reindex OK: ${r.total_files} files | updated=${r.updated} skipped=${r.skipped_unchanged} removed=${r.removed} DB=${r.db_size_kb}KB trong ${r.elapsed_ms}ms`;
    await forceRefresh();
  } catch (e) { out.textContent = 'Lỗi: ' + e.message; }
}

async function triggerSentinel() {
  try {
    const r = await api('/api/sentinel/scan', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    logV4(`Sentinel [${r.status}] trong ${r.elapsed_ms}ms | Cảnh báo=${r.alert_count} | Dịch vụ=${(r.services||[]).length}`);
    await forceRefresh();
  } catch (e) { logV4('Sentinel lỗi: ' + e.message); }
}

async function triggerNatBust() {
  logV4('Đang chạy STUN + Birthday-Paradox NAT Buster...');
  try {
    const r = await api('/api/nat/bust', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    logV4(`NAT Buster: punched=${r.punched} mode=${r.fallback_mode} | LocalNAT=${(r.local_nat||{}).nat_type} | TailscaleRTT=${r.tailscale_rtt_ms}ms | DirectRTT=${r.direct_rtt_p50_ms}ms | ${r.diagnosis}`);
    await forceRefresh();
  } catch (e) { logV4('NAT Buster lỗi: ' + e.message); }
}

async function triggerEdgeTest() {
  logV4('Đang test Universal Warp-Edge Gateway + Speculative Prefetch...');
  try {
    const r = await api('/api/edge/fetch', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ app_id: 'chimera', path: '/', allow_prefetch: true })
    });
    logV4(`Edge Gateway [${r.app_id}]: raw=${r.raw_bytes}B -> wire=${r.wire_bytes}B (-${r.saved_vs_raw_pct}%, ${r.mode_name}) | Prefetched=${Object.keys(r.prefetched||{}).length} endpoints trong ${r.server_exec_ms}ms`);
    await forceRefresh();
  } catch (e) { logV4('Edge lỗi: ' + e.message); }
}

async function triggerHoloBackup() {
  logV4('Đang tạo Holographic GF(256) (K=2, N=3) Backup...');
  try {
    const r = await api('/api/backup/create', { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
    logV4(`Holo Backup [${r.backup_id}]: files=${(r.files||[]).length} raw=${r.raw_bytes}B -> shard=${r.shard_bytes}B | Entropy=[${(r.entropies||[]).join(', ')}] | PeerSynced=${r.peer_synced} | SHA=${(r.orig_sha256||'').slice(0,16)}... (${r.elapsed_ms}ms)`);
    await forceRefresh();
  } catch (e) { logV4('Holo Backup lỗi: ' + e.message); }
}

async function refresh() {
  if (document.hidden) return;
  try {
    const headers = _lastEtag ? { 'If-None-Match': _lastEtag } : {};
    const res = await fetch('/api/status', { headers });
    if (res.status === 304) return;
    if (!res.ok) throw new Error(await res.text());
    const et = res.headers.get('ETag');
    if (et) _lastEtag = et;
    renderState(await res.json());
  } catch (e) { console.error(e); }
}

async function forceRefresh() {
  _lastEtag = '';
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

if (window.__INIT_STATE__) {
  renderState(window.__INIT_STATE__);
} else {
  refresh();
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refresh();
});
setInterval(() => { if (!document.hidden) refresh(); }, 30000);
</script>
</body>
</html>
"""


class _ThreadingControlServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64


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
        self.backup_root = self.ops_dir / "holo_backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        self.auto_seed_on_empty = auto_seed_on_empty

        self.nat_responder = NatPunchResponder()
        self.edge_gateway = EdgeGateway(
            targets=self.config.edge_targets, telepathy_store=self.telepathy_store
        )
        self.sentinel = SentinelEngine(ops_dir=self.ops_dir)
        self.code_search = CodeSearchIndex(self.ops_dir / "code_index.db")

        self._run_lock = threading.Lock()
        self._ephemeral_mode = int(self.config.beam_port) == 0 and int(self.config.query_port) == 0
        self._status_cache_lock = threading.Lock()
        self._status_cache_ts: float = 0.0
        self._status_cache_data: tuple[dict[str, Any], bytes, str] | None = None
        self._last_nat_result: dict[str, Any] | None = None
        self._stop = threading.Event()
        self._beam_srv: BeamServer | None = None
        self._rpc_srv: HedgedRpcServer | None = None
        self._query_srv: ActiveQueryServer | None = None
        self._immortal_rx: ImmortalMultiPathReceiver | None = None
        self._warp_srv: WarpServer | None = None
        self._local_edge_proxy: LocalEdgeProxy | None = None
        self._httpd: _ThreadingControlServer | None = None
        self._threads: list[threading.Thread] = []
        self.http_addr: tuple[str, int] = ("127.0.0.1", 0)

    def _allowed_roots(self) -> list[Path]:
        roots = [Path(p).resolve() for p in self.config.allowed_query_roots]
        roots.append(self.ops_dir.resolve())
        if self.config.watched_query_file and self.config.watched_query_file != "@synthetic":
            roots.append(Path(self.config.watched_query_file).resolve().parent)
        for p in self.config.search_roots:
            roots.append(Path(p).resolve())
        for p in self.config.backup_targets:
            roots.append(Path(p).resolve())
        return roots

    def _assert_path_allowed(self, raw_path: str) -> Path:
        cand = Path(raw_path).resolve()
        allowed = self._allowed_roots()
        if not any(cand == r or r in cand.parents for r in allowed):
            raise PermissionError(f"Path outside allowed roots: {cand}")
        return cand

    def peer_http_base(self) -> str:
        if self.config.peer_ipv4:
            return f"http://{self.config.peer_ipv4}:{self.config.peer_dashboard_port}"
        return f"http://127.0.0.1:{self.http_addr[1]}"

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
            protocol_version = "HTTP/1.1"
            timeout = 15.0

            def _send_bytes(
                self,
                code: int,
                ctype: str,
                raw: bytes,
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                accept_enc = (self.headers.get("Accept-Encoding") or "").lower()
                use_gzip = len(raw) >= 512 and "gzip" in accept_enc
                body = gzip.compress(raw, compresslevel=5) if use_gzip else raw
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Vary", "Accept-Encoding")
                if use_gzip:
                    self.send_header("Content-Encoding", "gzip")
                if extra_headers:
                    for k, v in extra_headers.items():
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def _send_json(
                self,
                code: int,
                obj: Any,
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self._send_bytes(
                    code,
                    "application/json; charset=utf-8",
                    body,
                    extra_headers=extra_headers,
                )

            def _read_body(self) -> bytes:
                clen = int(self.headers.get("Content-Length", "0"))
                return self.rfile.read(clen) if clen > 0 else b""

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/":
                    _, raw_json, etag = daemon_ref.get_cached_status()
                    safe_json = raw_json.decode("utf-8").replace("</", "<\\/")
                    hydrated = _DASHBOARD_HTML.replace(
                        "/*__INIT_STATE__*/null", safe_json, 1
                    ).replace("/*__INIT_ETAG__*/\"\"", json.dumps(etag), 1)
                    self._send_bytes(
                        200,
                        "text/html; charset=utf-8",
                        hydrated.encode("utf-8"),
                        extra_headers={"Cache-Control": "no-cache"},
                    )
                    return
                if parsed.path == "/api/health":
                    self._send_json(
                        200,
                        {
                            "ok": True,
                            "version": "4.0.0",
                            "node_name": daemon_ref.config.node_name,
                            "role": daemon_ref.config.role,
                            "hardware": cpu_caps(),
                            "zero_weight": get_zero_weight_status(),
                        },
                    )
                    return
                if parsed.path == "/api/nat/profile":
                    self._send_json(200, discover_nat_profile())
                    return
                if parsed.path == "/api/nat/session":
                    qs = urllib.parse.parse_qs(parsed.query)
                    tok = qs.get("token", [""])[0]
                    st = daemon_ref.nat_responder.get_session(tok)
                    self._send_json(200 if st else 404, st or {"error": "Session not found"})
                    return
                if parsed.path == "/api/edge/stats":
                    self._send_json(200, daemon_ref.edge_stats())
                    return
                if parsed.path == "/api/sentinel/status":
                    if (
                        daemon_ref.config.role == "controller"
                        and daemon_ref.config.peer_ipv4
                        and "local=1" not in parsed.query
                    ):
                        try:
                            rem = _http_get_json(f"{daemon_ref.peer_http_base()}/api/sentinel/status", timeout_s=4.0)
                            self._send_json(200, rem)
                            return
                        except Exception:
                            pass
                    self._send_json(200, daemon_ref.sentinel.latest_status())
                    return
                if parsed.path == "/api/search/stats":
                    if (
                        daemon_ref.code_search.stats().get("indexed_files", 0) == 0
                        and daemon_ref.config.peer_ipv4
                        and "local=1" not in parsed.query
                    ):
                        try:
                            rem = _http_get_json(f"{daemon_ref.peer_http_base()}/api/search/stats", timeout_s=4.0)
                            self._send_json(200, rem)
                            return
                        except Exception:
                            pass
                    self._send_json(200, daemon_ref.code_search.stats())
                    return
                if parsed.path == "/api/backup/list":
                    self._send_json(200, {"backups": list_holo_backups(daemon_ref.backup_root)})
                    return
                if parsed.path == "/api/backup/shard":
                    qs = urllib.parse.parse_qs(parsed.query)
                    bid = sanitize_workspace_id(qs.get("backup_id", [""])[0])
                    idx_s = qs.get("idx", ["1"])[0]
                    if idx_s not in ("0", "1", "2"):
                        self._send_json(400, {"error": "Invalid shard idx"})
                        return
                    bdir = (daemon_ref.backup_root / bid).resolve()
                    if daemon_ref.backup_root.resolve() not in bdir.parents:
                        self._send_json(403, {"error": "Invalid backup_id"})
                        return
                    cand = bdir / ("export_shard_2.chshard" if idx_s == "2" and (bdir / "export_shard_2.chshard").is_file() else f"shard_{idx_s}.chshard")
                    if not cand.is_file():
                        self._send_json(404, {"error": "Shard not found"})
                        return
                    self._send_bytes(200, "application/octet-stream", cand.read_bytes())
                    return
                if parsed.path == "/api/status":
                    _, raw_json, etag = daemon_ref.get_cached_status()
                    inm = (self.headers.get("If-None-Match") or "").strip()
                    if inm == etag:
                        self.send_response(304)
                        self.send_header("ETag", etag)
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self._send_bytes(
                        200,
                        "application/json; charset=utf-8",
                        raw_json,
                        extra_headers={"ETag": etag, "Cache-Control": "no-cache"},
                    )
                    return
                if parsed.path == "/api/cluster/report":
                    qs = urllib.parse.parse_qs(parsed.query)
                    fmt = qs.get("format", ["json"])[0]
                    st_payload, _, _ = daemon_ref.get_cached_status()
                    if fmt == "md":
                        md_bytes = format_cluster_markdown_report(st_payload).encode("utf-8")
                        self._send_bytes(
                            200,
                            "text/markdown; charset=utf-8",
                            md_bytes,
                            extra_headers={"Content-Disposition": 'inline; filename="chimera_eval_report.md"'},
                        )
                        return
                    self._send_json(
                        200,
                        {
                            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                            "version": "4.0.0",
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
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
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, res_obj)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/nat/punch-offer":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        self._send_json(200, daemon_ref.nat_responder.start_session(body))
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/nat/bust":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        peer_base = str(body.get("peer_http") or daemon_ref.peer_http_base())
                        local_tm = bool(body.get("local_test_mode", not bool(daemon_ref.config.peer_ipv4)))
                        n_sock = int(body.get("num_sockets", 192 if not local_tm else 16))
                        spray = int(body.get("spray_count", 900 if not local_tm else 64))
                        res = attempt_direct_punch(
                            peer_http_base=peer_base,
                            num_sockets=n_sock,
                            spray_count=spray,
                            timeout_s=float(body.get("timeout_s", 3.5 if not local_tm else 1.5)),
                            local_test_mode=local_tm,
                        )
                        daemon_ref._last_nat_result = res
                        daemon_ref.store.log_event(
                            "INFO", "NAT_BUSTER", f"mode={res['fallback_mode']} {res['diagnosis']}"
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/edge/fetch":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        res = daemon_ref.edge_gateway.fetch(
                            app_id=str(body.get("app_id", "chimera")),
                            path=str(body.get("path", "/")),
                            query=str(body.get("query", "")),
                            method=str(body.get("method", "GET")),
                            body_b64=str(body.get("body_b64", "")),
                            content_type=str(body.get("content_type", "")),
                            allow_prefetch=bool(body.get("allow_prefetch", True)),
                            known_dict_ids=list(body.get("known_dict_ids", [])),
                        )
                        self._send_json(200, res)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except KeyError as ke:
                        self._send_json(404, {"error": str(ke)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/sentinel/scan":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            daemon_ref.config.role == "controller"
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/sentinel/scan",
                                {"local_only": True},
                                timeout_s=12.0,
                            )
                            self._send_json(200, rem)
                            return
                        rep = daemon_ref.sentinel.scan(daemon_ref.config)
                        daemon_ref.store.log_event(
                            "WARN" if rep["alert_count"] else "INFO",
                            "SENTINEL",
                            f"status={rep['status']} alerts={rep['alert_count']} logs={len(rep['logs_scanned'])} ({rep['elapsed_ms']}ms)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except Exception as exc:
                        self._send_json(500, {"error": str(exc)})
                    return

                if parsed.path == "/api/search/reindex":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            not body.get("roots")
                            and not daemon_ref.config.search_roots
                            and daemon_ref.config.role == "controller"
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/search/reindex",
                                {"local_only": True},
                                timeout_s=30.0,
                            )
                            self._send_json(200, rem)
                            return
                        raw_roots = body.get("roots")
                        if raw_roots:
                            roots = [daemon_ref._assert_path_allowed(str(r)) for r in raw_roots]
                        elif daemon_ref.config.search_roots:
                            roots = [Path(p) for p in daemon_ref.config.search_roots]
                        else:
                            roots = [Path(p) for p in daemon_ref.config.allowed_query_roots] or [daemon_ref.ops_dir]
                        rep = daemon_ref.code_search.incremental_index(roots)
                        daemon_ref.store.log_event(
                            "INFO",
                            "CODE_SEARCH",
                            f"Indexed {rep['total_files']} files (updated={rep['updated']}, skipped={rep['skipped_unchanged']}) in {rep['elapsed_ms']}ms",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/search":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        if (
                            daemon_ref.code_search.stats().get("indexed_files", 0) == 0
                            and daemon_ref.config.peer_ipv4
                            and not bool(body.get("local_only", False))
                        ):
                            rem = _http_post_json(
                                f"{daemon_ref.peer_http_base()}/api/search",
                                {
                                    "query": body.get("query", ""),
                                    "limit": body.get("limit", 10),
                                    "repo": body.get("repo", ""),
                                    "local_only": True,
                                },
                                timeout_s=8.0,
                            )
                            self._send_json(200, rem)
                            return
                        res = daemon_ref.code_search.search(
                            query=str(body.get("query", "")),
                            limit=int(body.get("limit", 10)),
                            repo=str(body.get("repo", "")),
                        )
                        self._send_json(200, res)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/store-shard":
                    try:
                        ct = (self.headers.get("Content-Type") or "").lower()
                        raw_body = self._read_body()
                        if "application/json" in ct or raw_body.lstrip().startswith(b"{"):
                            obj = json.loads(raw_body.decode("utf-8"))
                            shard_bytes = base64.b64decode(str(obj["shard_b64"]).encode("ascii"))
                        else:
                            shard_bytes = raw_body
                        ack = store_received_shard(shard_bytes, daemon_ref.backup_root)
                        daemon_ref.store.log_event(
                            "INFO",
                            "HOLO_BACKUP",
                            f"Stored remote shard #{ack['shard_idx']} for {ack['backup_id']} ({ack['bytes']}B)",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, ack)
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/create":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        raw_paths = body.get("paths")
                        if raw_paths:
                            targets = [daemon_ref._assert_path_allowed(str(p)) for p in raw_paths]
                        elif daemon_ref.config.backup_targets:
                            targets = [Path(p) for p in daemon_ref.config.backup_targets if Path(p).exists()]
                        else:
                            cfg_file = daemon_ref.ops_dir / "config.json"
                            if not cfg_file.exists():
                                daemon_ref.config.save(daemon_ref.ops_dir)
                            targets = [cfg_file]
                        peer_base = (
                            daemon_ref.peer_http_base()
                            if (daemon_ref.config.peer_ipv4 and not bool(body.get("no_sync", False)))
                            else ""
                        )
                        rep = create_holo_backup(
                            paths=targets,
                            backup_root=daemon_ref.backup_root,
                            backup_id=str(body.get("backup_id", "")),
                            peer_http_base=peer_base,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "HOLO_BACKUP",
                            f"Created (2,3) GF256 {rep['backup_id']} raw={rep['raw_bytes']}B shard={rep['shard_bytes']}B peer_synced={rep['peer_synced']}",
                        )
                        daemon_ref.invalidate_status_cache()
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
                    return

                if parsed.path == "/api/backup/restore":
                    try:
                        body = json.loads(self._read_body().decode("utf-8") or "{}")
                        broot = daemon_ref.backup_root.resolve()
                        shards_raw = body.get("shard_paths", [])
                        if len(shards_raw) < 2:
                            self._send_json(400, {"error": "Provide at least 2 shard_paths"})
                            return
                        shard_paths: list[Path] = []
                        for sp in shards_raw:
                            cand = Path(str(sp)).resolve()
                            if broot not in cand.parents or not cand.is_file():
                                raise PermissionError(f"Invalid shard path outside backup_root: {sp}")
                            shard_paths.append(cand)
                        bid = sanitize_backup_id(str(body.get("backup_id", shard_paths[0].parent.name)))
                        out_dir = daemon_ref.backup_root / "restored" / bid
                        rep = restore_holo_backup(shard_paths, out_dir=out_dir)
                        self._send_json(200, rep)
                    except PermissionError as pe:
                        self._send_json(403, {"error": str(pe)})
                    except Exception as exc:
                        self._send_json(400, {"error": str(exc)})
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

        if int(self.config.edge_proxy_port) >= 0:
            proxy_peer = self.peer_http_base()
            self._local_edge_proxy = LocalEdgeProxy(
                listen_host="127.0.0.1",
                listen_port=int(self.config.edge_proxy_port),
                peer_http_base=proxy_peer,
                targets=self.config.edge_targets,
                telepathy_store=self.telepathy_store,
            ).start()
            self.config.edge_proxy_port = self._local_edge_proxy.addr[1]

        t_http = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t_sched = threading.Thread(target=self._scheduler_loop, daemon=True)
        t_http.start()
        t_sched.start()
        self._threads.extend([t_http, t_sched])
        zw = get_zero_weight_status()
        self.store.log_event(
            "INFO",
            "DAEMON",
            f"v4.0 Started on http://{self.http_addr[0]}:{self.http_addr[1]} | RAM={zw['daemon_ram_mb']}MB | Beam={self.config.beam_port} Query={self.config.query_port} EdgeProxy={self.config.edge_proxy_port}",
        )
        return self

    def edge_stats(self) -> dict[str, Any]:
        return {
            "gateway": self.edge_gateway.stats(),
            "local_proxy": self._local_edge_proxy.stats() if self._local_edge_proxy is not None else None,
        }

    def invalidate_status_cache(self) -> None:
        with self._status_cache_lock:
            self._status_cache_ts = 0.0
            self._status_cache_data = None

    def get_cached_status(self, ttl_s: float = 15.0) -> tuple[dict[str, Any], bytes, str]:
        now = time.monotonic()
        with self._status_cache_lock:
            if self._status_cache_data is not None and (now - self._status_cache_ts) < ttl_s:
                return self._status_cache_data
        payload = self.status_payload()
        raw_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        etag = f'"{hashlib.blake2s(raw_json, digest_size=8).hexdigest()}"'
        entry = (payload, raw_json, etag)
        with self._status_cache_lock:
            self._status_cache_data = entry
            self._status_cache_ts = time.monotonic()
        return entry

    def status_payload(self) -> dict[str, Any]:
        return {
            "version": "4.0.0",
            "config": self.config.to_dict(),
            "hardware": cpu_caps(),
            "zero_weight": get_zero_weight_status(),
            "telepathy_dicts": self.telepathy_store.list_dicts(),
            "today_daily_done": self.store.has_daily_run_today(),
            "telemetry": self.store.get_dashboard_state(limit=30),
            "cluster": self.store.get_cluster_overview(limit=30),
            "sentinel": self.sentinel.latest_status(),
            "code_search": self.code_search.stats(),
            "edge": self.edge_stats(),
            "holo_backups": list_holo_backups(self.backup_root)[:8],
            "nat_last": self._last_nat_result,
        }

    def run_cycle(self, trigger: str = "manual") -> dict[str, Any]:
        with self._run_lock:
            res = run_daily_autopilot(
                self.config, self.store, trigger=trigger, ops_dir=self.ops_dir
            )
            self.invalidate_status_cache()
            return res

    def _scheduler_loop(self) -> None:
        if self.auto_seed_on_empty:
            st = self.store.get_dashboard_state(limit=1)
            if st["total_runs"] == 0 and not self._stop.wait(timeout=1.5):
                try:
                    self.run_cycle(trigger="startup_seed")
                except Exception:
                    pass

        is_persistent = not self._ephemeral_mode
        last_sentinel = 0.0
        if is_persistent and (self.config.role == "server" or self.config.search_roots):
            try:
                if self.config.search_roots:
                    self.code_search.incremental_index([Path(p) for p in self.config.search_roots])
                if self.config.role == "server":
                    self.sentinel.scan(self.config)
                    last_sentinel = time.monotonic()
                self.invalidate_status_cache()
            except Exception as exc:
                self.store.log_event("ERROR", "HYPEROS_INIT", str(exc))

        sent_iv = max(60, int(getattr(self.config, "sentinel_interval_s", 300)))
        while not self._stop.wait(timeout=30.0):
            try:
                now_hm = datetime.now().astimezone().strftime("%H:%M")
                if now_hm >= self.config.daily_time and not self.store.has_daily_run_today():
                    self.run_cycle(trigger="daemon_daily")
                if is_persistent and self.config.role == "server":
                    if (time.monotonic() - last_sentinel) >= sent_iv:
                        self.sentinel.scan(self.config)
                        last_sentinel = time.monotonic()
                        self.invalidate_status_cache()
            except Exception as exc:
                self.store.log_event("ERROR", "SCHEDULER", str(exc))

    def close(self) -> None:
        self._stop.set()
        if self._local_edge_proxy is not None:
            self._local_edge_proxy.close()
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
        self.sentinel.close()
        self.code_search.close()
        self.store.close()

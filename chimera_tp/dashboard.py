"""24/7 CHIMERA-HYPER Mission-Control Daemon, Scheduler & Interactive Web Dashboard."""

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
    make_synthetic_logs,
    remote_active_query,
)
from .autopilot import (
    VALID_PROFILES,
    OpsConfig,
    TelemetryStore,
    _build_incremental_sample,
    default_ops_dir,
    run_daily_autopilot,
)
from .fabric import BeamServer, beam_send
from .hyper_wire import HedgedRpcServer
from .native import cpu_caps
from .probe import probe_environment
from .protocol import ChimeraReceiver, ChimeraSender, FaultProfile
from .warp import WarpServer

_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA-HYPER v2.0 Mission Control</title>
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
  .shell { max-width: 1260px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  .topbar {
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;
    background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px;
  }
  .brand h1 { font-size: 17px; font-weight: 700; letter-spacing: 0.02em; display: flex; align-items: center; gap: 8px; }
  .badge { font-family: var(--mono); font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgba(34,211,238,0.14); color: var(--cyan); border: 1px solid rgba(34,211,238,0.3); }
  .badge.ok { background: rgba(52,211,153,0.14); color: var(--green); border-color: rgba(52,211,153,0.35); }
  .badge.warn { background: rgba(251,191,36,0.14); color: var(--amber); border-color: rgba(251,191,36,0.35); }
  .badge.err { background: rgba(248,113,113,0.14); color: var(--red); border-color: rgba(248,113,113,0.35); }
  .meta-line { color: var(--muted); font-size: 11.5px; font-family: var(--mono); margin-top: 4px; }

  .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button, select, input {
    font-family: inherit; font-size: 12px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--card2); color: var(--fg); padding: 7px 12px; outline: none;
  }
  button { cursor: pointer; font-weight: 600; transition: 0.15s ease; }
  button:hover { border-color: var(--cyan); background: #1e293b; }
  button.primary { background: rgba(34,211,238,0.18); border-color: rgba(34,211,238,0.5); color: #67e8f9; }
  button.primary:disabled { opacity: 0.5; cursor: wait; }

  .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
  .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  @media (max-width: 900px) { .grid-4, .grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
  @media (max-width: 580px) { .grid-4, .grid-2 { grid-template-columns: 1fr; } }

  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 15px 17px; }
  .card-title { font-size: 12.5px; font-weight: 700; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .kpi-val { font-size: 26px; font-weight: 800; font-family: var(--mono); line-height: 1.15; }
  .kpi-sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  td.mono { font-family: var(--mono); }

  .query-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .query-bar input { flex: 1; min-width: 140px; font-family: var(--mono); }
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
      <h1>CHIMERA-HYPER v2.0 <span class="badge" id="node-badge">...</span> <span class="badge ok" id="sched-badge">DAILY ...</span></h1>
      <div class="meta-line" id="hw-meta">Probing node hardware & link state...</div>
    </div>
    <div class="controls">
      <select id="profile-select" title="Active Darwinian Profile">
        <option value="auto-darwin">auto-darwin (UCB1 Self-Tuning)</option>
        <option value="max-speed">max-speed (Turbo Pipeline)</option>
        <option value="lossy-armor">lossy-armor (Proactive GFNI)</option>
        <option value="exotic-v05">exotic-v05 (Multi-Realm)</option>
      </select>
      <button class="primary" id="btn-run" onclick="triggerRun()">&#9654; Chạy đánh giá ngay</button>
      <button onclick="triggerBeam()">&#9889; Live DNA Beam &rarr; Peer</button>
      <button onclick="triggerExotic()">&#9762; Kiểm tra v0.5 Exotic</button>
    </div>
  </div>

  <div class="grid-4">
    <div class="card">
      <div class="card-title">Điểm Sức Khỏe Tổng Hợp</div>
      <div class="kpi-val" id="kpi-health" style="color:var(--green)">--</div>
      <div class="kpi-sub" id="kpi-health-sub">Chưa có phiên chạy</div>
    </div>
    <div class="card">
      <div class="card-title">Mạng WAN 5% Rớt Gói</div>
      <div class="kpi-val" id="kpi-wan" style="color:var(--cyan)">--</div>
      <div class="kpi-sub" id="kpi-wan-sub">CHIMERA GFNI vs TCP-CUBIC</div>
    </div>
    <div class="card">
      <div class="card-title">Live Beam &harr; Peer</div>
      <div class="kpi-val" id="kpi-beam" style="color:var(--purple)">--</div>
      <div class="kpi-sub" id="kpi-beam-sub">DNA FastCDC + Delta qua Tailscale</div>
    </div>
    <div class="card">
      <div class="card-title">Wormhole SHM &amp; RTT Peer</div>
      <div class="kpi-val" id="kpi-shm" style="color:var(--amber)">--</div>
      <div class="kpi-sub" id="kpi-shm-sub">IPC nội bộ &amp; Hedged p99</div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        <span>Đối chiếu Trước (TCP chuẩn) vs Sau (CHIMERA-HYPER)</span>
        <span class="meta-line" id="latest-ts"></span>
      </div>
      <div id="compare-panel"><div class="meta-line">Nhấn "Chạy đánh giá ngay" để lấy số đo trực tiếp...</div></div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Biểu đồ Xu hướng Đa Ngày (Health &amp; Speedup)</span>
        <span class="meta-line" id="trend-count">0 runs</span>
      </div>
      <svg id="trend-svg" viewBox="0 0 560 190" style="width:100%;height:190px;display:block;"></svg>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-title">
        <span>Active Compute-in-Transit &rarr; Peer (Lọc log ngay tại máy đích)</span>
        <span class="meta-line" id="query-badge">UDP 9704</span>
      </div>
      <div class="query-bar">
        <input id="q-needle" value="ERROR" placeholder="Từ khóa lọc (vd: ERROR, pull, INFO)">
        <input id="q-file" value="" placeholder="File đích (để trống dùng file cấu hình)">
        <button onclick="triggerQuery()">&#128269; Chạy Query từ xa</button>
      </div>
      <div class="log-box" id="query-out">Chưa chạy truy vấn trực tiếp.</div>
    </div>

    <div class="card">
      <div class="card-title">
        <span>Darwinian Genome UCB1 Leaderboard</span>
        <span class="meta-line">Tự học &amp; chọn cấu hình tối ưu</span>
      </div>
      <table>
        <thead><tr><th>Genome</th><th>Pulls</th><th>Avg Reward</th><th>Params</th></tr></thead>
        <tbody id="genome-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-title">
      <span>Nhật ký Hoạt động &amp; Cảnh báo Tự động (SQLite Persistent)</span>
      <span class="meta-line" id="services-meta"></span>
    </div>
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
    svg.innerHTML = '<text x="280" y="95" text-anchor="middle" fill="#64748b" font-size="12">Chưa có lịch sử chạy</text>';
    return;
  }
  const W = 560, H = 190, L = 38, R = 16, T = 18, B = 26;
  const pw = W - L - R, ph = H - T - B;
  let html = '';
  for (let g of [0, 50, 100]) {
    const y = T + ph - (g / 100) * ph;
    html += `<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="rgba(148,163,184,0.16)" stroke-dasharray="3 3"/>`;
    html += `<text x="${L-6}" y="${y+4}" text-anchor="end" fill="#94a3b8" font-size="10" font-family="monospace">${g}</text>`;
  }
  const n = history.length;
  const maxWan = Math.max(20, ...history.map(h => h.wan_5pct_speedup || 0));
  const ptsH = [], ptsW = [];
  history.forEach((h, i) => {
    const x = n === 1 ? L + pw / 2 : L + (i / (n - 1)) * pw;
    const yh = T + ph - (Math.min(100, h.health_score) / 100) * ph;
    const yw = T + ph - (Math.min(maxWan, h.wan_5pct_speedup) / maxWan) * ph;
    ptsH.push(`${x.toFixed(1)},${yh.toFixed(1)}`);
    ptsW.push(`${x.toFixed(1)},${yw.toFixed(1)}`);
  });
  html += `<polyline fill="none" stroke="#34d399" stroke-width="2.2" points="${ptsH.join(' ')}"/>`;
  html += `<polyline fill="none" stroke="#22d3ee" stroke-width="2" stroke-dasharray="4 2" points="${ptsW.join(' ')}"/>`;
  history.forEach((h, i) => {
    const x = n === 1 ? L + pw / 2 : L + (i / (n - 1)) * pw;
    const yh = T + ph - (Math.min(100, h.health_score) / 100) * ph;
    html += `<circle cx="${x.toFixed(1)}" cy="${yh.toFixed(1)}" r="3.5" fill="#34d399"><title>#${h.id} ${h.ts_local} | score=${h.health_score} | WAN=${h.wan_5pct_speedup}x</title></circle>`;
  });
  html += `<text x="${L}" y="${H-6}" fill="#34d399" font-size="10">● Health (0-100)</text>`;
  html += `<text x="${L+115}" y="${H-6}" fill="#22d3ee" font-size="10">--- WAN 5% Speedup (max ${maxWan.toFixed(0)}x)</text>`;
  svg.innerHTML = html;
}

function renderState(st) {
  const cfg = st.config || {};
  const hw = st.hardware || {};
  document.getElementById('node-badge').textContent = `${cfg.node_name || 'node'} (${cfg.role || 'ctrl'})`;
  document.getElementById('sched-badge').textContent = `DAILY ${cfg.daily_time || '08:00'} • ${st.today_daily_done ? 'HÔM NAY ĐÃ CHẠY' : 'CHỜ LỊCH'}`;
  document.getElementById('hw-meta').textContent =
    `HW: native=${hw.native} gfni=${hw.gfni} avx2=${hw.avx2} | Peer: ${cfg.peer_name || '-'} (${cfg.peer_ipv4 || 'local-only'})`;
  document.getElementById('profile-select').value = cfg.active_profile || 'auto-darwin';
  document.getElementById('services-meta').textContent =
    `Ports: Beam=${cfg.beam_port} RPC=${cfg.rpc_v4_port}/${cfg.rpc_v6_port} Query=${cfg.query_port} Warp=${cfg.warp_port}`;
  if (!document.getElementById('q-file').value && cfg.watched_query_file) {
    document.getElementById('q-file').placeholder = cfg.watched_query_file;
  }

  const db = st.telemetry || {};
  const latest = db.latest;
  if (latest) {
    document.getElementById('latest-ts').textContent = `${latest.ts_local} (${latest.trigger}) • ${latest.genome_id}`;
    const sc = latest.health_score;
    const hEl = document.getElementById('kpi-health');
    hEl.textContent = `${sc}/100`;
    hEl.style.color = sc >= 85 ? 'var(--green)' : (sc >= 60 ? 'var(--amber)' : 'var(--red)');
    document.getElementById('kpi-health-sub').textContent = latest.anomalies.length ? 'Cảnh báo: ' + latest.anomalies.join(', ') : 'Mọi kênh & thuật toán ổn định';

    const loc = latest.local || {};
    document.getElementById('kpi-wan').textContent = `${loc.wan_5pct_speedup || 0}x`;
    document.getElementById('kpi-wan-sub').textContent = `CHIMERA ${loc.wan_5pct_chimera_mbps} vs TCP ${loc.wan_5pct_tcp_mbps} Mbps`;

    const pr = latest.peer || {};
    if (pr.reachable) {
      document.getElementById('kpi-beam').textContent = `${pr.beam_speedup}x (${pr.beam_saved_pct}%)`;
      document.getElementById('kpi-beam-sub').textContent = `${pr.beam_eff_mbps} Mbps eff vs TCP ${pr.tcp_upload_mbps} Mbps`;
      document.getElementById('kpi-shm').textContent = `${loc.wormhole_gbps} Gbps | ${pr.rtt_p50_ms}ms`;
      document.getElementById('kpi-shm-sub').textContent = `Peer p99: Single ${pr.single_p99_ms}ms -> Hedged ${pr.hedged_p99_ms}ms`;
    } else {
      document.getElementById('kpi-beam').textContent = 'Offline/Local';
      document.getElementById('kpi-beam-sub').textContent = pr.reason || 'Chưa cấu hình peer';
      document.getElementById('kpi-shm').textContent = `${loc.wormhole_gbps} Gbps`;
      document.getElementById('kpi-shm-sub').textContent = `TCP loopback: ${loc.tcp_loopback_gbps} Gbps`;
    }

    let cmp = '';
    cmp += `<div class="cmp-row"><span>Lõi GF(256) 32×1180 Solve</span><span class="mono">Python ${loc.gfni_py_ms}ms &rarr; <b>Native ${loc.gfni_native_ms}ms (${loc.gfni_speedup}x)</b></span></div>`;
    cmp += `<div class="cmp-row"><span>IPC nội bộ 16 MiB (SHA-256)</span><span class="mono">TCP ${loc.tcp_loopback_gbps} Gbps &rarr; <b>Wormhole ${loc.wormhole_gbps} Gbps</b></span></div>`;
    cmp += `<div class="cmp-row"><span>WAN 5% Drop (40ms RTT)</span><span class="mono">TCP ${loc.wan_5pct_tcp_mbps} Mbps &rarr; <b>GFNI ${loc.wan_5pct_chimera_mbps} Mbps (${loc.wan_5pct_speedup}x)</b></span></div>`;
    if (pr.reachable) {
      cmp += `<div class="cmp-row"><span>Live ${pr.peer_name} DNA Beam 1 MiB</span><span class="mono">TCP ${pr.tcp_upload_ms}ms &rarr; <b>Beam ${pr.beam_elapsed_ms}ms (-${pr.beam_saved_pct}% dây, ${pr.beam_speedup}x)</b></span></div>`;
      cmp += `<div class="cmp-row"><span>Live ${pr.peer_name} Active Query</span><span class="mono">TCP ${pr.query_tcp_ms}ms &rarr; <b>Pipe ${pr.query_chimera_ms}ms (-${pr.query_saved_pct}% dây, P0 ${pr.query_p0_ms}ms)</b></span></div>`;
      cmp += `<div class="cmp-row"><span>Live Dual-Stack Hedged RPC</span><span class="mono">V4 p99 ${pr.single_p99_ms}ms &rarr; <b>V4+V6 p99 ${pr.hedged_p99_ms}ms</b></span></div>`;
    }
    document.getElementById('compare-panel').innerHTML = cmp;
  }

  renderTrend(db.history || []);

  const gt = document.getElementById('genome-tbody');
  gt.innerHTML = (db.genomes || []).map(g => {
    const p = g.params || {};
    return `<tr><td class="mono">${g.genome_id}</td><td class="mono">${g.pulls}</td><td class="mono" style="color:var(--cyan)">${g.avg_reward.toFixed(2)}</td><td class="mono">k=${p.gen_k} win=${p.max_inflight_gens} loss=${p.loss_hint} hedge=${p.hedge_delay_ms}ms</td></tr>`;
  }).join('');

  const evs = (db.events || []).map(e => `[${e.ts_local}] [${e.level}] [${e.category}] ${e.message}`).join('\n');
  document.getElementById('events-box').textContent = evs || 'No events recorded yet.';
}

async function refresh() {
  try {
    const st = await api('/api/status');
    renderState(st);
  } catch (e) { console.error(e); }
}

async function triggerRun() {
  const b = document.getElementById('btn-run');
  b.disabled = true; b.textContent = 'Đang chạy kiểm chứng...';
  try {
    await api('/api/run?sync=1', { method: 'POST' });
    await refresh();
  } catch (e) { alert('Lỗi: ' + e.message); }
  finally { b.disabled = false; b.textContent = '▶ Chạy đánh giá ngay'; }
}

async function triggerBeam() {
  try {
    const res = await api('/api/live-beam', { method: 'POST' });
    alert(`Live DNA Beam xong!\nWire: ${res.udp_wire_bytes} B / ${res.raw_bytes} B (Tiết kiệm ${res.reduction_pct}%)\nThời gian: ${res.elapsed_ms} ms`);
    await refresh();
  } catch (e) { alert('Live Beam error: ' + e.message); }
}

async function triggerQuery() {
  const needle = document.getElementById('q-needle').value || 'ERROR';
  const file = document.getElementById('q-file').value || '';
  document.getElementById('query-out').textContent = 'Đang thực thi Active Compute-in-Transit trên peer...';
  try {
    const res = await api('/api/live-query', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ needle, file_path: file })
    });
    document.getElementById('query-out').textContent =
      `Matched: ${res.matched_records} dòng | Wire: ${res.wire_bytes}/${res.raw_bytes} B (-${res.wire_reduction_pct}%) | P0 Preview: ${res.preview_first_ms}ms | Total: ${res.total_ms}ms\n--- Top Preview ---\n` +
      (res.preview_items || []).join('\n');
    await refresh();
  } catch (e) {
    document.getElementById('query-out').textContent = 'Lỗi: ' + e.message;
  }
}

async function triggerExotic() {
  try {
    const res = await api('/api/exotic-audit', { method: 'POST' });
    alert('Exotic v0.5 Status:\n' + JSON.stringify(res, null, 2));
    await refresh();
  } catch (e) { alert('Exotic audit error: ' + e.message); }
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
    """24/7 Mission-Control HTTP + UDP service host & daily self-scheduling daemon."""

    def __init__(
        self,
        config: OpsConfig | None = None,
        ops_dir: Path | None = None,
        auto_seed_on_empty: bool = False,
    ) -> None:
        self.ops_dir = Path(ops_dir) if ops_dir else default_ops_dir()
        self.config = config if config is not None else OpsConfig.load(self.ops_dir)
        self.store = TelemetryStore(self.ops_dir / "telemetry.db")
        self.auto_seed_on_empty = auto_seed_on_empty

        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._beam_srv: BeamServer | None = None
        self._rpc_srv: HedgedRpcServer | None = None
        self._query_srv: ActiveQueryServer | None = None
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
        # 1) Start persistent BeamServer
        self._beam_srv = BeamServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.beam_port),
            vault_dir=self.ops_dir / "rx_vault",
            out_dir=self.ops_dir / "received_beam",
        ).start()
        self.config.beam_port = self._beam_srv.ctrl_addr[1]

        # 2) Start Dual-Stack HedgedRpcServer (IPv4 + optional IPv6)
        rpc_binds: list[tuple[str, int]] = [("0.0.0.0", int(self.config.rpc_v4_port))]
        if int(self.config.rpc_v6_port) >= 0:
            try:
                test_srv = HedgedRpcServer(
                    rpc_binds + [("::", int(self.config.rpc_v6_port))],
                    handler=lambda b: b"CHIMERA-PONG:" + b[:32],
                ).start()
                self._rpc_srv = test_srv
            except OSError:
                self._rpc_srv = HedgedRpcServer(
                    rpc_binds,
                    handler=lambda b: b"CHIMERA-PONG:" + b[:32],
                ).start()
        else:
            self._rpc_srv = HedgedRpcServer(
                rpc_binds, handler=lambda b: b"CHIMERA-PONG:" + b[:32]
            ).start()
        self.config.rpc_v4_port = self._rpc_srv.addrs[0][1]
        if len(self._rpc_srv.addrs) > 1:
            self.config.rpc_v6_port = self._rpc_srv.addrs[1][1]

        # 3) Start ActiveQueryServer
        self._query_srv = ActiveQueryServer(
            bind_ip="0.0.0.0",
            bind_port=int(self.config.query_port),
            allowed_roots=self._allowed_roots(),
        ).start()
        self.config.query_port = self._query_srv.addr[1]

        # 4) Start HTTP Control Dashboard first so Warp can target it cleanly
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
                            "node_name": daemon_ref.config.node_name,
                            "role": daemon_ref.config.role,
                            "hardware": cpu_caps(),
                        },
                    )
                    return
                if parsed.path == "/api/status":
                    self._send_json(200, daemon_ref.status_payload())
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
                        {
                            "bytes": clen - rem,
                            "sha256": hasher.hexdigest(),
                            "server_ms": round(ms, 2),
                        },
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
                        res, meta = remote_active_query(
                            (peer_ip, peer_qport),
                            file_path=fpath,
                            plan=ComputePlan(op="filter_lines", needle=needle),
                            est_loss=0.02,
                            timeout_s=15.0,
                        )
                        daemon_ref.store.log_event(
                            "INFO",
                            "LIVE_QUERY",
                            f"needle={needle!r} matched={res.matched_records} wire_saved={res.wire_reduction_pct}% in {res.total_ms}ms",
                        )
                        out = res.to_dict()
                        out["server_exec_ms"] = meta.get("server_exec_ms", 0.0)
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
        self.store.log_event(
            "INFO",
            "DAEMON",
            f"Started on http://{self.http_addr[0]}:{self.http_addr[1]} | Beam={self.config.beam_port} Query={self.config.query_port}",
        )
        return self

    def status_payload(self) -> dict[str, Any]:
        return {
            "version": "2.0.0",
            "config": self.config.to_dict(),
            "hardware": cpu_caps(),
            "today_daily_done": self.store.has_daily_run_today(),
            "telemetry": self.store.get_dashboard_state(limit=30),
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
        for srv in (self._warp_srv, self._query_srv, self._rpc_srv, self._beam_srv):
            if srv is not None:
                srv.close()
        self.store.close()

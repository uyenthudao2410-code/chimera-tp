"""CHIMERA-NOOSPHERE v27.0 LIVING ORGANISM COMMAND — Zero-WebGL 2D Cognitive Symbiosis Console."""

from __future__ import annotations

import base64
import zlib

UNIVERSE_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA // LIVING ORGANISM v27 — CHIMERA-HYPER v12.0 OMEGA-GALACTIC</title>
<style>
:root{--bg:#070b14;--s1:#0d1424;--s2:#131d33;--bd:#1e2c47;--bd2:#30466e;--fg:#e8eef8;--mu:#879ab8;--cy:#38bdf8;--gr:#10b981;--am:#f59e0b;--vi:#a78bfa;--rd:#f43f5e;--tl:#2dd4bf;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;--mono:ui-monospace,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:var(--bg);color:var(--fg);font:12px/1.38 var(--sans);overflow:hidden}
body.tac #app{display:none!important}body.tac #tactical-deck{display:flex}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}.mu{color:var(--mu)}.ok{color:var(--gr)}.wn{color:var(--am)}.er{color:var(--rd)}.in{color:var(--cy)}.vi{color:var(--vi)}.tl{color:var(--tl)}
#app{display:grid;grid-template-rows:46px 228px 232px 1fr;gap:8px;padding:8px 13px;height:100vh;width:100vw}
.card{background:var(--s1);border:1px solid var(--bd);border-radius:8px;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.ch{display:flex;align-items:center;justify-content:space-between;padding:5.5px 10px;border-bottom:1px solid var(--bd);background:rgba(19,29,51,.65);gap:8px;flex-shrink:0;white-space:nowrap}
.ct{font-size:10.3px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;display:flex;align-items:center;gap:6px;color:#f1f5f9;white-space:nowrap}
.ct i,.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0}
.row,.sb{display:flex;align-items:center;gap:6px}.sb{justify-content:space-between}
#top{flex-direction:row;align-items:center;justify-content:space-between;padding:0 12px;gap:8px;border-color:rgba(16,185,129,.28)}
.logo{width:28px;height:28px;border-radius:7px;background:linear-gradient(135deg,#10b981,#0284c7 60%,#8b5cf6);display:flex;align-items:center;justify-content:center;font:800 11.5px var(--mono);color:#fff;flex-shrink:0;box-shadow:0 0 12px rgba(16,185,129,.28)}
.pill{display:inline-flex;align-items:center;gap:4px;padding:2px 6.5px;border-radius:99px;border:1px solid var(--bd);background:var(--s2);font:600 9.6px var(--mono);white-space:nowrap}
.pill.live{border-color:rgba(16,185,129,.5);background:rgba(16,185,129,.12);color:#6ee7b7}
.pill.bio{border-color:rgba(45,212,191,.45);background:rgba(45,212,191,.1);color:#5eead4}
.pill.warn{border-color:rgba(245,158,11,.5);background:rgba(245,158,11,.12);color:#fcd34d}
.pill.pain{border-color:rgba(244,63,94,.55);background:rgba(244,63,94,.14);color:#fda4af}
.dot.pulse{background:var(--gr);transition:transform .16s}.dot.hit{transform:scale(1.65);background:#fff}
button,input{font:600 9.9px var(--sans);color:var(--fg);background:var(--s2);border:1px solid var(--bd);border-radius:5px;padding:3px 7px;outline:none;cursor:pointer;white-space:nowrap}
button:hover,.tab.active,.flt.active{border-color:var(--cy);background:rgba(56,189,248,.16);color:#fff}
button.pri{background:#0284c7;border-color:#38bdf8;color:#fff}button.bio{background:rgba(16,185,129,.16);border-color:rgba(16,185,129,.55);color:#6ee7b7}button.act{border-color:var(--am);color:var(--am)}
button.xs,.tab,.flt{padding:2.2px 6.5px;font-size:9.8px}
#topo-wrap{position:relative;flex:1;min-height:0;background:radial-gradient(circle at 22% 45%,rgba(16,185,129,.06),transparent 48%),radial-gradient(circle at 78% 45%,rgba(167,139,250,.06),transparent 48%)}
#mesh-svg{width:100%;height:100%;display:block}
.nd{cursor:pointer}.nd rect.box{fill:#0f192d;stroke:var(--nc,#33486b);stroke-width:1.35;rx:8;transition:fill .15s,stroke-width .15s}
.nd:hover rect.box,.nd.on rect.box{fill:#162542;stroke-width:2.3}
.nd.dim{opacity:.33}
.pipe-bg{fill:none;stroke-width:4;opacity:.14}.pipe-fg{fill:none;stroke-width:1.85;stroke-dasharray:6 5;animation:flow 1.3s linear infinite}
.pipe-fg.rev{animation-direction:reverse}.pipe-fg.hot{stroke-width:2.8;opacity:1!important}.pipe-fg.dim{opacity:.18}
@keyframes flow{to{stroke-dashoffset:-22}}
#inspector{padding:4px 11px;border-top:1px solid var(--bd);background:#0a101e;font-size:10.3px;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-shrink:0}
#charts{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;min-height:0}
.cb{padding:7px 9px;display:flex;flex-direction:column;gap:5.5px;flex:1;min-height:0}
.kpi-row{display:grid;grid-template-columns:repeat(3,1fr);gap:5.5px}
.kpi{background:var(--s2);border:1px solid rgba(48,70,110,.55);border-radius:5px;padding:3.5px 6px;min-width:0}
.kpi small{display:block;font-size:8.8px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kpi b{display:block;font:700 10.8px var(--mono);color:#f8fafc;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cv{width:100%;flex:1;min-height:74px;display:block}
#bottom{display:grid;grid-template-columns:1.25fr 1fr;gap:9px;min-height:0}
#flow-feed{flex:1;overflow-y:auto;min-height:0}
.ftbl{width:100%;border-collapse:collapse;font:10.3px/1.33 var(--mono)}
.ftbl th{position:sticky;top:0;background:#10192b;color:var(--mu);font:600 9.3px var(--sans);text-transform:uppercase;letter-spacing:.04em;text-align:left;padding:4.5px 8px;border-bottom:1px solid var(--bd)}
.ftbl td{padding:4px 8px;border-bottom:1px solid rgba(30,44,71,.62);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px}
.ftbl tr{cursor:pointer}.ftbl tbody tr:hover,.ftbl tbody tr.sel{background:rgba(56,189,248,.11)}
.badge{display:inline-block;padding:1px 5.5px;border-radius:4px;font:700 9.2px var(--mono);border:1px solid currentColor}
.dpn{display:none;flex:1;min-height:0;overflow:auto;padding:6px 9px;flex-direction:column;gap:5px}.dpn.active{display:flex}
.cgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:4.5px}
.cc{display:flex;flex-direction:column;gap:1px;padding:4px 6.5px;border-radius:5px;border:1px solid rgba(16,185,129,.35);background:rgba(16,185,129,.06);cursor:pointer;transition:border-color .15s}
.cc:hover,.cc.hi{border-color:var(--cy);background:rgba(56,189,248,.13)}
.cc.bio{border-color:rgba(45,212,191,.4);background:rgba(45,212,191,.07)}
.cc.off{border-color:rgba(244,63,94,.4);background:rgba(244,63,94,.06);opacity:.72}
.cc .cn{display:flex;align-items:center;justify-content:space-between;font:700 9.6px var(--mono);color:#f1f5f9;gap:4px}
.cc .cd{font-size:8.9px;color:var(--mu);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wsb{background:#09101d;border:1px solid var(--bd);border-radius:5px;padding:4px 7px;font:9.6px/1.35 var(--mono);color:#cbd5e1}
.wsb div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.out{background:#050810;border-top:1px solid var(--bd);padding:4px 9px;font:9.8px/1.3 var(--mono);color:#a7f3d0;height:36px;overflow:auto;white-space:pre-wrap;word-break:break-word;flex-shrink:0}
.tbl{width:100%;border-collapse:collapse;font:10px var(--mono)}.tbl th,.tbl td{text-align:left;padding:3px 6px;border-bottom:1px solid var(--bd)}
#spotlight-modal{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:72px;background:rgba(4,8,16,.78)}#spotlight-modal.open{display:flex}
.pc{width:min(600px,92vw);background:var(--s1);border:1px solid var(--cy);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}
#tactical-deck{position:fixed;inset:10px;z-index:30;display:none;flex-direction:column;gap:8px;overflow:auto;padding:14px;background:#070c14;border:1px solid var(--bd);border-radius:10px}
.tg2{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:8px}.tb2{border:1px solid var(--bd);border-radius:6px;padding:8px;background:var(--s1)}
@media(max-width:1240px){html,body{overflow:auto}#app{height:auto;grid-template-rows:auto 240px auto auto}#charts{grid-template-columns:repeat(2,1fr)}#bottom{grid-template-columns:1fr}}
</style>
</head>
<body>
<!-- CHIMERA-HYPER v2.0 / v12.0 OMEGA-GALACTIC / OMNISCIENCE v24 / NOOSPHERE LIVING ORGANISM v27 ZERO-WEBGL -->
<div id="app">
<header id="top" class="card">
<div class="row" style="gap:7px;min-width:0">
<div class="logo">CH</div>
<div style="white-space:nowrap"><div style="font-weight:800;font-size:12.4px;color:#fff">CHIMERA // LIVING ORGANISM <span class="tl mono" style="font-size:10.5px">v27</span></div><div class="mu" style="font-size:9.4px">Noosphere · Eidolon · Immortal Relay · WIN ⇄ SVHOME</div></div>
<span class="pill live"><span class="dot pulse" id="hb-d"></span><span id="hb-l">ALIVE #0 · 1.0s</span></span>
<span class="pill bio" id="h-pain">PAIN 0.00 · OK</span>
</div>
<div class="row" style="gap:4px;flex-wrap:nowrap">
<span class="pill" id="h-win">WIN --/80M</span>
<span class="pill" id="h-sv">SVH --/80M</span>
<span class="pill in" id="h-rtt">2-WAY --ms</span>
<span class="pill ok" id="h-pr">PRISM xhigh</span>
<button class="bio" onclick="act('sync2')">Sync ⇄</button>
<button onclick="act('dream')">Dream</button>
<button id="b-ks" onclick="act('ks')">ROI Guard</button>
<button id="b-tac" onclick="tac()">Compact</button>
<button class="pri" onclick="oPal()">Ctrl+K</button>
</div>
</header>

<section class="card">
<div class="ch">
<span class="ct"><i style="background:var(--gr)"></i>Living Cognitive Organism Topology — Dual-Node Neural Symbiosis (43 MCP Tools)</span>
<div class="row">
<span class="mu" style="font-size:10px">Lọc cơ quan:</span>
<button class="xs active" data-n="all" onclick="selNode(null)">Tất cả</button>
<button class="xs" data-n="brain" onclick="selNode('brain')">Noosphere</button>
<button class="xs" data-n="win" onclick="selNode('win')">Win Soma</button>
<button class="xs" data-n="gpu" onclick="selNode('gpu')">GTX/Synes</button>
<button class="xs" data-n="sv" onclick="selNode('sv')">svhome Twin</button>
<button class="xs" data-n="eidolon" onclick="selNode('eidolon')">Eidolon</button>
<button class="xs" data-n="relay" onclick="selNode('relay')">Quota/Relay</button>
</div>
</div>
<div id="topo-wrap"><svg id="mesh-svg" viewBox="0 0 1200 178" preserveAspectRatio="xMidYMid meet"></svg></div>
<div id="inspector"><span class="mono tl" id="ins-title">NOOSPHERE LIVING SYMBIOSIS — WIN-DESKTOP ⇄ PHANTOM-5MS ⇄ SVHOME · 1 GOOGLE xhigh + 5 CODEX COLD-BRIDGE</span><span class="mu mono" id="ins-sub">Zero-WebGL 0% GPU UI · Law 2 / Law 6 / Law 7 PASS</span></div>
</section>

<section id="charts">
<article class="card">
<div class="ch"><span class="ct"><i style="background:var(--cy)"></i>Living Soma · Law 7 RAM</span><span class="mono ok" id="p-gov">LAW7 OK</span></div>
<div class="cb">
<div id="sil-list" class="kpi-row"></div>
<canvas id="c-ram" class="cv"></canvas>
<div class="sb"><span class="mu mono" style="font-size:9.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" id="hd-st">HD +0.00G · Cryo 0</span><div class="row" style="gap:4px"><button class="xs" onclick="act('cryo')">Cryo</button><button class="xs" onclick="act('thaw')">Thaw</button><button class="xs" onclick="act('wall')">Wall</button></div></div>
</div>
</article>

<article class="card">
<div class="ch"><span class="ct"><i style="background:var(--gr)"></i>2-Way Symbiosis &amp; RTT</span><span class="mono in" id="p-tun">-- ms</span></div>
<div class="cb">
<div id="net-kpi" class="kpi-row"></div>
<canvas id="c-kal" class="cv"></canvas>
<div class="sb"><span class="mu mono" style="font-size:9.4px;white-space:nowrap" id="p-tx">TX 0 MB · RX 0 MB</span><div class="row" style="gap:4px"><span class="in mono" style="font-size:9.4px" id="p-rt">0 KB/s</span><button class="xs bio" onclick="act('sync2')">Sync</button></div></div>
</div>
</article>

<article class="card">
<div class="ch"><span class="ct"><i style="background:var(--vi)"></i>GTX 1650 · Synesthesia</span><span class="mono vi" id="p-cu">2350 CU</span></div>
<div class="cb">
<div id="gpu-kpi" class="kpi-row"></div>
<canvas id="c-ph" class="cv"></canvas>
<div class="sb"><span class="mu mono" style="font-size:9.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" id="th-r">Free 8.0G/6.0G</span><div class="row" style="gap:4px"><button class="xs" id="b-thm" onclick="cycThm()">CAP 99%</button><button class="xs" onclick="act('ptx')">PTX</button><button class="xs" onclick="act('synes')">Synes</button><button class="xs" onclick="act('ctrlz')">Ctrl+Z</button></div></div>
</div>
</article>

<article class="card">
<div class="ch"><span class="ct"><i style="background:var(--tl)"></i>Cortex Shield · PRISM</span><span class="mono ok" id="om-g">xhigh 100%</span></div>
<div class="cb">
<div id="sub-kpi" class="kpi-row"></div>
<canvas id="c-ht" class="cv"></canvas>
<div class="sb"><span class="mu mono" style="font-size:9.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" id="p-pl">CB:ON · Sub:ON</span><div class="row" style="gap:4px"><button class="xs" onclick="act('dream')">Dream</button><button class="xs" onclick="act('autop')">AutoP</button><button class="xs" onclick="act('gate')">Gate</button><button class="xs" onclick="act('pano')">Pano</button></div></div>
</div>
</article>
</section>

<section id="bottom">
<article class="card">
<div class="ch">
<span class="ct"><i style="background:var(--gr)"></i>Live Neural Wire &amp; Sync Feed <span class="mu mono" id="w-ct">(0)</span></span>
<div class="row" id="fl-bar" style="gap:4px"></div>
</div>
<div id="flow-feed"></div>
</article>

<article class="card">
<div class="ch">
<span class="ct"><i style="background:var(--tl)"></i>Living Organs &amp; Substrate <span class="ok mono" id="c-cnt">43 MCP</span></span>
<div class="row" id="s-tb" style="gap:4px"></div>
</div>
<div id="pane-organs" class="dpn active"><div id="o-ch" class="cgrid"></div><div id="ws-box" class="wsb"><div><span class="tl">GlobalWorkspace:</span> đang đồng bộ ý thức 2 chiều...</div></div></div>
<div id="pane-carts" class="dpn"><div id="c-ch" class="cgrid"></div></div>
<div id="pane-ops" class="dpn"><div class="row" style="flex-wrap:wrap" id="ac-o"></div><div id="t-lg" class="mono" style="font-size:9.8px;overflow:auto;flex:1"></div></div>
<div id="pane-hyperdrive" class="dpn"><div class="row" id="ac-h"></div><div class="mu" style="font-size:10px">Benchmark v9.0 Hyperdrive + PHANTOM direct UDP &amp; NIXL 22µs mmap.</div></div>
<div id="pane-galactic" class="dpn"><div class="row" id="ac-g"></div><div id="h-tb" style="flex:1;overflow:auto"></div></div>
<div class="out" id="h-out">CHIMERA LIVING ORGANISM v27 sẵn sàng — Noosphere + Eidolon + Immortal Relay + 2-Way Sync.</div>
</article>
</section>
</div>

<section id="tactical-deck"><div class="sb" style="border-bottom:1px solid var(--bd);padding-bottom:6px"><b>CHIMERA // LIVING COMPACT OPS</b><div class="row" id="t-act"></div></div><div class="tg2" id="t-gr"></div><div class="out" id="t-out" style="height:220px">--</div></section>
<div id="spotlight-modal" onclick="if(event.target===this)cPal()"><div class="pc"><div class="sb"><span class="tl" style="font-weight:700">Noosphere Command Spotlight (Ctrl+K)</span><button onclick="cPal()">ESC</button></div><div class="row"><input id="spotlight-input" style="flex:1" placeholder="sync2 / dream / autop / pano / gate / synes / precog / scout / cryo / ptx / <tìm cụm>" onkeydown="if(event.key==='Enter')xPal()"><button class="pri" onclick="xPal()">Chạy</button></div><div class="out" id="spotlight-out" style="height:180px">Gọi trực tiếp bất kỳ cơ quan sống nào hoặc tìm kiếm toàn cụm &lt;5ms.</div></div></div>

<script>
window.__INIT_STATE__=/*__INIT_STATE__*/null;let _et=/*__INIT_ETAG__*/"";
const $=i=>document.getElementById(i),Q=s=>document.querySelectorAll(s),T=(i,v)=>{const e=$(i);if(e)e.textContent=v;},E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),M=Math,mn=M.min,mx=M.max,psh=(a,v)=>{a.push(v);a.shift();},clm=(v,a,b)=>mx(a,mn(b,v)),bt=(a,c)=>a.map(([l,f])=>`<button${c?' class="'+c+'"':''} onclick="${f}">${l}</button>`).join('');
const C0='#38bdf8',C1='#10b981',C2='#f59e0b',C3='#a78bfa',C4='#f43f5e',C5='#2dd4bf';
const P1='/v1/hyperdesk/',P2='/api/galactic/',P3='/v1/noosphere/',P4='/v1/eidolon/';
const A={
  sync2:[P3+'sync','2WAY_SYNC',{timeout:3.0}],
  tick:[P3+'tick','PULSE_TICK',{trigger:'ui'}],
  dream:[P3+'dream','DREAM',{reason:'ui_manual'}],
  epiph:[P3+'epiphany','EPIPHANY',null],
  subc:[P3+'subconscious','SUBCONSCIOUS',{prompt:'Generate 5-word title for CHIMERA Living Organism console',category:'title'}],
  gate:[P3+'deploy-gate?service=tquota','DEPLOY_GATE',null],
  pano:[P3+'panopticon','PANOPTICON',null],
  autop:[P4+'autopoiesis','AUTOPOIESIS',{}],
  synes:[P4+'synesthesia','SYNESTHESIA',{}],
  precog:[P4+'precog-verify','PRECOG_SVH',{rel_path:'ui_probe.py',content:'def alive(): return True\n',offload_to_peer:true}],
  scout:[P4+'scout','SCOUT',{repo:'.',pattern:'noosphere|preempt',max_files:30,max_tokens:320}],
  opt:[P1+'optimize','DESK'],cryo:[P1+'cryo','CRYO'],thaw:[P1+'thaw','THAW'],wall:[P1+'silicon-wall','WALL'],
  ptx:['/v1/vgpu/ptx-bench','PTX',{n:65536,force:true}],emb:['/v1/openai/v1/embeddings','EMBED',{input:['noosphere'],dimensions:128}],
  teleport:[P2+'live-teleport','TELEPORT'],frost:[P2+'live-frost','FROST'],vsa:[P2+'vsa-query','VSA',{trials:100,corrupt_pct:.4}],
  chmc:[P2+'live-chmc','CHMC'],freeze:['/v1/blackbox/freeze','FREEZE'],ctrlz:['/v1/omega/multiverse/ctrl-z','CTRLZ'],ph:['/api/phantom/connect','PHANTOM']
};
const CD={connect:['Beacon :9780','win'],egress_membrane:['DLP + Cache :9781','eidolon'],pulse:['Cross-Host PubSub','sv'],hybrid_search:['<5ms Index Search','eidolon'],blackbox:['60s Ring Recorder','eidolon'],diskless_secrets:['RAM-Only Secrets','eidolon'],vgpu_pareto:['4-Tier GPU Router','gpu'],immortal_jobs:['Self-Healing Jobs','relay'],browser_grid:['Headless Browser','win'],zygote_canary:['<10ms Worker Fork','sv'],vault_sql:['SQLite Mesh Sync','sv'],ghost_bubble:['CoW Dry-Run Box','eidolon'],hyper_desk:['Cryo + CPU Wall','win'],cosmos_entity:['Thermo Phase Grid','gpu'],omega_entity:['Self-Evolve Genome','brain'],agent_hyper_bus:['Zero-Spawn 43 MCP','brain']};
const S={tac:0,hb:0,ks:0,wR:30,sR:58,wFree:8.5,sFree:6.0,rtt:5.8,kx:5.8,kp:1.4,kk:.4,tx:0,rx:0,conns:0,pong:0,rk:0,lb:0,lt:0,cpu:14,watts:38,gt:50,gu:8,vf:2048,vt:4096,cu:2350,cm:'AUTO:SLEEP',oaiM:3,apps:[],eh:0,egR:0,dlp:0,bb:0,vdb:0,ij:0,hd:{},th:{},om:{},tr:{},ct:{},org:{alive:true,mcp_tools:43,pain:0,sync_cnt:0,sync_rtt:0,ws_items:0,dreams:0,antibodies:0,sub_saved:0,ws_top:[]},prm:{},fl:[],lf:0,si:0,foc:null,flt:'all',tM:'cool_99',hotPipe:'',pr:null};
const C=window.__CORTEX__={version:'27.0',webgl:false,zeroGpu:true,unified:true,living:true,noosphere:true,eidolon:true,flowsSeen:0};
const R={w:Array(36).fill(30),s:Array(36).fill(58),kr:Array(36).fill(5.8),ke:Array(36).fill(5.8),ph:Array.from({length:28},()=>({x:.28,y:.35})),hn:['NOOSPHERE','2-WAY SYNC','EIDOLON','PRISM/CB','SILICON'],ht:Array.from({length:5},()=>Array(18).fill(.2)),tr:[]};

const kpi=a=>a.map(([l,v,c])=>`<div class="kpi"><small>${l}</small><b class="${c||''}">${E(v)}</b></div>`).join('');
const fmtK=n=>n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':String(n|0);

function renOrgans(){
  const o=S.org||{},p=S.prm||{},e=o.eidolon||{};
  const cards=[
    ['Autonomic Pulse',o.alive?'LIVE':'IDLE',`ticks:${o.ticks||0} · ${o.tick_ms||0}ms · 0 proc`,'tick','brain',o.alive],
    ['2-Way Symbiosis',o.sync_on?`${o.sync_cnt||0} sync`:'WAIT',`RTT ${o.sync_rtt||S.kx.toFixed(1)}ms · ${o.sync_err||0} err`,'sync2','sv',!(o.sync_err>0)],
    ['Immune Reflex',`Pain ${(o.pain||0).toFixed(2)}`,`${o.antibodies||0} antibodies · ${o.gc_trims||0} GC`,'pano','brain',(o.pain||0)<.4],
    ['Nocturnal Dream',o.dreams?`${o.dreams} runs`:(o.has_epiphany?'EPIPHANY':'READY'),o.has_epiphany?'Morning Epiphany READY':'NREM+REM shadow (Law 6)','dream','brain',1],
    ['Subconscious 0t',p.sub_on?'ACTIVE':'READY',`saved:${fmtK(o.sub_saved||0)}t · <2ms local`,'subc','relay',1],
    ['Codex Cold-Bridge',p.cb_on?'LIVE 0t':'OPT-IN',`hits:${p.cb_hits||0} · 5 Codex · xhigh OK`,'gate','relay',1],
    ['Eidolon Exoskel',`${e.scout||0}sc/${e.fuzz||0}fz`,'SHA-256 Scout · 0t Fuzzer','scout','eidolon',1],
    ['Precog → svhome',`${e.precog||0} ver`,'0% Win CPU shadow twin','precog','sv',1],
    ['Synesthesia VSA',`${e.syn_proj||4} repo`,`${e.syn_mem||160} episodic memories`,'synes','gpu',1]
  ];
  $('o-ch').innerHTML=cards.map(([nm,st,ds,ac,og,ok])=>`<div class="cc bio ${ok?'':'off'} ${S.foc===og?'hi':''}" data-org="${og}" onclick="act('${ac}')"><div class="cn"><span>${E(nm)}</span><span class="${ok?'tl':'wn'}">${E(st)}</span></div><div class="cd">${E(ds)}</div></div>`).join('');
  const top=o.ws_top||[];
  $('ws-box').innerHTML=top.length?top.map(it=>`<div><span class="tl">[${E(it.k)}]</span> ${E(it.s)}</div>`).join(''):`<div><span class="tl">GlobalWorkspace (${o.ws_items||0} items):</span> Click bất kỳ cơ quan sống nào ở trên để thực thi trực tiếp.</div>`;
}

function renKPIs(){
  const o=S.org||{},p=S.prm||{},e=o.eidolon||{},vr=S.vt?M.round((S.vt-S.vf)/S.vt*100):0,hdMb=S.hd.reclaimed_mb||0;
  $('sil-list').innerHTML=kpi([['WIN DAEMON',`${S.wR.toFixed(1)} MB`,S.wR>72?'er':'ok'],['SVH DAEMON',`${S.sR.toFixed(1)} MB`,S.sR>75?'er':'ok'],['WIN CPU / PWR',`${S.cpu|0}% · ${S.watts|0}W`,S.cpu>85?'wn':'in']]);
  $('net-kpi').innerHTML=kpi([['2-WAY SYNC',`${o.sync_cnt||0} · ${o.sync_rtt||S.kx.toFixed(1)}ms`,(o.sync_err||0)?'er':'ok'],['KALMAN PHANTOM',`${S.kx.toFixed(2)} ms`,S.kx>40?'wn':'in'],['TUNNELS / PONG',`${S.conns}d · ${S.pong.toFixed(0)}s`,'mu']]);
  $('gpu-kpi').innerHTML=kpi([['GTX 1650',`${S.gt.toFixed(0)}°C · ${S.gu|0}%`,S.gt>72?'er':S.gt>60?'wn':'ok'],['SYNESTHESIA',`${e.syn_proj||4}r · ${e.syn_mem||160}m`,'tl'],['VRAM / COLAB',`${vr}% · ${S.cu|0}CU`,'vi']]);
  const hitTxt=p.hit_pct!=null?`${Number(p.hit_pct).toFixed(1)}%`:'READY';
  $('sub-kpi').innerHTML=kpi([['PRISM CACHE',`${hitTxt} · ${p.edits||0}ed`,(p.edits||0)?'wn':'ok'],['SAVED QUOTA',`${fmtK(p.saved_tok||0)} · ${M.round(p.saved_wk||0)}%`,'tl'],['SUB / BRIDGE',`${p.sub_hits||0}s · ${p.cb_hits||0}cb`,'vi']]);
  T('hd-st',`HD +${(hdMb/1024).toFixed(2)}G · Cryo ${S.hd.cryo_procs||0} · Echo ${o.echo_hits||0}`);
  T('p-tx',`TX ${(S.tx/1048576).toFixed(2)}M · RX ${(S.rx/1048576).toFixed(2)}M`);
  T('th-r',`Free ${S.wFree.toFixed(1)}G/${S.sFree.toFixed(1)}G`);
  T('h-win',`WIN ${S.wR.toFixed(1)}/80M`);T('h-sv',`SVH ${S.sR.toFixed(1)}/80M`);T('h-rtt',`2-WAY ${(o.sync_rtt||S.kx).toFixed(1)}ms`);
  T('h-pr',`PRISM ${hitTxt} · xhigh`);
  const pn=Number(o.pain||0),pe=$('h-pain');
  if(pe){pe.textContent=`PAIN ${pn.toFixed(2)} · ${pn>=.65?'ALERT':pn>=.35?'STRESS':'HEALTHY'}`;pe.className='pill '+(pn>=.65?'pain':pn>=.35?'warn':'bio');}
  T('p-pl',`CB:${p.cb_on?'ON':'OFF'} · Sub:${p.sub_on?'ON':'OFF'} · WF:${p.wf_sessions||0}s`);
  T('om-g',p.xhigh_ok===false?'EFFORT ERR':'xhigh 100%');
  T('c-cnt',`${o.mcp_tools||43} MCP`);
  renOrgans();
}

function flowPipe(f){
  if(!f)return '';
  const op=String(f.op||'').toUpperCase(),src=String(f.src||'').toLowerCase(),dst=String(f.dst||'').toLowerCase();
  if(/NOOSPHERE|DREAM|SYNC|PULSE|PHANTOM/.test(op)||dst.includes('svhome')&&src.includes('win'))return 'win-sv';
  if(/APP_ATTACH/.test(op)||/tquota|tqouta|radar/.test(src))return 'sv-relay';
  if(/EGRESS|TARPIT|DLP|SCOUT|FUZZ/.test(op)||src==='external')return 'sv-eidolon';
  if(/PTX|EMBED|COLAB|GPU|SYN/.test(op))return 'win-gpu';
  if(/VSA|TELEPORT|FROST|CHMC|CTRLZ/.test(op))return 'brain-win';
  return 'win-sv';
}

function drawTopo(){
  const f=S.foc,selF=S.fl[S.si],actP=S.hotPipe||flowPipe(selF),o=S.org||{},p=S.prm||{},e=o.eidolon||{};
  const hitTxt=p.hit_pct!=null?`${Number(p.hit_pct).toFixed(1)}%`:'READY';
  const N=[
    ['brain',8,16,216,144,C5,'1. NOOSPHERE BRAIN',o.alive?`LIVE · #${o.ticks||0}`:'INIT',[`AutonomicPulse: ${o.tick_ms||0}ms (0 proc)`,`Pain ${(o.pain||0).toFixed(2)} · ${o.antibodies||0} Antibodies`,`Workspace: ${o.ws_items||0} shared facts`,`Dreams: ${o.dreams||0} · ${o.mcp_tools||43} MCP Tools`]],
    ['win',292,8,248,76,C0,'2. WIN-DESKTOP SOMA',`${S.wR.toFixed(1)} / 80 MB`,[`CPU ${S.cpu|0}% · ${S.watts|0}W · Free ${S.wFree.toFixed(1)}G`,`Zero-Echo ${o.echo_hits||0} · NIXL 22µs · Law 7`]],
    ['gpu',292,94,248,76,C3,'3. GTX 1650 · SYNESTHESIA',`${e.syn_proj||4}r · ${e.syn_mem||160}m`,[`GTX1650 ${S.gt.toFixed(0)}°C (${S.gu|0}%) · PTX sm_75`,`Colab ${S.cu|0}CU (${S.cm.replace('AUTO:','')}) · 0MB idle`]],
    ['sv',646,8,248,76,C1,'4. SVHOME TWIN HUB',`${S.sR.toFixed(1)} / 80 MB`,[`2-Way Sync: ${o.sync_cnt||0}× (${o.sync_rtt||S.kx.toFixed(1)}ms · 0 err)`,`Precog Twin: ${e.precog||0} offloads · XFS CoW`]],
    ['eidolon',646,94,248,76,C2,'5. EIDOLON EXOSKELETON',`0-Chatter · Law 6`,[`Scout ${e.scout||0} · Silent Fuzzer ${e.fuzz||0} (0t)`,`Egress :9781 (${S.egR} req) · Panopticon`]],
    ['relay',976,16,216,144,C1,'6. QUOTA · IMMORTAL',p.xhigh_ok===false?'ERR':(p.gate?'GATE PASS':`${hitTxt} LIVE`),[`PRISM Hit: ${hitTxt} · xhigh 100%`,`Saved: ${fmtK(p.saved_tok||0)}t (${M.round(p.saved_wk||0)}% wk)`,`Subconscious 0t + 5 Codex Bridge`,`Steer <1ms · Deploy Gate ARMED`]]
  ];
  const E0=[
    ['brain-win',224,66,292,46,C5,'NIXL 22µs',0,'brain','win'],
    ['brain-gpu',224,118,292,132,C3,'VSA / PTX',0,'brain','gpu'],
    ['win-sv',540,46,646,46,C1,`2-Way ${(o.sync_rtt||S.kx).toFixed(1)}ms`,0,'win','sv'],
    ['win-gpu',416,84,416,94,C3,'PTX',0,'win','gpu'],
    ['sv-eidolon',770,84,770,94,C2,'CoW',0,'sv','eidolon'],
    ['gpu-eidolon',540,132,646,132,C2,'Precog / VSA',1,'gpu','eidolon'],
    ['sv-relay',894,46,976,66,C1,'Cold-Bridge',0,'sv','relay'],
    ['eidolon-relay',894,132,976,114,C5,'Immune Gate',0,'eidolon','relay']
  ];
  const out=[];
  E0.forEach(([id,x1,y1,x2,y2,c,lbl,rev,a,b])=>{
    const hit=actP===id,rel=!f||f===a||f===b,mx0=(x1+x2)/2,my0=(y1+y2)/2,d=x1===x2?`M${x1} ${y1}L${x2} ${y2}`:`M${x1} ${y1}C${mx0} ${y1} ${mx0} ${y2} ${x2} ${y2}`;
    out.push(`<path d="${d}" class="pipe-bg" stroke="${c}"/><path d="${d}" class="pipe-fg${rev?' rev':''}${hit?' hot':''}${!rel?' dim':''}" stroke="${c}"/>`);
    if(x1!==x2){
      const lx=mx0,ly=my0-(y1===y2?10:0),tw=mx(64,lbl.length*5.8+12);
      out.push(`<rect x="${lx-tw/2}" y="${ly-9}" width="${tw}" height="15" rx="7" fill="${hit?'#162642':'#0a1120'}" stroke="${c}" stroke-width="${hit?1.4:.85}" opacity="${rel?1:.3}"/><text x="${lx}" y="${ly+2}" fill="${hit?'#fff':c}" font-size="8.8" font-family="ui-monospace,Consolas,monospace" font-weight="700" text-anchor="middle" opacity="${rel?1:.3}">${E(lbl)}</text>`);
    }
  });
  N.forEach(([id,x,y,w,h,c,title,stat,lines])=>{
    const on=f===id,dim=f&&!on&&!E0.some(e=>(e[8]===f&&e[9]===id)||(e[9]===f&&e[8]===id));
    let ls='';lines.forEach((ln,i)=>ls+=`<text x="${x+10}" y="${y+42+i*18}" fill="#bfd0e8" font-size="9.6" font-family="ui-monospace,Consolas,monospace">${E(ln)}</text>`);
    out.push(`<g class="nd${on?' on':''}${dim?' dim':''}" style="--nc:${c}" onclick="selNode('${id}')"><rect class="box" x="${x}" y="${y}" width="${w}" height="${h}"/><rect x="${x}" y="${y}" width="${w}" height="24" rx="8" fill="${c}" opacity=".15"/><circle cx="${x+12}" cy="${y+12}" r="3.5" fill="${c}"/><text x="${x+21}" y="${y+15.5}" fill="#f8fafc" font-size="9.6" font-weight="700">${E(title)}</text><text x="${x+w-8}" y="${y+15.5}" fill="${c}" font-size="9.2" font-family="ui-monospace,Consolas,monospace" font-weight="700" text-anchor="end">${E(stat)}</text>${ls}</g>`);
  });
  $('mesh-svg').innerHTML=out.join('');
}

function selNode(n){
  S.foc=S.foc===n?null:n;
  Q('[data-n]').forEach(b=>b.classList.toggle('active',b.dataset.n===(S.foc||'all')));
  Q('.cc').forEach(e=>e.classList.toggle('hi',!!S.foc&&e.dataset.org===S.foc));
  const o=S.org||{},p=S.prm||{},desc={
    brain:['NOOSPHERE BRAIN (5 Living Organs · 43 MCP)',`Pulse #${o.ticks||0} (${o.tick_ms||0}ms) · Pain ${(o.pain||0).toFixed(2)} · ${o.ws_items||0} Workspace facts · ${o.dreams||0} NREM+REM dreams`],
    win:['WIN-DESKTOP SOMA (Law 7 <80MB · Law 2 Zero-Choke)',`Daemon ${S.wR.toFixed(1)}MB · CPU ${S.cpu|0}% · Free ${S.wFree.toFixed(1)}G · Zero-Echo ${o.echo_hits||0} hits`],
    gpu:['GTX 1650 PTX + ECOSYSTEM SYNESTHESIA + COLAB',`GTX1650 ${S.gt.toFixed(0)}°C (${S.gu|0}%) · 4 repos / 160 episodic memories · Colab ${S.cu|0} CU`],
    sv:['SVHOME TWIN HUB (24/7 XFS CoW + 2-Way Symbiosis)',`Daemon ${S.sR.toFixed(1)}MB · 2-Way Sync ${o.sync_cnt||0}× (${o.sync_rtt||S.kx.toFixed(1)}ms) · Precog Shadow Twin 0% Win CPU`],
    eidolon:['EIDOLON ZERO-CHATTER EXOSKELETON (Law 6 Shadow)',`SHA-256 Scout (-99.8%) · Silent Fuzzer (0t PASS) · Autopoiesis · Panopticon · Egress :9781`],
    relay:['QUOTA SHIELD & IMMORTAL RELAY (1 Google xhigh + 5 Codex)',`PRISM ${p.hit_pct!=null?p.hit_pct+'%':'LIVE'} · Saved ${fmtK(p.saved_tok||0)}t · Subconscious 0t + Cold-Bridge + Steer <1ms`]
  }[S.foc];
  if(desc){T('ins-title',desc[0]);T('ins-sub',desc[1]);}
  else{const c=S.fl[S.si];T('ins-title',c?`LIVE SIGNAL #${c.id} · ${c.op} (${c.src} ──► ${c.dst})`:'NOOSPHERE LIVING SYMBIOSIS — WIN-DESKTOP ⇄ PHANTOM-5MS ⇄ SVHOME · 1 GOOGLE xhigh + 5 CODEX COLD-BRIDGE');T('ins-sub',c?`${c.detail||'rpc'} • ${c.bytes||0}B • ${c.ms}ms • ${c.ts}`:'Click vào cơ quan sống hoặc dòng sự kiện để quan sát và điều khiển trực tiếp');}
  drawTopo();renFl(S.fl,1);
}

function drawCharts(){
  const P=(id,fn)=>{const c=$(id);if(!c)return;const r=c.getBoundingClientRect();if(r.width<10||r.height<10)return;const d=mn(2,devicePixelRatio||1),W=M.round(r.width*d),H=M.round(r.height*d);if(c.width!==W||c.height!==H){c.width=W;c.height=H;}const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);x.clearRect(0,0,r.width,r.height);x.font='600 9px ui-monospace,Consolas,monospace';
    const ln=(p,cl,w,da)=>{x.save();x.strokeStyle=cl;x.lineWidth=w||1.6;if(da)x.setLineDash(da);x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.stroke();x.restore();};
    const ar=(p,cl,al,b)=>{x.save();x.fillStyle=cl;x.globalAlpha=al;x.beginPath();x.moveTo(p[0][0],b);p.forEach(([X,Y])=>x.lineTo(X,Y));x.lineTo(p[p.length-1][0],b);x.closePath();x.fill();x.restore();};
    const dt=(X,Y,rd,cl)=>{x.fillStyle=cl;x.beginPath();x.arc(X,Y,rd,0,6.283);x.fill();};
    const tx=(s,X,Y,cl)=>{x.fillStyle=cl||'#8799b5';x.fillText(s,X,Y);};
    const grid=(pL,pT,pw,ph,rows)=>{for(let i=0;i<=rows;i++){const y=pT+ph*i/rows;ln([[pL,y],[pL+pw,y]],'rgba(48,70,110,.35)',1);}};
    fn(x,r.width,r.height,ln,ar,dt,tx,grid);
  };
  P('c-ram',(x,W,H,ln,ar,dt,tx,grid)=>{
    const pL=26,pT=12,pw=W-pL-6,ph=H-22,my=v=>pT+ph-clm(v,0,90)/90*ph;
    grid(pL,pT,pw,ph,3);tx('90M',1,pT+4);tx('80M',1,my(80)+3,C4);tx('40M',1,my(40)+3);tx('0',10,pT+ph+3);
    ln([[pL,my(80)],[pL+pw,my(80)]],C4,1,[4,3]);
    [[R.s,C1],[R.w,C0]].forEach(([a,cl])=>{const p=a.map((v,i)=>[pL+i*pw/(a.length-1),my(v)]);ar(p,cl,.13,pT+ph);ln(p,cl,1.8);dt(...p[p.length-1],2.8,cl);});
    tx(`WIN ${S.wR.toFixed(1)}M`,pL+4,9,C0);tx(`SVH ${S.sR.toFixed(1)}M`,pL+76,9,C1);tx('LAW7 80M',W-50,9,C4);
  });
  P('c-kal',(x,W,H,ln,ar,dt,tx,grid)=>{
    const pL=30,pT=12,pw=W-pL-6,ph=H-22,lo=mx(0,mn(...R.kr)-2),hi=mx(lo+8,mx(...R.kr)+2),my=v=>pT+ph-(clm(v,lo,hi)-lo)/(hi-lo)*ph;
    grid(pL,pT,pw,ph,3);tx(`${hi.toFixed(0)}ms`,1,pT+4);tx(`${((hi+lo)/2).toFixed(0)}ms`,1,pT+ph/2+3);tx(`${lo.toFixed(0)}ms`,1,pT+ph+3);
    const ep=R.ke.map((v,i)=>[pL+i*pw/(R.ke.length-1),my(v)]);
    ar(ep,C1,.14,pT+ph);R.kr.forEach((v,i)=>dt(pL+i*pw/(R.kr.length-1),my(v),1.5,C0));ln(ep,C1,1.8);dt(...ep[ep.length-1],3,'#fff');
    tx(`Symbiosis ${S.kx.toFixed(2)}ms`,pL+4,9,C1);tx('PHANTOM',W-48,9,C0);
  });
  P('c-ph',(x,W,H,ln,ar,dt,tx,grid)=>{
    const pL=28,pT=12,pw=W-pL-6,ph=H-22;
    [['rgba(244,63,94,.12)',0,.3],['rgba(245,158,11,.08)',.3,.35],['rgba(16,185,129,.08)',.65,.35]].forEach(([c,y,h])=>{x.fillStyle=c;x.fillRect(pL,pT+ph*y,pw,ph*h);});
    grid(pL,pT,pw,ph,3);tx('85°',4,pT+4,C4);tx('60°',4,pT+ph/2+3,C2);tx('35°',4,pT+ph+3,C1);
    const pts=R.ph.map(q=>[pL+q.x*pw,pT+(1-q.y)*ph]);
    ln(pts,C3,1.6);const lp=pts[pts.length-1],lc=S.gt>72?C4:S.gt>58?C2:C1;dt(lp[0],lp[1],3.8,lc);
    tx(`GTX1650 (${S.gt.toFixed(0)}°C · ${S.gu|0}%)`,pL+4,9,'#e2e8f0');
  });
  P('c-ht',(x,W,H,ln,ar,dt,tx)=>{
    const lw=68,cw=(W-lw-4)/18,rh=(H-14)/5;
    tx('5 LIVING ORGANS VITALITY (LIVE)',1,9,C5);
    R.hn.forEach((nm,r)=>{
      const y0=13+r*rh;tx(nm,1,y0+rh*.74,'#b7c6dd');
      for(let k=0;k<18;k++){const v=R.ht[r][k];x.fillStyle=v>.78?C1:v>.5?C5:v>.26?'#0284c7':'#142038';x.fillRect(lw+k*cw+1,y0+1.5,mx(2,cw-2.2),mx(3,rh-3));}
    });
  });
}

function renFl(fl,keep){
  if(!fl)return;
  if(!keep&&fl.length){
    const n=fl[0].id;
    if(n>S.lf&&S.lf){S.si=0;S.hotPipe=flowPipe(fl[0]);pTr(fl[0].lane||'wire',`${fl[0].op} ${fl[0].src}→${fl[0].dst} (${fl[0].ms}ms)`,fl[0].ok?'ok':'er');}
    S.lf=mx(S.lf,n);S.fl=fl;C.flowsSeen=fl.length;
  }
  const f=S.flt,fn=S.foc;
  const rows=S.fl.filter(x=>{
    if(f==='apps'&&!/APP_ATTACH/.test(x.op))return false;
    if(f==='sync'&&!/VSA|PULSE|TELEPORT|PHANTOM|NOOSPHERE|SYNC/.test(x.op))return false;
    if(f==='egress'&&!/EGRESS|TARPIT|DLP|CONNECT/.test(x.op))return false;
    if(f==='compute'&&x.lane!=='compute'&&!/PTX|EMBED|DREAM/.test(x.op))return false;
    if(fn){const p=flowPipe(x);if(!p.includes(fn))return false;}
    return true;
  });
  T('w-ct',`(${rows.length}/${S.fl.length})`);
  const bc=x=>x.lane==='compute'?'wn':x.lane==='crypto'?'vi':x.lane==='tarpit'||!x.ok?'er':/VSA|PHANTOM|SYNC|NOOSPHERE/.test(x.op)?'ok':'in';
  $('flow-feed').innerHTML=`<table class="ftbl"><thead><tr><th>Time</th><th>Operation</th><th>Transfer Route</th><th>Size</th><th>Latency</th><th>Detail</th></tr></thead><tbody>`+
    (rows.length?rows.slice(0,24).map(x=>{const idx=S.fl.indexOf(x);return`<tr class="${idx===S.si?'sel':''}" onclick="selFl(${idx})"><td class="mu">${E(x.ts)}</td><td><span class="badge ${bc(x)}">${E(x.op)}</span></td><td><b>${E(x.src)}</b> <span class="in">──►</span> <b>${E(x.dst)}</b></td><td class="mu">${x.bytes?x.bytes+' B':'—'}</td><td class="${x.ok?'ok':'er'}">${x.ms} ms</td><td class="mu">${E(x.detail||'ok')}</td></tr>`;}).join(''):`<tr><td colspan="6" class="mu" style="padding:14px;text-align:center">Chưa có sự kiện khớp bộ lọc hiện tại.</td></tr>`)+`</tbody></table>`;
}
function selFl(i){S.si=i;const c=S.fl[i];if(c){S.hotPipe=flowPipe(c);T('ins-title',`LIVE SIGNAL #${c.id} · ${c.op} (${c.src} ──► ${c.dst})`);T('ins-sub',`${c.detail||'rpc'} • ${c.bytes||0} B • ${c.ms} ms • ${c.ts}`);}drawTopo();renFl(S.fl,1);}
function setFlt(k){S.flt=k;Q('.flt').forEach(b=>b.classList.toggle('active',b.dataset.f===k));renFl(S.fl,1);}

const log=t=>{T('h-out',t);T('t-out',t);};
async function api(u,b){const r=await fetch(u,b!==undefined&&b!==null?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined),t=await r.text();let j;try{j=JSON.parse(t);}catch(_){j={raw:t};}if(!r.ok)throw new Error(j.error||r.statusText);return j;}
async function rq(u,b,tag){try{const r=await api(u,b);if(tag)pTr(tag.toLowerCase(),JSON.stringify(r).slice(0,72),'ok');log(JSON.stringify(r,null,2));await pulse();return r;}catch(e){log('Err: '+e.message);}}
const act=k=>k==='ks'?rq('/api/trinity/kill-switch',{active:!S.ks,reason:S.ks?'resume':'guard'},'ROI'):A[k]&&rq(A[k][0],A[k][2]===undefined?{}:A[k][2],A[k][1]);
const cycThm=()=>{S.tM=S.tM==='cool_99'?'eco_85':(S.tM==='eco_85'?'turbo_100':'cool_99');T('b-thm',S.tM==='cool_99'?'CAP 99%':S.tM==='eco_85'?'ECO 85%':'TURBO');rq(P1+'thermostat',{mode:S.tM},'THERMO');};
const tp=()=>rq(P2+'tarpit/env/prod.yml',null,'TARPIT'),togC=n=>n==='connect'?log('Core Beacon luôn bật.'):rq('/v1/cartridges',{name:n,enabled:!S.ct[n]},'CART');
const bW=w=>runB(P2+'benchmark',{wave:w});
async function runB(u,b={}){const r=await rq(u,b,'BENCH');if(r&&r.ideas){selSec('galactic');$('h-tb').innerHTML='<table class="tbl"><thead><tr><th>Idea</th><th>Result</th><th>OK</th></tr></thead><tbody>'+Object.values(r.ideas).slice(0,29).map(x=>`<tr><td>${E(x.name)}</td><td class="in">${E(x.after)}</td><td class="${x.ok?'ok':'er'}">${x.ok?'PASS':'FAIL'}</td></tr>`).join('')+'</tbody></table>';}}
function tac(){S.tac=!S.tac;document.body.classList.toggle('tac',S.tac);$('b-tac').classList.toggle('act',S.tac);}
function selSec(id){Q('.tab').forEach(t=>t.classList.toggle('active',t.dataset.id===id));Q('.dpn').forEach(p=>p.classList.remove('active'));const p=$('pane-'+id);if(p)p.classList.add('active');}
const oPal=()=>{$('spotlight-modal').classList.add('open');$('spotlight-input').focus();},cPal=()=>$('spotlight-modal').classList.remove('open');
async function xPal(){const q=($('spotlight-input').value||'').trim(),l=q.toLowerCase();if(!q)return;if(A[l]){cPal();return act(l);}if(l==='tarpit'){cPal();return tp();}if(l==='bench'){cPal();return bW('all');}if(l==='compact'||l==='tactical'){cPal();return tac();}try{T('spotlight-out',JSON.stringify(await api('/api/hyperdrive/search?q='+encodeURIComponent(q)+'&limit=12'),null,2));}catch(e){T('spotlight-out','Err: '+e.message);}}
function pTr(k,m,c){R.tr.push([new Date().toTimeString().slice(0,8),k,m,c||'in']);if(R.tr.length>18)R.tr.shift();$('t-lg').innerHTML=R.tr.slice(-10).map(([t,k2,m2,c2])=>`<div><span class="mu">${t}</span> <b class="${c2}">${E(k2)}</b> ${E(m2)}</div>`).join('');}
function sKal(o){const p=S.kp+.08,K=p/(p+1.2);S.kx+=K*(o-S.kx);S.kp=(1-K)*p;S.kk=K;psh(R.kr,o);psh(R.ke,S.kx);}
function upB(z,ph,init){
  if(z&&z.daemon_ram_mb!=null){S.wR=+z.daemon_ram_mb;if(z.host_free_ram_gb!=null)S.wFree=+z.host_free_ram_gb;if(init)R.w.fill(S.wR);else psh(R.w,S.wR);T('tz',`${S.wR.toFixed(1)}/80 MB`);}
  if(ph&&ph.direct_rtt_ms!=null){S.rtt=+ph.direct_rtt_ms;S.conns=ph.active_conns||0;S.tx=ph.tx_bytes||0;S.rx=ph.rx_bytes||0;S.pong=ph.last_pong_age_s||0;if(init){S.kx=S.rtt;R.kr.fill(S.rtt);R.ke.fill(S.rtt);}else sKal(S.rtt);T('p-tun',`${S.rtt.toFixed(2)} ms`);}else if(!init)sKal(S.kx);
}

let _pB=0,_bl=0;
async function pulse(){
  if(document.hidden||_pB)return;_pB=1;
  try{
    const p=await api('/api/pulse'),{zero_weight:z={},phantom:ph0={},peer:pr0,platform:pl,trinity:tr}=p,ph=ph0.client||{},pr=pr0||S.pr;if(pr)S.pr=pr;
    S.hb++;const d=$('hb-d');if(d){d.classList.add('hit');setTimeout(()=>d.classList.remove('hit'),160);}T('hb-l',`ALIVE #${S.hb} · ${_bl?'2.5s':'1.0s'}`);
    upB(z,ph,0);
    if(pr&&pr.zero_weight&&pr.zero_weight.daemon_ram_mb!=null){S.sR=+pr.zero_weight.daemon_ram_mb;if(pr.zero_weight.host_free_ram_gb!=null)S.sFree=+pr.zero_weight.host_free_ram_gb;T('tp',`${pr.node_name} ${S.sR.toFixed(1)} MB`);}
    if(pl&&pl.organism&&pl.organism.peer_rss>0)S.sR=+pl.organism.peer_rss;
    psh(R.s,S.sR);
    const tb=(ph.tx_bytes||0)+(ph.rx_bytes||0),now=performance.now();if(S.lt&&tb>=S.lb)S.rk=M.round((tb-S.lb)/1024/mx(.2,(now-S.lt)/1e3));S.lb=tb;S.lt=now;T('p-rt',`${S.rk} KB/s`);
    if(p.latest_event)T('te',`${p.latest_event.ts_local} ${p.latest_event.message}`);
    if(tr){S.tr=tr;S.ks=!!tr.kill_switch;T('p-gov',S.wR<80&&S.sR<80?'LAW7 OK':'RSS WARN');const b=$('b-ks');b.textContent=S.ks?'HALTED':'ROI Guard';b.className=S.ks?'act':'';}
    if(pl){
      if(pl.organism)S.org=pl.organism;
      if(pl.prism)S.prm=pl.prism;
      S.hd=pl.hyper_desk||{};S.th=pl.thermo||{};S.om=pl.omega||{};
      S.cpu=+(pl.host_cpu_pct??S.th.cpu_pct??S.cpu);S.watts=+(S.th.watts??S.watts);
      if(pl.host_free_ram_gb!=null)S.wFree=+pl.host_free_ram_gb;
      if(pl.gpu_temp_c!=null)S.gt=+pl.gpu_temp_c;if(pl.gpu_util_pct!=null)S.gu=+pl.gpu_util_pct;
      S.vf=+pl.vram_free_mb||S.vf;S.vt=+pl.vram_total_mb||S.vt;S.cu=+pl.colab_cu||S.cu;S.cm=String(pl.colab_mode||'AUTO:SLEEP');
      S.oaiM=+pl.openai_models_count||S.oaiM;S.apps=pl.apps_online||[];
      S.eh=pl.egress_hit_pct||0;S.egR=pl.egress_requests||0;S.dlp=pl.egress_dlp_blocked||0;S.bb=pl.blackbox_frames||0;S.vdb=pl.vault_sql_dbs||0;S.ij=pl.immortal_jobs||0;
      T('p-cu',`${S.cu|0} CU`);T('tt2',`Pain ${(S.org.pain||0).toFixed(2)} · ${S.org.sync_cnt||0} sync`);
      if(pl.cartridges){
        S.ct=pl.cartridges;const en=Object.entries(pl.cartridges);
        $('c-ch').innerHTML=en.map(([k,v])=>{const[desc,og]=CD[k]||['Substrate module','win'];return`<div class="cc ${v?'':'off'} ${S.foc===og?'hi':''}" data-org="${og}" onclick="togC('${E(k)}')"><div class="cn"><span>${E(k.replace(/_(entity|membrane|pareto)/,''))}</span><span class="${v?'ok':'er'}">${v?'ON':'OFF'}</span></div><div class="cd">${E(desc)}</div></div>`;}).join('');
      }
      const o=S.org||{},pm=S.prm||{},act=[o.alive?.86:.2,o.sync_cnt?.88:clm(.3+S.rk/40,.2,.85),clm(.35+mn(.55,S.egR*.005+(o.ws_items||0)*.05),.2,.92),pm.hit_pct!=null?clm(pm.hit_pct/100,.25,.98):.68,clm(.28+S.cpu/140+S.gu/180,.18,.9)];
      R.ht.forEach((row,i)=>psh(row,act[i]));
      psh(R.ph,{x:clm((S.cpu+S.gu*.6)/150,.06,.94),y:clm((S.gt-35)/50,.06,.94)});
    }
    if(p.flows)renFl(p.flows,0);
    renKPIs();drawTopo();drawCharts();
    if(!S.foc&&S.fl[S.si]){const c=S.fl[S.si];T('ins-title',`LIVE SIGNAL #${c.id} · ${c.op} (${c.src} ──► ${c.dst})`);T('ins-sub',`${c.detail||'rpc'} • ${c.bytes||0} B • ${c.ms} ms • ${c.ts}`);}
    if(p.status_etag&&p.status_etag!==_et)await refresh();
  }catch(_){}finally{_pB=0;}
}
function sched(){pulse().finally(()=>setTimeout(sched,_bl?2500:1000));}
async function refresh(){try{const r=await fetch('/api/status',{headers:_et?{'If-None-Match':_et}:{}});if(r.status===304||!r.ok)return;_et=r.headers.get('ETag')||_et;const j=await r.json();upB(j.zero_weight,(j.phantom||{}).client,1);}catch(_){}}
window.onresize=()=>{drawCharts();};window.onblur=()=>_bl=1;window.onfocus=()=>{_bl=0;pulse();};
document.onvisibilitychange=()=>{if(!document.hidden)pulse();};
window.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K'||e.code==='Space')){e.preventDefault();$('spotlight-modal').classList.contains('open')?cPal():oPal();return;}if(e.key==='Escape')return cPal();if(e.key==='Tab'){e.preventDefault();return tac();}if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;const k={'1':'organs','2':'carts','3':'ops','0':'hyperdrive','x':'galactic','X':'galactic'}[e.key];if(k)selSec(k);};
$('fl-bar').innerHTML=[['all','Tất cả'],['sync','Sync/Brain'],['apps','Apps'],['egress','Egress'],['compute','Compute']].map(([k,l])=>`<button class="flt ${k==='all'?'active':''}" data-f="${k}" onclick="setFlt('${k}')">${l}</button>`).join('');
$('s-tb').innerHTML=[['organs','[1] Organs'],['carts','[2] Carts'],['ops','[3] Ops'],['hyperdrive','[0] v9'],['galactic','[X] v12']].map(([k,l])=>`<button class="tab ${k==='organs'?'active':''}" data-id="${k}" onclick="selSec('${k}')">${l}</button>`).join('');
$('ac-h').innerHTML=bt([['Bench v9',"runB('/api/hyperdrive/benchmark')"],['Status',"rq('/api/hyperdrive/status')"],['Reconnect PHANTOM',"act('ph')"]],'xs');
$('ac-g').innerHTML=bt([['Bench All 29',"bW('all')"],['v10',"bW('v10')"],['v11',"bW('v11')"],['v12',"bW('v12')"],['CHMC',"act('chmc')"]],'xs');
$('ac-o').innerHTML=bt([['2-Way Sync ⇄',"act('sync2')"],['Run Dream',"act('dream')"],['Epiphany',"act('epiph')"],['Autopoiesis',"act('autop')"],['Panopticon',"act('pano')"],['Deploy Gate',"act('gate')"],['Synesthesia',"act('synes')"],['Precog→SVH',"act('precog')"],['SHA Scout',"act('scout')"],['Subconscious',"act('subc')"],['Freeze 60s',"act('freeze')"]],'xs');
$('t-act').innerHTML=bt([['Sync ⇄',"act('sync2')"],['Dream',"act('dream')"],['AutoP',"act('autop')"],['Gate',"act('gate')"],['Synes',"act('synes')"]])+'<button class="pri" onclick="tac()">Full UI</button>';
$('t-gr').innerHTML=[['WIN SOMA','tz','in'],['SVHOME TWIN','tp','ok'],['NOOSPHERE','tt2','tl'],['LATEST WIRE','te','wn']].map(([l,i,c])=>`<div class="tb2"><small class="mu">${l}</small><div id="${i}" class="mono ${c}">--</div></div>`).join('');
if(window.__INIT_STATE__)upB(window.__INIT_STATE__.zero_weight,(window.__INIT_STATE__.phantom||{}).client,1);else refresh();
renKPIs();drawTopo();drawCharts();setTimeout(sched,80);
</script>
</body>
</html>
"""


def _deflate_raw_b64(text: str, strip_indent: bool = False) -> str:
    if strip_indent:
        text = "\n".join(line.lstrip(" ") for line in text.splitlines())
    comp = zlib.compressobj(level=9, wbits=-zlib.MAX_WBITS)
    return base64.b64encode(comp.compress(text.encode("utf-8")) + comp.flush()).decode("ascii")


_RAW_DEFLATE_B64 = _deflate_raw_b64(UNIVERSE_DASHBOARD_HTML, strip_indent=True)


def build_kolmogorov_packed_html(init_state_json: str = "null", etag_json: str = '""') -> bytes:
    """Emit self-unpacking DecompressionStream('deflate-raw') capsule."""
    s_b64 = _deflate_raw_b64(init_state_json)
    boot = (
        "<!doctype html><meta charset=utf-8><title>CHIMERA v27</title>"
        "<body style=margin:0;background:#070b14;color:#2dd4bf;font:12px/1 monospace;padding:12px>"
        "<!-- CHIMERA-HYPER v2.0 -->CHIMERA LIVING ORGANISM v27...<script>"
        "const _u=x=>new Response(new Blob([Uint8Array.from(atob(x),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();"
        f"(async()=>{{const[h,s]=await Promise.all([_u('{_RAW_DEFLATE_B64}'),_u('{s_b64}')]);"
        f"document.open();document.write(h.replace('/*__INIT_STATE__*/null',()=>s).replace('/*__INIT_ETAG__*/\"\"',()=>JSON.stringify({etag_json})));document.close()}})();</script>"
    )
    return boot.encode("utf-8")

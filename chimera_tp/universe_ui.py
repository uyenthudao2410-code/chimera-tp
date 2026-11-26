"""CHIMERA-HYPER v24.0 OMNISCIENCE — Hyper-Organic Spatial Intelligence HUD (<20KB Gzip)."""

from __future__ import annotations

import base64
import zlib

UNIVERSE_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA // OMNISCIENCE v24 — CHIMERA-HYPER v12.0 OMEGA-GALACTIC</title>
<style>
:root{--fg:#e8f4ff;--mu:#6f8db0;--cy:#00f0ff;--gr:#00ffaa;--am:#ffb830;--vi:#b47cff;--rd:#ff4d79;--bd:rgba(0,240,255,.26);--m:ui-monospace,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#02050c;color:var(--fg);font:10.5px/1.3 var(--m);font-variant-numeric:tabular-nums}
body.tactical #stage{display:none!important}body.tactical #tactical-deck{display:flex}body.tactical{background:#020806;color:#bbf7d0;--cy:#00ffaa;--bd:rgba(0,255,170,.35)}
.mu{color:var(--mu)}.ok{color:var(--gr)}.wn{color:var(--am)}.er{color:var(--rd)}.in{color:var(--cy)}.vi{color:var(--vi)}.cv{width:100%;display:block}
#stage,#gl,#mesh-svg,#sat-layer,#hud{position:absolute;inset:0}#stage{position:fixed;overflow:hidden;background:radial-gradient(circle at 50% 50%,rgba(0,85,150,.24),rgba(40,12,88,.12) 44%,#02050c 78%)}
#stage::before{content:"";position:absolute;inset:0;background:radial-gradient(rgba(0,240,255,.11) 1px,transparent 1px) 0 0/34px 34px;mask-image:radial-gradient(circle,#000 18%,transparent 76%);pointer-events:none;z-index:1}
#gl{width:100%;height:100%;display:block;cursor:grab;z-index:2}#mesh-svg{width:100%;height:100%;pointer-events:none;z-index:5;overflow:visible}#sat-layer{pointer-events:none;z-index:6}
.sat{position:absolute;transform:translate(-50%,-50%);pointer-events:auto;cursor:pointer;display:flex;align-items:center;gap:6px;padding:3px 9px 3px 6px;border-radius:999px;background:rgba(3,10,24,.92);border:1px solid var(--sc);box-shadow:0 0 14px -4px var(--sc);transition:transform .18s}
.sat:hover,.sat.on{transform:translate(-50%,-50%) scale(1.12);box-shadow:0 0 22px -2px var(--sc)}.sat i,.pn i,.wt i,.cc i{border-radius:50%;display:inline-block}
.sat i{width:7px;height:7px;background:var(--sc);box-shadow:0 0 10px var(--sc)}.sat b{font-size:8.6px;letter-spacing:.08em;color:#fff}.sat small{font-size:7.5px;color:var(--sc)}
#hud{pointer-events:none;z-index:10;display:grid;grid-template-rows:46px 1fr 82px;padding:10px 14px;gap:8px}
.glass{pointer-events:auto;background:rgba(4,12,26,.84);border:1px solid var(--bd);position:relative;transition:opacity .22s,border-color .18s,box-shadow .18s}
.cham{clip-path:polygon(12px 0,100% 0,100% calc(100% - 12px),calc(100% - 12px) 100%,0 100%,0 12px)}
.glass::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(135deg,rgba(0,240,255,.1),transparent 28%,transparent 72%,rgba(180,124,255,.08))}
.glass.dim{opacity:.3}.glass.linked{border-color:var(--lk,var(--cy))!important;box-shadow:0 0 28px -5px var(--lk,var(--cy)),inset 0 0 20px -12px var(--lk,var(--cy));opacity:1!important}
.r,.sbw,.wh,.tbs{display:flex;align-items:center;gap:5px}.sbw,.wh{justify-content:space-between}
#top{display:flex;align-items:center;justify-content:space-between;padding:0 12px;gap:10px;border-radius:8px}
.em{width:28px;height:28px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#00f0ff,#0a2b6e 72%);border:1px solid var(--cy);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;box-shadow:0 0 16px rgba(0,240,255,.55);position:relative;flex-shrink:0}
.em::after{content:"";position:absolute;inset:-4px;border-radius:50%;border:1px dashed rgba(0,240,255,.55);animation:spn 14s linear infinite}@keyframes spn{to{transform:rotate(360deg)}}
.pp{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;background:rgba(0,255,170,.09);border:1px solid rgba(0,255,170,.45);color:var(--gr);font-size:8.3px;font-weight:800;white-space:nowrap}
.dot{width:6px;height:6px;border-radius:50%;background:var(--gr);box-shadow:0 0 10px var(--gr);transition:transform .12s}.dot.hit{transform:scale(1.8);background:#fff}
#pipe{display:flex;align-items:center;gap:4px;overflow:hidden}.pn{display:flex;align-items:center;gap:5px;padding:3px 8px;border-radius:999px;border:1px solid rgba(0,240,255,.22);background:rgba(4,14,32,.78);cursor:pointer;font-size:8.3px;font-weight:700;white-space:nowrap}
.pn:hover,.pn.on{border-color:var(--pc);background:rgba(0,240,255,.16);color:#fff;box-shadow:0 0 14px -3px var(--pc)}.pn i{width:5px;height:5px;background:var(--pc);box-shadow:0 0 7px var(--pc)}.pa{color:rgba(0,240,255,.55);font-size:8px}
button,input{font:700 8.4px var(--m);color:var(--fg);background:rgba(7,18,38,.86);border:1px solid var(--bd);border-radius:4px;padding:3px 6.5px;outline:none}
button{cursor:pointer}button:hover,.tab.active,.cb button.on{border-color:var(--cy);background:rgba(0,240,255,.2);color:#fff}button.pri{background:linear-gradient(135deg,#0891b2,#2563eb);border-color:var(--cy);color:#fff}button.act{border-color:var(--am);color:var(--am)}button.xs,.tab{padding:2px 5px;font-size:7.9px}
#arena{display:grid;grid-template-columns:346px 1fr 358px;grid-template-rows:1fr 1fr;gap:12px;min-height:0}
#w-win{grid-column:1;grid-row:1}#w-sv{grid-column:1;grid-row:2}#w-gpu{grid-column:3;grid-row:1}#w-cmd{grid-column:3;grid-row:2}
#center-hud{grid-column:2;grid-row:1/3;pointer-events:none;display:flex;flex-direction:column;justify-content:space-between;align-items:center;padding:4px 0}
.cb{pointer-events:auto;display:flex;gap:4px;padding:3px 6px;border-radius:999px;background:rgba(3,10,24,.76);border:1px solid var(--bd)}
#causal-banner{pointer-events:auto;max-width:560px;text-align:center;padding:6px 14px;border-radius:999px;background:rgba(3,10,24,.92);border:1px solid rgba(0,240,255,.36);box-shadow:0 0 20px -8px rgba(0,240,255,.45)}
.wing{padding:8px 11px;display:flex;flex-direction:column;justify-content:space-between;min-height:0;overflow:hidden}
.wh{padding-bottom:4px;margin-bottom:5px;border-bottom:1px solid rgba(0,240,255,.16)}.wt{font-size:8.6px;font-weight:800;letter-spacing:.1em;display:flex;align-items:center;gap:6px;color:#fff}.wt i{width:6px;height:6px;background:currentColor;box-shadow:0 0 8px currentColor}
.tag{font-size:7.8px;font-weight:700;padding:1.5px 6px;border-radius:999px;border:1px solid var(--bd);color:var(--cy)}
.rings,.mgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:2px 0 4px}
.rg{display:flex;flex-direction:column;align-items:center;padding:4px 2px;border-radius:6px;background:rgba(3,10,22,.56);border:1px solid rgba(0,240,255,.12);cursor:pointer}
.rg:hover,.rg.hi{border-color:var(--cy);background:rgba(0,240,255,.1)}.rg svg{width:62px;height:62px;overflow:visible}.rg-bg{fill:none;stroke:rgba(255,255,255,.08);stroke-width:5}.rg-fg{fill:none;stroke-width:5;stroke-linecap:round;transform:rotate(-90deg);transform-origin:32px 32px;transition:stroke-dashoffset .4s ease}
.rg-v{font-size:10.5px;font-weight:800;fill:#fff;text-anchor:middle}.rg-u{font-size:6.8px;fill:var(--mu);text-anchor:middle}.rg-l{font-size:7.5px;color:#b8d4f0;letter-spacing:.05em;margin-top:2px;font-weight:700}.rg-s{font-size:7.2px;color:var(--mu)}
.mc{padding:4px 6px;border-radius:5px;background:rgba(3,10,22,.6);border:1px solid rgba(0,240,255,.12)}.mc small{display:block;font-size:7.1px;color:var(--mu);letter-spacing:.05em}.mc b{font-size:10px}
#flow-feed{display:flex;flex-direction:column;gap:4px;overflow-y:auto;flex:1;min-height:0}
.fl{padding:4.5px 7px;border-radius:4px;border:1px solid rgba(0,240,255,.16);border-left:3px solid var(--cy);background:rgba(4,12,26,.76);cursor:pointer}.fl:hover,.fl.sel{border-color:var(--am);background:rgba(255,184,48,.09)}
.fl.compute{border-left-color:var(--am)}.fl.crypto{border-left-color:var(--vi)}.fl.tarpit{border-left-color:var(--rd)}.fl.phantom{border-left-color:var(--gr)}.fb{font-size:7.6px;font-weight:800;padding:1px 4px;border-radius:3px;border:1px solid currentColor}
.tbs{flex-wrap:wrap;margin-bottom:4px}.dpn{display:none;flex:1;min-height:0;overflow:auto}.dpn.active{display:flex;flex-direction:column;gap:4px}
.out{background:rgba(2,6,14,.85);border:1px solid rgba(0,240,255,.18);border-radius:4px;padding:4px 6px;font-size:8px;color:#b8ffe3;max-height:52px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.tbl{width:100%;border-collapse:collapse;font-size:8px}.tbl th,.tbl td{text-align:left;padding:2px 4px;border-bottom:1px solid rgba(0,240,255,.14)}
#dock{display:grid;grid-template-columns:232px 1fr 224px;align-items:center;gap:10px;padding:6px 12px;border-radius:8px}
#c-ch{display:flex;flex-wrap:wrap;gap:4px;justify-content:center}
.cc{display:inline-flex;align-items:center;gap:4px;font-size:7.7px;font-weight:700;padding:2.5px 6px;border-radius:999px;border:1px solid rgba(0,255,170,.35);background:rgba(0,255,170,.08);color:#c4ffe8;cursor:pointer}
.cc i{width:4.5px;height:4.5px;background:var(--gr);box-shadow:0 0 6px var(--gr)}.cc.off{border-color:rgba(255,77,121,.4);background:rgba(255,77,121,.1);color:var(--rd);opacity:.7}.cc.off i{background:var(--rd);box-shadow:none}
.cc:hover,.cc.hi{border-color:#fff;background:rgba(0,240,255,.26);color:#fff;box-shadow:0 0 12px rgba(0,240,255,.5)}
#spotlight-modal{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:72px;background:rgba(2,5,12,.88)}#spotlight-modal.open{display:flex}
.pc{width:min(580px,92vw);background:#050f22;border:1px solid var(--cy);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}
#tactical-deck{position:fixed;inset:10px;z-index:30;display:none;flex-direction:column;gap:8px;overflow:auto;padding:14px;background:#020907;border:1px solid var(--bd);border-radius:10px}#tactical-deck svg text{text-anchor:middle;font-size:10px;fill:#e2e8f0}
.tg2{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.tb2{border:1px solid var(--bd);border-radius:6px;padding:8px;background:#040e0a}
@media(max-width:1180px){html,body{overflow:auto}#stage{position:relative;min-height:100vh}#hud{position:relative;grid-template-rows:auto auto auto}#arena{grid-template-columns:1fr;grid-template-rows:auto}#w-win,#w-sv,#w-gpu,#w-cmd,#center-hud{grid-column:1;grid-row:auto}#center-hud{min-height:280px}#dock{grid-template-columns:1fr}#mesh-svg,#sat-layer{display:none}}
</style>
</head>
<body>
<!-- CHIMERA-HYPER v2.0 / v12.0 OMEGA-GALACTIC / OMNISCIENCE v24 -->
<div id="stage">
<canvas id="gl"></canvas><svg id="mesh-svg"></svg><div id="sat-layer"></div>
<div id="hud">
  <header id="top" class="glass">
    <div class="r" style="gap:9px"><div class="em">CH</div><div><div style="font-weight:900;font-size:11.6px;letter-spacing:.1em;color:#fff">CHIMERA // OMNISCIENCE v24</div><div class="mu" style="font-size:7.7px;letter-spacing:.06em">HYPER-ORGANIC INFRASTRUCTURE INTELLIGENCE</div></div><span class="pp"><span class="dot" id="hb-dot"></span><span id="hb-lbl">SYNC · #0</span></span><canvas id="c-ecg" style="width:90px;height:22px;display:block"></canvas></div>
    <nav id="pipe"></nav>
    <div class="r"><span class="tag ok" id="p-fps">60 FPS</span><button id="b-ks" onclick="act('ks')">ROI</button><button onclick="pip()">PiP</button><button id="b-tac" onclick="tac()">0-GPU</button><button id="b-son" onclick="tSon()">Sonic</button><button class="pri" onclick="oPal()">Ctrl+K</button></div>
  </header>
  <main id="arena">
    <section id="w-win" class="wing glass cham" data-org="win">
      <div><div class="wh"><span class="wt in"><i></i>01 // WIN-DESKTOP · SILICON</span><span class="tag ok" id="p-gov">ACTIVE</span></div><div id="sil-list" class="rings"></div><div class="mgrid"><div class="mc"><small>HYPERDESK</small><b class="ok" id="hd-gb">+0.00 GB</b></div><div class="mc"><small>CRYO / WALL</small><b class="in" id="hd-cw">0 / 0</b></div><div class="mc"><small>ZERO-WEIGHT</small><b class="in" id="w-ram">--/80MB</b></div></div></div>
      <div><canvas id="c-bow" class="cv" style="height:60px"></canvas><div class="sbw" style="margin-top:4px"><span class="mu" style="font-size:7.5px">WIN ⇄ SVHOME RAM EQUILIBRIUM</span><div class="r"><button class="xs" onclick="act('cryo')">Cryo</button><button class="xs" onclick="act('thaw')">Thaw</button><button class="xs" onclick="act('wall')">Wall</button></div></div></div>
    </section>
    <section id="w-sv" class="wing glass cham" data-org="sv">
      <div><div class="wh"><span class="wt ok"><i></i>03 // PHANTOM-5MS · SVHOME HUB</span><span class="tag ok" id="p-tun">-- ms</span></div><div id="sv-rings" class="rings"></div></div>
      <div><canvas id="c-kal" class="cv" style="height:90px"></canvas><div class="sbw" style="margin-top:4px"><span class="mu" style="font-size:7.5px">APPS: <b class="ok" id="p-pl">--</b> • <b class="vi" id="oai-m">UNIFY</b></span><span class="in" style="font-size:7.8px" id="p-rt">0 KB/s</span></div></div>
    </section>
    <div id="center-hud">
      <div class="cb" id="cam-b"></div>
      <div id="causal-banner"><div class="in" style="font-size:8.9px;font-weight:800;letter-spacing:.06em" id="an-o">LIVING ENTITY SYNCHRONIZED • 10,620 VSA VECTORS</div><div class="mu" style="font-size:7.9px;margin-top:1px" id="an-s">Hover Organ / Satellite / Cartridge để khóa mạch thần kinh &amp; xem kết nối thực</div></div>
    </div>
    <section id="w-gpu" class="wing glass cham" data-org="gpu">
      <div><div class="wh"><span class="wt vi"><i></i>02 // COLAB ELASTIC · GPU THERMO</span><span class="tag vi" id="p-cu">2350CU</span></div><div id="gpu-rings" class="rings"></div><div class="mgrid"><div class="mc"><small>REGIME</small><b class="ok" id="th-r">COOL</b></div><div class="mc"><small>GENOME</small><b class="wn" id="om-g">lz4_simd</b></div><div class="mc"><small>POWER</small><b class="wn" id="p-thm">0W</b></div></div></div>
      <div><canvas id="c-ph" class="cv" style="height:68px"></canvas><div class="sbw" style="margin-top:4px"><span class="mu" style="font-size:7.5px">THERMO PHASE ATTRACTOR</span><div class="r"><button class="xs" id="b-thm" onclick="cycThm()">CAP 99%</button><button class="xs" onclick="act('ptx')">PTX 65K</button><button class="xs" onclick="act('emb')">Embed</button><button class="xs" onclick="act('ctrlz')">Ctrl+Z</button></div></div></div>
    </section>
    <section id="w-cmd" class="wing glass cham" data-org="core">
      <div class="wh"><span class="wt wn"><i></i>04 // CAUSAL NERVE STREAM &amp; OPS</span><span class="tag ok" id="w-ct">LIVE</span></div>
      <div class="tbs" id="s-tb"></div>
      <div id="pane-wire" class="dpn active"><div id="flow-feed">Synchronizing neural stream...</div></div>
      <div id="pane-hyperdrive" class="dpn"><span class="mu">v9.0 HYPERDRIVE</span><div class="r" id="ac-hyp"></div></div>
      <div id="pane-galactic" class="dpn"><span class="mu">v12.0 OMEGA-GALACTIC (29 Ideas)</span><div class="r" id="ac-gal"></div><div id="h-tbl" style="flex:1;overflow:auto"></div></div>
      <div id="pane-ops" class="dpn"><div class="r" id="ac-ops"></div><div id="t-lg" style="font-size:8px;overflow:auto;flex:1"></div></div>
      <div class="out" id="h-out">OMNISCIENCE v24 • Eco-Cortex 1-24FPS + Cryo-Silicon 99% cap.</div>
    </section>
  </main>
  <footer id="dock" class="glass">
    <div><div class="sbw"><span class="in" style="font-size:7.9px;font-weight:800;letter-spacing:.07em">NEURAL ACTIVITY</span><span class="ok" style="font-size:7.8px" id="c-cnt">15/15 ON</span></div><canvas id="c-ht" class="cv" style="height:52px"></canvas></div>
    <div id="c-ch"></div>
    <div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end"><div class="r" id="q-act"></div><div class="mu" style="font-size:7.5px" id="v-pl">VSA 100% COHERENT</div></div>
  </footer>
</div>
</div>
<section id="tactical-deck"><div class="sbw" style="border-bottom:1px solid var(--bd);padding-bottom:6px"><b>CHIMERA // 0-GPU TACTICAL</b><div class="r" id="t-act"></div></div><svg viewBox="0 0 880 72" style="width:100%;height:72px;border:1px solid var(--bd);border-radius:8px;background:#020705"><rect x="16" y="8" width="160" height="56" rx="8" fill="#06141a" stroke="#00f0ff"/><text x="96" y="30" fill="#7dd3fc">WIN</text><text id="sw" x="96" y="48">--</text><line x1="176" y1="36" x2="704" y2="36" stroke="#ffb830" stroke-width="2" stroke-dasharray="6 4"/><circle cx="440" cy="36" r="18" fill="#091529" stroke="#ffb830" stroke-width="2"/><text x="440" y="40" fill="#ffb830">VSA</text><text id="st" x="440" y="13" fill="#00f0ff">PHANTOM</text><rect x="704" y="8" width="160" height="56" rx="8" fill="#061a14" stroke="#00ffaa"/><text x="784" y="30" fill="#00ffaa">SVHOME</text><text id="ss" x="784" y="48">--</text></svg><div class="tg2" id="t-grid"></div><div class="out" id="t-out" style="max-height:200px">--</div></section>
<div id="spotlight-modal" onclick="if(event.target===this)cPal()"><div class="pc"><div class="sbw"><span class="in" style="font-weight:800">Spotlight (Ctrl+K)</span><button onclick="cPal()">ESC</button></div><div class="r"><input id="spotlight-input" style="flex:1" placeholder="Symbol / cryo / ptx / emb / teleport / frost / vsa / tarpit / bench / zero-gpu" onkeydown="if(event.key==='Enter')xPal()"><button class="pri" onclick="xPal()">Run</button></div><div class="out" id="spotlight-out" style="max-height:200px">Cluster search &lt;5ms.</div></div></div>
<script>
window.__INIT_STATE__=/*__INIT_STATE__*/null;let _et=/*__INIT_ETAG__*/"";
const $=i=>document.getElementById(i),Q=s=>document.querySelectorAll(s),T=(i,v)=>{const e=$(i);if(e)e.textContent=v;},E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),M=Math,cs=M.cos,sn=M.sin,mn=M.min,mx=M.max,psh=(a,v)=>{a.push(v);a.shift();},clm=(v,a,b)=>mx(a,mn(b,v)),bt=(a,c)=>a.map(([l,f])=>`<button${c?' class="'+c+'"':''} onclick="${f}">${l}</button>`).join('');
const O={win:['#00f0ff',2.55,'w-win','WIN-SILICON','AVX-512 • HyperDesk','WIN ──► HyperDesk Cryo/Wall + Governor ──► VSA-10K Core (<80MB)'],gpu:['#b47cff',.58,'w-gpu','COLAB-T4','Elastic CUDA Burst','GTX1650 Thermo ──► 4-Tier Pareto Router ──► Headless Colab T4 (0% Win GPU)'],sv:['#00ffaa',3.72,'w-sv','SVHOME-HUB','PHANTOM • AVX2','PHANTOM-5MS (Kalman RTT) ⇄ svhome AVX2 ⇄ Egress DLP + OpenAI Unify + Apps'],core:['#ffb830',5.7,'w-cmd','VSA-CORTEX','Causal Synapse','VSA-10K Holographic Core ⇄ 15 Hot Cartridges ⇄ WASM Teleport + FROST 2/3']};
const CO={egress_membrane:'sv',pulse:'sv',immortal_jobs:'sv',zygote_canary:'sv',vault_sql:'sv',vgpu_pareto:'gpu',cosmos_entity:'gpu',browser_grid:'win',hyper_desk:'win'};
const CD={connect:'Discovery Beacon (:9780)',egress_membrane:'DLP Shield + UCB1 Egress Cache',pulse:'Cross-Host PubSub + KV Bus',hybrid_search:'<5ms Semantic + Symbol Search',blackbox:'Zero-Disk 60s Flight Recorder',diskless_secrets:'RAM-Only Ephemeral Vault',vgpu_pareto:'4-Tier Elastic GPU Router (Local ↔ Colab T4)',immortal_jobs:'Self-Healing Distributed Jobs',browser_grid:'Headless Browser Grid',zygote_canary:'<10ms Pre-Forked Worker Pool',vault_sql:'Replicated SQLite Mesh',ghost_bubble:'Dry-Run Sandbox (Commit/Discard)',hyper_desk:'Cryo Reclaim + Silicon Wall',cosmos_entity:'Thermal Phase + Autopoietic Optimizer',omega_entity:'Self-Evolving Genome + Ctrl+Z'};
const P1='/v1/hyperdesk/',P2='/api/galactic/',A={opt:[P1+'optimize','DESK'],cryo:[P1+'cryo','CRYO'],thaw:[P1+'thaw','THAW'],wall:[P1+'silicon-wall','WALL'],ptx:['/v1/vgpu/ptx-bench','PTX',{n:65536,force:true}],emb:['/v1/openai/v1/embeddings','EMBED',{input:['hosi'],dimensions:128}],teleport:[P2+'live-teleport','TELEPORT'],frost:[P2+'live-frost','FROST'],vsa:[P2+'vsa-query','VSA',{trials:100,corrupt_pct:.4}],chmc:[P2+'live-chmc','CHMC'],freeze:['/v1/blackbox/freeze','FREEZE'],ctrlz:['/v1/omega/multiverse/ctrl-z','CTRLZ'],ph:['/api/phantom/connect','PHANTOM']};
const SH=[`precision highp float;attribute vec3 aP,aM;uniform vec2 uR;uniform float uT,uZ,uA,uS,uW,uG,uB;varying float vA,vK,vH,vW;mat2 rt(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}void main(){vec3 p=aP;if(aM.y<2.5)p*=1.+uB*.055+.016*sin(uT*2.2+aM.x*3.)*(1.+uS);else if(aM.y>3.5){p.xy*=rt(uT*(aM.y>4.5?-.24:.18));p.xz*=rt(sin(uT*.4)*.28);}vH=exp(-pow((length(p.xy)-.72)*2.2,2.));p.xz*=rt(uR.x);p.yz*=rt(uR.y);p.z-=uZ;float d=max(.45,-p.z);gl_Position=vec4(p.x/(d*.55*uA),p.y/(d*.55),clamp(-p.z/16.,-1.,1.),1.);vW=exp(-pow(mod(aM.x-uW+6.283,6.283)-3.14,2.)*3.)*uG;vA=aM.z*(.38+.62*clamp((p.z+uZ+1.8)/3.6,0.,1.))*(1.+uS*.5+vW*1.4+uB*.36);vK=aM.y;}`,`precision highp float;uniform float uTl,uFr,uTp,uTh;varying float vA,vK,vH,vW;void main(){vec3 c=vK<.5?vec3(0.,.94,1.):vK<1.5?vec3(.78,.96,1.):vK<2.5?vec3(0.,1.,.66):vK<3.5?vec3(.71,.49,1.):vK<4.5?vec3(.08,.76,1.):vec3(1.,.72,.2);c=mix(c,vec3(1.,.48,.18),clamp(uTh,0.,.55));c=mix(c,vec3(.96,1.,1.),clamp(vH*.48+vW*.52,0.,.88));if(uTl>.02)c=mix(c,vec3(1.,.78,.2),uTl*.58);if(uFr>.02)c=mix(c,vec3(.72,.5,1.),uFr*.62);if(uTp>.02)c=mix(c,vec3(1.,.3,.48),uTp*.65);gl_FragColor=vec4(c,clamp(vA,.04,.95));}`,`precision highp float;attribute vec3 aB,aRn;attribute float aD,aK;uniform vec2 uR;uniform float uT,uSh,uZ,uA,uS,uB;varying float vD,vSh,vK,vDp;mat2 rt(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}void main(){vec3 p=aB;if(aK<.5){p=aB*(1.+uB*.04+.022*sin(uT*2.+aRn.x*6.28))+aRn*(aD*1.35+uSh*2.2);p.xy*=rt(uT*.09);}else if(aK>1.5){float u=aB.x+uT*(.55+uS*.85)*aB.y,v=aB.z+u*2.6,r=.48+.1*sin(v*2.+uT*1.4);p=vec3((1.05+r*cos(v))*cos(u),(1.05+r*cos(v))*sin(u),r*sin(v));}else p*=1.+uB*.065;p.xz*=rt(uR.x);p.yz*=rt(uR.y);p.z-=uZ;float d=max(.45,-p.z);gl_Position=vec4(p.x/(d*.55*uA),p.y/(d*.55),clamp(-p.z/16.,-1.,1.),1.);gl_PointSize=aK<.5?max(1.3,3.5/d):(aK<1.5?max(2.8,7.4/d):max(3.4,8.6/d));vD=aD;vSh=uSh;vK=aK;vDp=clamp((p.z+uZ+1.8)/3.6,.18,1.);}`,`precision highp float;varying float vD,vSh,vK,vDp;void main(){vec2 c=gl_PointCoord*2.-1.;float r2=dot(c,c);if(r2>1.)discard;vec3 col=vK<.5?mix(mix(vec3(.08,.92,1.),vec3(1.,.3,.48),clamp(vD,0.,1.)),vec3(.25,.3,.38),clamp(vSh,0.,1.)):vK<1.5?vec3(.96,1.,1.):vK<2.5?vec3(1.,.76,.22):vK<3.5?vec3(0.,1.,.68):vec3(.74,.52,1.);gl_FragColor=vec4(col,exp(-r2*3.4)*(vK<.5?max(.18,.82-vSh*.55):.98)*vDp);}`];
const S={tac:0,son:0,yw:.28,pt:.24,tY:.28,tP:.24,zm:4.35,tZ:4.35,mx:0,my:0,sp:.28,tl:0,fr:0,tp:0,sh:0,hb:0,hbS:0,lb:0,lt:0,rk:0,lf:0,fl:[],si:0,pr:null,ok:0,raf:0,dr:0,lx:0,ly:0,ks:0,wR:32,sR:56,dWR:32,dSR:56,rtt:7.2,kx:7.2,kp:1.6,kk:.42,th:{cpu_pct:18,watts:45},eh:0,egR:0,dlp:0,gt:49,gu:8,vf:2048,vt:4096,cu:2350,cm:'AUTO:SLEEP',oaiM:3,uni:0,apps:[],ct:{},foc:null,bolts:[],syncMs:0};
const C=window.__CORTEX__={version:'24.0',unified:true,torus:true,living:true,hosi:true,glOk:false,glError:0,shaderCount:4,gpuPaused:false,particles:10620,destroyedPct:0,flowsSeen:0};
const R={w:Array(26).fill(32),s:Array(26).fill(56),ecg:Array(44).fill(0),kr:Array(32).fill(7.2),ke:Array(32).fill(7.2),kk:Array(32).fill(.42),hn:['PHANTOM','COLAB','EGRESS','HYPRDSK','VSA-10K'],ho:['sv','gpu','sv','win','core'],ht:Array.from({length:5},()=>Array(16).fill(.22)),ph:Array.from({length:24},(_,i)=>({x:.22+i*.01,y:.3+sn(i*.3)*.05})),tr:[]};
let ac;const son=f=>{if(S.son)try{ac=ac||new(window.AudioContext||window.webkitAudioContext)();const o=ac.createOscillator(),g=ac.createGain(),t=ac.currentTime;o.frequency.value=f||520;g.gain.setValueAtTime(.02,t);g.gain.exponentialRampToValueAtTime(.0001,t+.1);o.connect(g);g.connect(ac.destination);o.start();o.stop(t+.11);}catch(_){}},tSon=()=>{S.son=!S.son;$('b-son').classList.toggle('act',S.son);son(680);};
const NS=800,SG=12,NP=260,NV=10000,NK=360,RS=72,NL=(NS*SG+NP+4*RS+48)*2,NT=NV+NP+NK,tP=new Float32Array(NL*3),tM=new Float32Array(NL*3),pB=new Float32Array(NT*3),pR=new Float32Array(NT*3),pD=new Float32Array(NT),pK=new Float32Array(NT);
(()=>{let l=0;const rad=1.05,pv=(x,y,z,u,k,a)=>{tP.set([x,y,z],l*3);tM.set([u,k,a],l*3);l++;};for(let i=0;i<NS;i++){const u0=i/NS*6.283,v0=i*7.31%6.283,tw=1.6+i%5*.3,rm=.34+i*19%100*.0022,k=i%4,al=k===1?.32:.23;let px=0,py=0,pz=0,pu=0;for(let s=0;s<=SG;s++){const f=s/SG,u=u0+f*1.42,v=v0+f*tw*1.45,rr=rm+.04*sn(3*u+2*v),x=(rad+rr*cs(v))*cs(u),y=(rad+rr*cs(v))*sn(u),z=rr*sn(v);if(s){pv(px,py,pz,pu,k,al);pv(x,y,z,u,k,al);}px=x;py=y;pz=z;pu=u;}}for(let i=0;i<NP;i++){const u=i/NP*6.283,v=i*2.4%6.283,r0=.48,r1=.74+i*37%100*.0032,x1=(rad+r1*cs(v))*cs(u),y1=(rad+r1*cs(v))*sn(u),z1=r1*sn(v),q=NV+i;pv((rad+r0*cs(v))*cs(u),(rad+r0*cs(v))*sn(u),r0*sn(v),u,1,.32);pv(x1,y1,z1,u,1,.56);pB.set([x1,y1,z1],q*3);pK[q]=1;}[1.56,1.88,2.14,1.72].forEach((rd,r)=>{const tl=r===2?.45:r===3?-.52:0,k=r>1?5:4;for(let s=0;s<RS;s++){const a0=s/RS*6.283,a1=(s+1)/RS*6.283,al=s%3?.16:.46;pv(rd*cs(a0),rd*sn(a0)*cs(tl),rd*sn(a0)*sn(tl),a0,k,al);pv(rd*cs(a1),rd*sn(a1)*cs(tl),rd*sn(a1)*sn(tl),a1,k,al);}});for(let i=0;i<48;i++){const a=i/48*6.283,r0=1.52,r1=i%4?1.58:1.66;pv(r0*cs(a),r0*sn(a),0,a,4,.38);pv(r1*cs(a),r1*sn(a),0,a,4,.38);}for(let i=0;i<NV;i++){const u=i*2.4%6.283,v=(i+.5)/NV*144.5,rm=.42+i%11*.02;pB.set([(rad+rm*cs(v))*cs(u),(rad+rm*cs(v))*sn(u),rm*sn(v)],i*3);pR.set([sn(i*12.99),cs(i*78.23),sn(i*39.42)],i*3);}for(let j=0;j<NK;j++){const i=NV+NP+j;pK[i]=2+j%3;pB.set([j/NK*6.283,(j%2?-1:1)*(.72+j%5*.12),j*1.618%6.283],i*3);}})();
const cv=$('gl'),gl=cv.getContext('webgl',{antialias:true,alpha:true,powerPreference:'low-power'})||cv.getContext('experimental-webgl');
let p1,p2,u1={},u2={},b1,b2,b3,b4,b5,b6,dirty=0;
const mkP=(v,f)=>{const p=gl.createProgram();[[v,gl.VERTEX_SHADER],[f,gl.FRAGMENT_SHADER]].forEach(([s,t])=>{const h=gl.createShader(t);gl.shaderSource(h,s);gl.compileShader(h);gl.attachShader(p,h);});gl.linkProgram(p);return p;},mkB=(d,y)=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,d,y?gl.DYNAMIC_DRAW:gl.STATIC_DRAW);return b;};
function initGL(){if(!gl)return;try{p1=mkP(SH[0],SH[1]);p2=mkP(SH[2],SH[3]);'uR,uT,uZ,uA,uS,uW,uG,uB,uTl,uFr,uTp,uTh'.split(',').forEach(k=>u1[k]=gl.getUniformLocation(p1,k));'uR,uT,uSh,uZ,uA,uS,uB'.split(',').forEach(k=>u2[k]=gl.getUniformLocation(p2,k));b1=mkB(tP);b2=mkB(tM);b3=mkB(pB);b4=mkB(pR);b5=mkB(pD,1);b6=mkB(pK);C.glError=gl.getError();S.ok=C.glOk=true;}catch(e){T('p-fps','GL ERR');}}
function ring(pct,col,val,u,lbl,sub,org){const p=clm(pct,2,100),ci=150.8,off=ci*(1-p/100);return`<div class="rg ${S.foc===org?'hi':''}" data-org="${org}" onclick="fCam('${org}')"><svg viewBox="0 0 64 64"><circle class="rg-bg" cx="32" cy="32" r="24"/><circle class="rg-fg" cx="32" cy="32" r="24" stroke="${col}" stroke-dasharray="${ci}" stroke-dashoffset="${off.toFixed(1)}" style="filter:drop-shadow(0 0 5px ${col})"/><text class="rg-v" x="32" y="34">${E(val)}</text><text class="rg-u" x="32" y="44">${E(u)}</text></svg><div class="rg-l">${lbl}</div><div class="rg-s">${E(sub)}</div></div>`;}
function renRings(){
  const cpu=+S.th.cpu_pct||0,vr=S.vt?M.round((S.vt-S.vf)/S.vt*100):0,ramP=S.wR/.8,svP=S.sR/.8,rttP=clm(100-S.kx*1.5,14,98);
  $('sil-list').innerHTML=ring(cpu,'#00f0ff',`${cpu|0}%`,'CPU','WIN CPU',`${S.th.watts||0}W`,'win')+ring(ramP,S.wR>72?'#ff4d79':'#00ffaa',`${S.wR.toFixed(0)}`,'MB/80','DAEMON',`${ramP|0}% cap`,'win')+ring(clm(S.oaiM*5,22,100),'#7dd3fc',`${S.oaiM}`,S.uni?'UNIFY':'LOC','AI MODELS',`${S.apps.length} apps`,'core');
  $('gpu-rings').innerHTML=ring(S.gt/.85,S.gt>70?'#ff4d79':'#ffb830',`${S.gt.toFixed(0)}°`,'TEMP','GTX1650',`${S.gu|0}% load`,'gpu')+ring(vr,'#00f0ff',`${vr}%`,'VRAM',`${((S.vt-S.vf)/1024).toFixed(1)}G`,'local gpu','gpu')+ring(S.cu/25,'#b47cff',`${S.cu|0}`,'CU',S.cm,'Colab T4','gpu');
  $('sv-rings').innerHTML=ring(svP,S.sR>75?'#ff4d79':'#00ffaa',`${S.sR.toFixed(0)}`,'MB/80','SVHOME',`${svP|0}% cap`,'sv')+ring(rttP,S.kx>40?'#ffb830':'#00f0ff',`${S.kx.toFixed(1)}`,'MS','PHANTOM','Kalman RTT','sv')+ring(clm(S.eh,S.egR?24:10,100),'#b47cff',`${S.eh|0}%`,'CACHE','EGRESS',`${S.dlp} dlp`,'sv');
}
function fOrg(o,custom){
  if(S.foc===o&&!custom&&o)return;S.foc=o;const ov=o&&O[o];
  Q('.wing').forEach(e=>{const hit=!!(ov&&e.id===ov[2]);e.classList.toggle('linked',hit);e.classList.toggle('dim',!!ov&&!hit);if(hit)e.style.setProperty('--lk',ov[0]);});
  Q('.sat,.pn').forEach(e=>e.classList.toggle('on',e.dataset.org===o));Q('.cc,.rg').forEach(e=>e.classList.toggle('hi',!!o&&e.dataset.org===o));
  if(custom){T('an-o',custom[0]);T('an-s',custom[1]);}
  else if(ov){T('an-o',`NEURAL CIRCUIT LOCKED → ${ov[3]}`);T('an-s',ov[5]);}
  else{const c=S.fl[S.si];if(c){T('an-o',`LIVE SIGNAL #${c.id} • ${c.op} (${c.ms}ms)`);T('an-s',`${c.src} ══► VSA-10K CORE ══► ${c.dst} • ${c.detail||'realtime pulse'}`);}else{T('an-o','LIVING ENTITY SYNCHRONIZED • 10,620 VSA VECTORS');T('an-s','Hover Organ / Satellite / Cartridge để khóa mạch thần kinh & xem kết nối thực');}}
}
function spawnBolt(org,col){S.bolts.push({org,col:col||(O[org]&&O[org][0])||'#00f0ff',t:0});if(S.bolts.length>12)S.bolts.shift();}
function upMesh(now){
  const svg=$('mesh-svg'),rS=$('stage').getBoundingClientRect();if(rS.width<920){svg.innerHTML='';return;}
  const cy0=rS.height/2,cy=cs(S.yw),sy=sn(S.yw),cp=cs(S.pt),sp=sn(S.pt),a=rS.width/mx(1,rS.height),pos={},out=[];
  Object.entries(O).forEach(([k,v])=>{
    const u=v[1]+sn(now*.00045)*.08,wx=1.74*cs(u),wy=1.74*sn(u),wz=.26*sn(u*2+now*.0006),x1=wx*cy-wz*sy,z1=wx*sy+wz*cy,dz=mx(.6,-(wy*sp+z1*cp-S.zm));
    const px=clm((.5+.5*x1/(dz*.55*a))*rS.width,374,rS.width-374),py=clm((.5-.5*(wy*cp-z1*sp)/(dz*.55))*rS.height,96,rS.height-114),el=$('sat-'+k);
    if(el){el.style.left=(px|0)+'px';el.style.top=(py|0)+'px';}pos[k]=[px,py,v[0]];
  });
  const bz=(x1,y1,x2,y2,c,op,w,ph,lbl)=>{
    const m1=(x1+x2)/2,m2=(y1+y2)/2+(y2<cy0?-24:24),d=`M${x1|0} ${y1|0}Q${m1|0} ${m2|0} ${x2|0} ${y2|0}`,t=(ph%1+1)%1,i=1-t,bx=i*i*x1+2*i*t*m1+t*t*x2,by=i*i*y1+2*i*t*m2+t*t*y2;
    out.push(`<path d="${d}" fill="none" stroke="${c}" stroke-width="${w+3}" opacity="${(op*.2).toFixed(2)}"/><path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" opacity="${op.toFixed(2)}" stroke-dasharray="6 5" stroke-dashoffset="${((-now*.04)%22)|0}"/><circle cx="${bx|0}" cy="${by|0}" r="${(w+1.7).toFixed(1)}" fill="#fff" stroke="${c}" stroke-width="1.3"/>`);
    if(lbl){const lx=.25*x1+.5*m1+.25*x2,ly=.25*y1+.5*m2+.25*y2-8;out.push(`<circle cx="${x1|0}" cy="${y1|0}" r="4.5" fill="${c}" stroke="#fff" stroke-width="1.4" opacity="${mn(1,op+.2).toFixed(2)}"/><circle cx="${x1|0}" cy="${y1|0}" r="${(7+S.hb*4).toFixed(1)}" fill="none" stroke="${c}" stroke-width="1" opacity="${(op*.55).toFixed(2)}"/><rect x="${(lx-52)|0}" y="${(ly-9)|0}" width="104" height="14" rx="7" fill="rgba(3,10,24,.86)" stroke="${c}" stroke-width=".8" opacity="${mn(1,op+.22).toFixed(2)}"/><text x="${lx|0}" y="${(ly+1)|0}" fill="${c}" font-size="7.3" font-family="monospace" font-weight="700" text-anchor="middle">${lbl}</text>`);}
  };
  [['win','gpu'],['gpu','core'],['core','sv'],['sv','win']].forEach(([a1,b1],i)=>{const pA=pos[a1],pB=pos[b1];if(pA&&pB)bz(pA[0],pA[1],pB[0],pB[1],pA[2],S.foc&&(S.foc===a1||S.foc===b1)?.65:.16+S.hb*.12,1,now*.00028+i*.25);});
  Object.entries(O).forEach(([k,v],i)=>{
    const wEl=$(v[2]),sp0=pos[k];if(!wEl||!sp0)return;
    const wr=wEl.getBoundingClientRect(),x1=(k==='win'||k==='sv'?wr.right:wr.left)-rS.left,y1=(k==='win'||k==='gpu'?wr.bottom-26:wr.top+26)-rS.top,hot=S.foc===k,op=hot?.96:S.foc?.14:.54+S.hb*.22;
    const tx=k==='sv'?`PHANTOM ${S.kx.toFixed(1)}ms`:k==='gpu'?`COLAB ${S.cm}`:k==='win'?`HYPERDESK ${S.wR.toFixed(0)}M`:`VSA · ${S.fl.length} LIVE`;
    bz(x1,y1,sp0[0],sp0[1],v[0],op,hot?2.1:1.35,now*.00045+i*.22,tx);
    S.bolts.forEach(b=>{if(b.org!==k)return;const t=b.t,i1=1-t,m1=(x1+sp0[0])/2,m2=(y1+sp0[1])/2+(sp0[1]<cy0?-24:24);out.push(`<circle cx="${(i1*i1*x1+2*i1*t*m1+t*t*sp0[0])|0}" cy="${(i1*i1*y1+2*i1*t*m2+t*t*sp0[1])|0}" r="5.5" fill="#fff" stroke="${b.col}" stroke-width="2.4" opacity="${(1-t*.7).toFixed(2)}"/>`);});
  });
  svg.innerHTML=out.join('');
}
function drawCh(now){
  const t=(now||performance.now())*.001;
  const P=(id,fn)=>{const c=$(id);if(!c)return;const r=c.getBoundingClientRect();if(r.width<6||r.height<6)return;const d=mn(2,devicePixelRatio||1),W=M.round(r.width*d),H=M.round(r.height*d);if(c.width!==W||c.height!==H){c.width=W;c.height=H;}const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);x.clearRect(0,0,r.width,r.height);x.font='700 8.2px monospace';const ln=(p,cl,w)=>{x.strokeStyle=cl;x.lineWidth=w||1.5;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.stroke();},dt=(X,Y,rd,cl,s)=>{x.beginPath();x.arc(X,Y,rd,0,6.283);s?(x.strokeStyle=cl,x.lineWidth=1.2,x.stroke()):(x.fillStyle=cl,x.fill());},tx=(s,X,Y,cl)=>{x.fillStyle=cl||'#8eb0d6';x.fillText(s,X,Y);},pg=(p,cl,al)=>{x.fillStyle=cl;x.globalAlpha=al;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.closePath();x.fill();x.globalAlpha=1;};fn(x,r.width,r.height,ln,dt,tx,pg);};
  P('c-ecg',(x,W,H,ln,dt)=>{const m=H*.58,dx=W/(R.ecg.length-1),p=R.ecg.map((v,i)=>[i*dx,m-v*H*.46]);ln(p,'#00ffaa',1.5);const lp=p[p.length-1];dt(lp[0],lp[1],2.4,'#fff');});
  P('c-bow',(x,W,H,ln,dt,tx,pg)=>{const m=H*.52,mh=H*.38;ln([[0,m],[W,m]],'rgba(0,240,255,.2)',1);[[R.w,-1,'#00f0ff'],[R.s,1,'#00ffaa']].forEach(([a,d,cl])=>{const p=a.map((v,i)=>[i*W/(a.length-1),m+d*mn(mh,v/80*mh)]);pg([[0,m],...p,[W,m]],cl,.18);ln(p,cl);});tx(`WIN ${S.dWR.toFixed(1)}M`,3,9,'#00f0ff');tx(`SVH ${S.dSR.toFixed(1)}M`,3,H-2,'#00ffaa');});
  P('c-kal',(x,W,H,ln,dt,tx,pg)=>{const sy=H*.66,kx=(W-10)/(R.ke.length-1),lo=mx(.5,mn(...R.kr)-1.8),hi=mx(lo+4,mx(...R.kr)+1.8),my=v=>sy-8-(v-lo)/(hi-lo)*(sy-20),ep=R.ke.map((v,i)=>[4+i*kx,my(v)]);pg([...ep.map(([X,Y])=>[X,Y-8]),...ep.slice().reverse().map(([X,Y])=>[X,Y+8])],'#00f0ff',.15);R.kr.forEach((v,i)=>dt(4+i*kx,my(v),1.5,'#ff4d79'));ln(ep,'#00f0ff',1.6);const lp=ep[ep.length-1];dt(lp[0],lp[1],2.5,'#fff');dt(lp[0],lp[1],5+S.hb*4,'#00f0ff',1);ln([[0,sy+2],[W,sy+2]],'rgba(0,240,255,.18)',1);ln(R.kk.map((k,i)=>[4+i*kx,H-4-mn(H-sy-12,k*(H-sy-9))]),'#b47cff',1.3);tx(`KALMAN RTT ${S.kx.toFixed(2)}ms (±2σ)`,3,9);tx(`GAIN K=${S.kk.toFixed(2)}`,3,sy+12);});
  P('c-ph',(x,W,H,ln,dt,tx)=>{const pL=4,pT=11,pw=W-8,ph=H-22;[['rgba(255,77,121,.12)',0,.28],['rgba(255,184,48,.08)',.28,.32],['rgba(0,255,170,.08)',.6,.4]].forEach(([c,y,h])=>{x.fillStyle=c;x.fillRect(pL,pT+ph*y,pw,ph*h);});for(let i=1;i<R.ph.length;i++){const a=R.ph[i-1],b=R.ph[i],al=i/R.ph.length;x.globalAlpha=.16+al*.84;ln([[pL+a.x*pw,pT+(1-a.y)*ph],[pL+b.x*pw,pT+(1-b.y)*ph]],b.y>.72?'#ff4d79':b.y>.42?'#ffb830':'#00ffaa',1+al*1.4);}x.globalAlpha=1;const lp=R.ph[R.ph.length-1],lx=pL+lp.x*pw,ly=pT+(1-lp.y)*ph,lc=lp.y>.72?'#ff4d79':lp.y>.42?'#ffb830':'#00ffaa';dt(lx,ly,3.2,lc);x.globalAlpha=.6;dt(lx,ly,5.5+sn(t*4.5)*2.2+S.hb*3,lc,1);x.globalAlpha=1;tx('HOT>72°',pL+2,8.5);tx('COOL<55°',pL+2,H-2);const rt=`${S.gt.toFixed(1)}°C • ${S.gu|0}%`;tx(rt,W-x.measureText(rt).width-4,8.5,'#fff');});
  P('c-ht',(x,W,H,ln,dt,tx)=>{const lw=48,cw=(W-lw-2)/16,rh=H/5;x.font='700 7.6px monospace';R.hn.forEach((nm,r)=>{const hi=S.foc&&R.ho[r]===S.foc,y0=r*rh;tx(nm,1,y0+rh*.78,hi?'#fff':'#7d9ec4');for(let k=0;k<16;k++){const v=mn(1,R.ht[r][k]+M.exp(-M.pow(k-(t*5.5)%16,2)*.48)*.32+(hi?.22:0));x.fillStyle=v>.78?'#ffb830':v>.48?'#00f0ff':v>.26?'#1d4ed8':'#0c1a30';x.globalAlpha=v>.78?.96:v>.48?.72:.5;x.fillRect(lw+k*cw+1,y0+1.2,mx(2,cw-2.2),mx(2,rh-2.4));}});x.globalAlpha=1;});
}
let lT=performance.now(),fc=0,fT=lT,_tk=0;
function loop(now){
  if(S.tac||document.hidden){S.raf=0;return;}
  S.raf=requestAnimationFrame(loop);const dt=mn(.05,(now-lT)*.001);lT=now;
  if(++fc&&now-fT>600){T('p-fps',M.round(fc*1e3/(now-fT))+' FPS');fc=0;fT=now;}
  if(!S.dr)S.tY+=dt*(.14+S.hb*.12);
  S.yw+=(S.tY+S.mx*.14-S.yw)*.09;S.pt+=(S.tP+S.my*.1-S.pt)*.09;S.zm+=(S.tZ-S.zm)*.1;S.dWR+=(S.wR-S.dWR)*.14;S.dSR+=(S.sR-S.dSR)*.14;
  S.sp=mx(.24,S.sp-dt*.42);S.tl=mx(0,S.tl-dt*.6);S.fr=mx(0,S.fr-dt*.6);S.tp=mx(0,S.tp-dt*.55);S.sh=mx(0,S.sh-dt*.38);S.hb=mx(0,S.hb-dt*1.25);
  S.bolts.forEach(b=>b.t+=dt*1.35);S.bolts=S.bolts.filter(b=>b.t<1);
  const bpm=clm(60+S.gu*.35+(S.rtt>15?16:0)+S.hb*18,56,120),ph=(now*.001*bpm/60)%1,card=M.exp(-M.pow((ph-.12)/.055,2))+.55*M.exp(-M.pow((ph-.27)/.075,2))+S.hb*.45;
  if((_tk&1)===0)psh(R.ecg,M.exp(-M.pow((ph-.14)/.028,2))*.95-M.exp(-M.pow((ph-.19)/.024,2))*.45+M.exp(-M.pow((ph-.3)/.055,2))*.32+S.hb*.25);
  if(!gl||!S.ok)return;
  const rc=cv.getBoundingClientRect(),dp=mn(1.75,devicePixelRatio||1),w=mx(2,M.floor(rc.width*dp)),h=mx(2,M.floor(rc.height*dp));
  if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}
  gl.viewport(0,0,w,h);gl.clearColor(.008,.02,.048,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE);
  const att=(p,a)=>a.forEach(([n,b,sz])=>{const l=gl.getAttribLocation(p,n);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,sz,gl.FLOAT,false,0,0);}),s1=(u,o)=>Object.entries(o).forEach(([k,v])=>gl.uniform1f(u[k],v));
  gl.useProgram(p1);att(p1,[['aP',b1,3],['aM',b2,3]]);gl.uniform2f(u1.uR,S.yw,S.pt);s1(u1,{uT:now*.001,uZ:S.zm,uA:w/h,uS:S.sp,uW:(now*.003)%6.283,uG:S.sp+S.hb*1.2+S.tl+S.fr,uB:card,uTl:S.tl,uFr:S.fr+(S.cm.includes('WARM')?.48:0),uTp:S.tp,uTh:mx(0,(S.gt-54)/35)});gl.drawArrays(gl.LINES,0,NL);
  if(dirty){gl.bindBuffer(gl.ARRAY_BUFFER,b5);gl.bufferSubData(gl.ARRAY_BUFFER,0,pD);dirty=0;}
  gl.useProgram(p2);att(p2,[['aB',b3,3],['aRn',b4,3],['aD',b5,1],['aK',b6,1]]);gl.uniform2f(u2.uR,S.yw,S.pt);s1(u2,{uT:now*.001,uSh:S.sh,uZ:S.zm,uA:w/h,uS:S.sp,uB:card});gl.drawArrays(gl.POINTS,0,NT);gl.disable(gl.BLEND);
  if((++_tk&1)===0){upMesh(now);drawCh(now);T('v-pl',`${C.destroyedPct?`VSA ${C.destroyedPct}% DMG`:'VSA 100% COHERENT'} • ♥ ${bpm|0} BPM • ${S.syncMs|0}ms`);}
}
function fCam(k){[S.tY,S.tP,S.tZ]={win:[-.52,.18,3.6],gpu:[.58,.32,3.6],sv:[2.6,.18,3.6],core:[0,.05,3.35],over:[.28,.24,4.35]}[k]||[.28,.24,4.35];Q('#cam-b button').forEach(b=>b.classList.toggle('on',b.dataset.c===k));fOrg(k==='over'?null:k);if(k!=='over')spawnBolt(k);}
function fireA(op){const u=String(op||'').toUpperCase();S.hb=1;if(/TELEPORT|DESK|CRYO|PTX/.test(u)){S.tl=1;S.sp=.96;spawnBolt('win','#00f0ff');spawnBolt('gpu','#ffb830');son(740);}else if(/FROST|CART|COLAB|EMBED/.test(u)){S.fr=1;S.sp=.94;spawnBolt('gpu','#b47cff');spawnBolt('core','#00f0ff');son(880);}else if(/TARPIT|DLP/.test(u)){S.tp=1;S.sp=.95;spawnBolt('sv','#ff4d79');}else if(u.includes('CHMC')){S.sh=1;spawnBolt('core','#ff4d79');son(170);}else if(u.includes('VSA')){pD.fill(0);dirty=1;C.destroyedPct=0;spawnBolt('core','#00ffaa');son(620);}else{S.sp=.88;spawnBolt('sv','#00ffaa');}}
function blast(f){for(let i=0;i<NV;i++)pD[i]=i<M.floor(NV*f)?1:0;dirty=1;C.destroyedPct=+(f*100).toFixed(1);S.sp=.95;S.hb=1;spawnBolt('core','#ff4d79');log(`VSA ${C.destroyedPct}% damaged.`);}
const log=t=>{T('h-out',t);T('t-out',t);};
async function api(u,b){const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined),t=await r.text();let j;try{j=JSON.parse(t);}catch(_){j={raw:t};}if(!r.ok)throw new Error(j.error||r.statusText);return j;}
async function rq(u,b,tag){if(tag)fireA(tag);try{const r=await api(u,b);if(tag)pTr(tag.toLowerCase(),JSON.stringify(r).slice(0,46),'ok');log(JSON.stringify(r,null,2));await pulse();return r;}catch(e){log('Err: '+e.message);}}
const act=k=>k==='ks'?rq('/api/trinity/kill-switch',{active:!S.ks,reason:S.ks?'manual_resume':'manual_guard'},'ROI'):A[k]&&rq(A[k][0],A[k][2]||{},A[k][1]);
const tp=()=>rq(P2+'tarpit/env/prod.yml',null,'TARPIT'),togC=n=>n==='connect'?log('Core ON.'):rq('/v1/cartridges',{name:n,enabled:!S.ct[n]},'CART');
async function runB(u,b={}){const r=await rq(u,b,'TELEPORT');if(r&&r.ideas){selSec('galactic');$('h-tbl').innerHTML='<table class="tbl"><thead><tr><th>Idea</th><th>Result</th><th>OK</th></tr></thead><tbody>'+Object.values(r.ideas).slice(0,29).map(x=>`<tr><td>${E(x.name)}</td><td class="in">${E(x.after)}</td><td class="${x.ok?'ok':'er'}">${x.ok?'PASS':'FAIL'}</td></tr>`).join('')+'</tbody></table>';}}
function tac(){S.tac=!S.tac;C.gpuPaused=S.tac;document.body.classList.toggle('tactical',S.tac);$('b-tac').classList.toggle('act',S.tac);if(S.tac){cancelAnimationFrame(S.raf);S.raf=0;T('p-fps','0% GPU');}else{lT=performance.now();S.raf=requestAnimationFrame(loop);}}
function selSec(id){Q('.tab').forEach(t=>t.classList.toggle('active',t.dataset.id===id));Q('.dpn').forEach(p=>p.classList.remove('active'));const p=$('pane-'+id);if(p)p.classList.add('active');}
const oPal=()=>{$('spotlight-modal').classList.add('open');$('spotlight-input').focus();},cPal=()=>$('spotlight-modal').classList.remove('open');
async function xPal(){const q=($('spotlight-input').value||'').trim(),l=q.toLowerCase();if(!q)return;if(A[l]){cPal();return act(l);}if(l==='tarpit'){cPal();return tp();}if(l==='bench'){cPal();return runB(P2+'benchmark',{wave:'all'});}if(l==='zero-gpu'||l==='tactical'){cPal();return tac();}try{T('spotlight-out',JSON.stringify(await api('/api/hyperdrive/search?q='+encodeURIComponent(q)+'&limit=12'),null,2));}catch(e){T('spotlight-out','Err: '+e.message);}}
async function pip(){try{const w=await documentPictureInPicture.requestWindow({width:240,height:86});w.document.body.style.cssText='margin:0;background:#02050c;color:#00f0ff;font:11px monospace;padding:8px';const u=()=>!w.closed&&(w.document.body.innerHTML=`<b>CHIMERA v24</b><br>${S.kx.toFixed(1)}ms • ${S.wR.toFixed(0)}⇄${S.sR.toFixed(0)}MB • ${S.gt|0}°C`);u();const iv=setInterval(()=>w.closed?clearInterval(iv):u(),1e3);}catch(e){log('PiP:'+e.message);}}
function pTr(k,m,c){R.tr.push([new Date().toTimeString().slice(0,8),k,m,c||'in']);if(R.tr.length>12)R.tr.shift();$('t-lg').innerHTML=R.tr.slice(-7).map(([t,k2,m2,c2])=>`<div><span class="mu">${t}</span> <b class="${c2}">${E(k2)}</b> ${E(m2)}</div>`).join('');}
function selFl(i){S.si=i;S.sp=.88;S.hb=.9;const f=S.fl[i];if(f)spawnBolt(f.lane==='compute'?'gpu':f.lane==='crypto'?'core':'sv');renFl(S.fl,1);}
function renFl(fl,keep){if(!fl||!fl.length)return;if(!keep){const n=fl[0].id;if(n>S.lf&&S.lf){fireA(fl[0].op);S.si=0;pTr(fl[0].lane||'wire',`${fl[0].op} ${fl[0].detail||''}`,fl[0].ok?'ok':'er');}S.lf=mx(S.lf,n);S.fl=fl;C.flowsSeen=fl.length;}if(S.si>=S.fl.length)S.si=0;T('w-ct',`${S.fl.length} LIVE`);$('flow-feed').innerHTML=S.fl.slice(0,6).map((f,i)=>`<div class="fl ${E(f.lane)} ${i===S.si?'sel':''}" onclick="selFl(${i})"><div class="sbw"><span><span class="fb ${f.lane==='compute'?'wn':f.lane==='crypto'?'vi':f.lane==='tarpit'?'er':'ok'}">${E(f.op)}</span> <span class="mu">${E(f.src)}→${E(f.dst)}</span></span><span class="${f.ok?'ok':'er'}">${f.bytes?f.bytes+'B ':''}${f.ms}ms</span></div><div class="sbw mu" style="font-size:7.6px"><span>${E(f.detail||'rpc')}</span><span>${E(f.ts)}</span></div></div>`).join('');if(!S.foc)fOrg(null);}
function sKal(o){const p=S.kp+.08,K=p/(p+1.2);S.kx+=K*(o-S.kx);S.kp=(1-K)*p;S.kk=K;psh(R.kr,o);psh(R.ke,S.kx);psh(R.kk,K);}
function upB(z,ph,init){if(z&&z.daemon_ram_mb!=null){S.wR=z.daemon_ram_mb;if(init)S.dWR=S.wR;else psh(R.w,S.wR);T('w-ram',`${S.wR.toFixed(1)}/80MB`);T('sw',`${S.wR.toFixed(1)}MB`);T('tz',`${S.wR.toFixed(1)}/80MB`);}if(ph&&ph.direct_rtt_ms!=null){S.rtt=ph.direct_rtt_ms;if(init)S.kx=S.rtt;else sKal(S.rtt);T('p-tun',S.rtt.toFixed(2)+'ms');T('st',`${S.rtt.toFixed(1)}ms`);}else if(!init)sKal(S.kx);}
let _pBusy=0;
async function pulse(){
  if(document.hidden||_pBusy)return;_pBusy=1;const t0=performance.now();
  try{
    const p=await api('/api/pulse'),{zero_weight:z={},phantom:ph0={},peer:pr0,platform:pl,trinity:tr}=p,ph=ph0.client||{},pr=pr0||S.pr;if(pr)S.pr=pr;
    S.syncMs=performance.now()-t0;S.hbS++;S.hb=mn(1,S.hb+.7);const d=$('hb-dot');if(d){d.classList.add('hit');setTimeout(()=>d.classList.remove('hit'),150);}T('hb-lbl',`SYNC · #${S.hbS}`);
    upB(z,ph,0);if(pr&&pr.zero_weight&&pr.zero_weight.daemon_ram_mb!=null)S.sR=pr.zero_weight.daemon_ram_mb;psh(R.s,S.sR);
    if(pr&&pr.online){T('ss',`${S.sR.toFixed(1)}MB`);T('tp',`${pr.node_name} ${S.sR.toFixed(1)}MB`);}
    const tb=(ph.tx_bytes||0)+(ph.rx_bytes||0),now=performance.now();if(S.lt&&tb>=S.lb){S.rk=M.round((tb-S.lb)/1024/mx(.2,(now-S.lt)/1e3));if(S.rk>1){S.sp=mn(1,S.sp+.38);spawnBolt('sv','#00ffaa');}}S.lb=tb;S.lt=now;T('p-rt',`${S.rk} KB/s`);
    if(p.latest_event)T('te',`${p.latest_event.ts_local} ${p.latest_event.message}`);
    if(tr){S.ks=!!tr.kill_switch;T('p-gov',tr.governor_mode||'LOCAL');const b=$('b-ks');b.textContent=S.ks?'HALT':'ROI';b.className=S.ks?'act':'';}
    if(pl){
      const hd=pl.hyper_desk||{},th=pl.thermo||{},om=pl.omega||{};S.th=th;S.eh=pl.egress_hit_pct||0;S.egR=pl.egress_requests||0;S.dlp=pl.egress_dlp_blocked||0;
      if(pl.gpu_temp_c!=null)S.gt=+pl.gpu_temp_c;if(pl.gpu_util_pct!=null)S.gu=+pl.gpu_util_pct;
      S.vf=+pl.vram_free_mb||S.vf;S.vt=+pl.vram_total_mb||S.vt;S.cu=+pl.colab_cu||S.cu;S.cm=String(pl.colab_mode||'AUTO:SLEEP');S.oaiM=+pl.openai_models_count||S.oaiM;S.uni=!!pl.unify_active;S.apps=pl.apps_online||[];
      const gb=((hd.reclaimed_mb||0)/1024).toFixed(2),lk=S.apps.length?S.apps.join(', '):`${pl.apps_total||0}`;
      [['hd-gb',`+${gb} GB`],['hd-cw',`${hd.cryo_procs||0} / ${hd.wall_pinned||0}`],['oai-m',`${S.oaiM} ${S.uni?'UNIFY':'LOC'}`],['p-thm',`${th.watts||0}W`],['p-cu',`${S.cu|0}CU · ${S.cm}`],['th-r',String(th.regime||'COOL').replace('_LOCAL','').replace('_SVHOME','→SVH')],['om-g',`${om.genome||'lz4_simd'} #${om.gen||1}`],['p-pl',lk],['tt2',`+${gb}GB • ${S.cu|0}CU`]].forEach(([i,v])=>T(i,v));
      if(pl.cartridges){S.ct=pl.cartridges;const en=Object.entries(pl.cartridges);T('c-cnt',`${en.filter(([,v])=>v).length}/${en.length} ON`);$('c-ch').innerHTML=en.map(([k,v])=>{const og=CO[k]||'core';return`<span class="cc ${v?'':'off'} ${S.foc===og?'hi':''}" data-org="${og}" data-cart="${E(k)}" onclick="togC('${E(k)}')"><i></i>${E(k.replace(/_(entity|membrane|pareto)/,'').replace('_',''))}</span>`;}).join('');}
      const rp=[mn(1,.32+S.rk/35+S.hb*.2),S.cm.includes('WARM')?.95:mn(.82,.42+S.gu/80),mn(1,.28+S.eh/100+S.egR*.02),hd.cryo_procs?.86:.36,C.destroyedPct?.96:.58];
      R.ht.forEach((r,i)=>psh(r,clm(rp[i]+sn(S.hbS*.7+i)*.1,.12,1)));psh(R.ph,{x:clm(((+th.cpu_pct||15)+S.gu*.6)/130,.08,.94),y:clm((S.gt-35)/50,.08,.94)});
      if(!R.tr.length)pTr('sync',`${S.rtt.toFixed(1)}ms • ${S.oaiM} OAI • ${S.cu|0}CU`,'ok');renRings();
    }
    if(p.flows)renFl(p.flows,0);if(p.status_etag&&p.status_etag!==_et)await refresh();
  }catch(_){}finally{_pBusy=0;}
}
function sched(){pulse().finally(()=>setTimeout(sched,450));}
async function refresh(){try{const r=await fetch('/api/status',{headers:_et?{'If-None-Match':_et}:{}});if(r.status===304||!r.ok)return;_et=r.headers.get('ETag')||_et;const j=await r.json();upB(j.zero_weight,(j.phantom||{}).client,1);}catch(_){}}
$('stage').onmousemove=e=>{S.mx=(e.clientX/innerWidth-.5)*2;S.my=(e.clientY/innerHeight-.5)*2;};
$('hud').onmouseover=e=>{const c=e.target.closest('[data-cart]');if(c){const k=c.dataset.cart,og=c.dataset.org;fOrg(og,[`CARTRIDGE · ${k.toUpperCase()} → ${(O[og]||O.core)[3]}`,CD[k]||'Live cartridge']);return;}const t=e.target.closest('[data-org]');fOrg(t?t.dataset.org:null);};
$('hud').onmouseleave=()=>fOrg(null);
cv.onpointerdown=e=>{S.dr=1;S.lx=e.clientX;S.ly=e.clientY;cv.setPointerCapture(e.pointerId);};cv.onpointerup=()=>S.dr=0;
cv.onpointermove=e=>{if(!S.dr)return;const dx=e.clientX-S.lx,dy=e.clientY-S.ly;S.lx=e.clientX;S.ly=e.clientY;if(e.shiftKey){const rc=cv.getBoundingClientRect(),nx=(e.clientX-rc.left)/rc.width*2-1,ny=1-(e.clientY-rc.top)/rc.height*2,a=rc.width/mx(1,rc.height),cy=cs(S.yw),sy=sn(S.yw),cp=cs(S.pt),sp=sn(S.pt);let h=0;for(let i=0;i<NV;i++){if(pD[i]>.5)continue;const px=pB[i*3],py=pB[i*3+1],pz=pB[i*3+2],x1=px*cy-pz*sy,z1=px*sy+pz*cy,d=mx(.45,-(py*sp+z1*cp-S.zm));if((x1/(d*.55*a)-nx)**2+((py*cp-z1*sp)/(d*.55)-ny)**2<.055){pD[i]=1;h++;}}if(h){dirty=1;let c2=0;for(let i=0;i<NV;i++)if(pD[i]>.5)c2++;C.destroyedPct=+(c2*100/NV).toFixed(1);S.sp=.95;S.hb=1;}return;}S.tY+=dx*.007;S.tP=clm(S.tP+dy*.007,-1.1,1.1);};
cv.addEventListener('wheel',e=>{S.tZ=clm(S.tZ+M.sign(e.deltaY)*.28,2.6,6.6);},{passive:true});
window.onresize=()=>{drawCh(performance.now());upMesh(performance.now());};
document.onvisibilitychange=()=>{if(!document.hidden&&!S.tac&&!S.raf){lT=performance.now();S.raf=requestAnimationFrame(loop);pulse();}};
window.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K'||e.code==='Space')){e.preventDefault();$('spotlight-modal').classList.contains('open')?cPal():oPal();return;}if(e.key==='Escape')return cPal();if(e.key==='Tab'){e.preventDefault();return tac();}if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;const k={'1':'wire','0':'hyperdrive','x':'galactic','X':'galactic','8':'ops'}[e.key];if(k)selSec(k);};
$('pipe').innerHTML=[['win','WIN-DESKTOP','#00f0ff'],['sv','PHANTOM ⇄ SVHOME','#00ffaa'],['core','VSA-10K CORE','#ffb830'],['gpu','COLAB T4 ELASTIC','#b47cff']].map(([k,l,c],i)=>(i?'<span class="pa">══►</span>':'')+`<span class="pn" style="--pc:${c}" data-org="${k}" onclick="fCam('${k}')"><i></i>${l}</span>`).join('');
$('sat-layer').innerHTML=Object.entries(O).map(([k,v])=>`<div class="sat" id="sat-${k}" style="--sc:${v[0]}" data-org="${k}" onmouseenter="fOrg('${k}')" onmouseleave="fOrg(null)" onclick="fCam('${k}')"><i></i><div><b>${v[3]}</b><br><small>${v[4]}</small></div></div>`).join('');
$('cam-b').innerHTML=[['over','ORBIT'],['win','WIN'],['core','CORE'],['sv','SVHOME'],['gpu','COLAB']].map(([k,l])=>`<button class="xs ${k==='over'?'on':''}" data-c="${k}" onclick="fCam('${k}')">${l}</button>`).join('');
$('s-tb').innerHTML=[['wire','[1] CAUSAL WIRE'],['hyperdrive','[0] v9'],['galactic','[X] v12 (29)'],['ops','[8] OPS']].map(([k,l])=>`<button class="tab ${k==='wire'?'active':''}" data-id="${k}" onclick="selSec('${k}')">${l}</button>`).join('');
$('ac-hyp').innerHTML=bt([['Bench v9',"runB('/api/hyperdrive/benchmark')"],['Status',"rq('/api/hyperdrive/status')"],['PHANTOM',"act('ph')"]],'xs');
$('ac-gal').innerHTML=bt([['All 29',"runB(P2+'benchmark',{wave:'all'})"],['v10',"runB(P2+'benchmark',{wave:'v10'})"],['v11',"runB(P2+'benchmark',{wave:'v11'})"],['v12',"runB(P2+'benchmark',{wave:'v12'})"]],'xs');
$('ac-ops').innerHTML=bt([['Unify',"rq('/v1/unify/status')"],['Colab',"rq('/v1/vgpu/colab/policy')"],['SMI',"rq('/v1/smi')"],['Models',"rq('/v1/openai/v1/models')"],['Freeze',"act('freeze')"]],'xs');
$('q-act').innerHTML=bt([['WASM',"act('teleport')"],['FROST',"act('frost')"],['Blast',"blast(.42)"],['Heal',"act('vsa')"],['Tarpit','tp()'],['CHMC',"act('chmc')"]],'xs');
$('t-act').innerHTML=bt([['Cryo',"act('opt')"],['WASM',"act('teleport')"],['FROST',"act('frost')"],['VSA',"act('vsa')"],['Bench',"runB(P2+'benchmark',{wave:'all'})"]])+'<button class="pri" onclick="tac()">3D</button>';
$('t-grid').innerHTML=[['WIN','tz',''],['SVHOME','tp','ok'],['COLAB','tt2','in'],['EVENT','te','wn']].map(([l,i,c])=>`<div class="tb2"><b>${l}</b><div id="${i}" class="${c}">--</div></div>`).join('');
initGL();if(window.__INIT_STATE__)upB(window.__INIT_STATE__.zero_weight,(window.__INIT_STATE__.phantom||{}).client,1);else refresh();renRings();drawCh(performance.now());S.raf=requestAnimationFrame(loop);setTimeout(sched,100);
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
    """Emit self-unpacking DecompressionStream('deflate-raw') capsule (<20 KB gzipped wire)."""
    s_b64 = _deflate_raw_b64(init_state_json)
    boot = (
        "<!doctype html><html><head><meta charset='utf-8'><title>CHIMERA v24 OMNISCIENCE</title></head>"
        "<body style='margin:0;background:#02050c;color:#00f0ff;font:12px monospace;padding:16px'>"
        "<!-- CHIMERA-HYPER v2.0 -->Awakening CHIMERA OMNISCIENCE v24..."
        "<script>const _u=x=>new Response(new Blob([Uint8Array.from(atob(x),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();"
        f"(async()=>{{const[h0,s0]=await Promise.all([_u('{_RAW_DEFLATE_B64}'),_u('{s_b64}')]);"
        f"document.open();document.write(h0.replace('/*__INIT_STATE__*/null',()=>s0).replace('/*__INIT_ETAG__*/\"\"',()=>JSON.stringify({etag_json})));document.close();}})();</script></body></html>"
    )
    return boot.encode("utf-8")

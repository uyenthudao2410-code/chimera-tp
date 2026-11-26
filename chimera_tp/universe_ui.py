"""CHIMERA-HYPER v14.0 PHANTOM-CORTEX — Unified Real-Time Living Causal Topology (<16KB Wire).

Unifies ALL subsystems in ONE live connected 3D scene driven by real daemon flows:
- WIN-DESKTOP (-2.05) <=> Center Singularity + 10,000-bit VSA Halo (0.0) <=> SVHOME Hub + 0-KB Tarpit Shield (+2.05).
- 3 Volumetric Highways: PHANTOM-5MS Direct (:9789->:9780), Compute/Crypto Bus (WASM Teleport Metaball & Twin FROST Beams), AI Relay (:12550) & SSH (:2222).
- 10,360 GPU particles in 1 draw call (10,000 interactive VSA Halo bits + 360 directional traveling packets).
- GPU Mobius Poincare floor warping dynamically toward hovered/focused nodes + real-time #flow-feed trace.
- Tab 0-GPU Tactical Schematic Mode (stops requestAnimationFrame cleanly, live SVG cluster diagram) + Ctrl+K/Space Palette.
"""

from __future__ import annotations

import base64
import zlib

UNIVERSE_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA-HYPER v12.0 OMEGA-GALACTIC — PHANTOM-CORTEX Unified 3D</title>
<style>
  :root{--bg:#02050d;--fg:#e2e8f0;--mut:#8aa3c7;--cy:#22d3ee;--gr:#34d399;--am:#fbbf24;--vi:#a78bfa;--rd:#fb7185;--bd:rgba(56,189,248,.26);--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--sans:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;overflow:hidden;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:12px}
  #gl{position:fixed;inset:0;width:100%;height:100%;display:block;cursor:grab}
  #gl:active{cursor:grabbing}
  body.tactical #gl,body.tactical .hud3d,body.tactical #cortex-hud,body.tactical #flow-panel,body.tactical #node-tags{display:none!important}
  body.tactical #tactical-deck{display:flex}
  body.tactical{background:#030806;color:#bbf7d0;--cy:#34d399;--bd:rgba(52,211,153,.32)}

  #topbar{position:fixed;top:8px;left:10px;right:10px;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:6px;padding:6px 10px;background:rgba(4,10,24,.82);border:1px solid var(--bd);border-radius:11px}
  .row{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
  .orb{width:12px;height:12px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#67e8f9,#3b82f6 60%,#02050d);box-shadow:0 0 12px var(--cy)}
  .brand{font-weight:800;letter-spacing:.04em;font-size:12px;color:#fff}
  .pill{font-family:var(--mono);font-size:9.5px;padding:2px 6px;border-radius:999px;border:1px solid var(--bd);background:rgba(9,18,38,.88);color:#cbd5e1;white-space:nowrap}
  .pill.ok{color:var(--gr);border-color:rgba(52,211,153,.42)}
  .pill.warn{color:var(--am);border-color:rgba(251,191,36,.45)}

  button,input{font:inherit;color:var(--fg);background:rgba(9,19,40,.92);border:1px solid var(--bd);border-radius:7px;padding:4px 8px;outline:none}
  button{cursor:pointer;font-size:10.5px;font-weight:600}
  button:hover{border-color:var(--cy);background:rgba(18,40,80,.92)}
  button.pri{background:linear-gradient(135deg,rgba(14,116,144,.88),rgba(30,64,175,.88));border-color:rgba(103,232,249,.65);color:#fff}
  button.act{border-color:var(--am);color:var(--am)}
  input:focus{border-color:var(--cy)}

  #node-tags{position:fixed;inset:0;pointer-events:none;z-index:10;overflow:hidden}
  .ntag{position:fixed;padding:4px 8px;border-radius:8px;background:rgba(3,8,20,.82);border:1px solid var(--bd);font-family:var(--mono);font-size:9.5px;line-height:1.25;transform:translate(-50%,-50%);white-space:nowrap;text-align:center}
  .ntag b{display:block;font-size:10px}
  .wtag{position:fixed;padding:2px 7px;border-radius:999px;background:rgba(3,9,22,.84);border:1px solid rgba(148,163,184,.28);font-family:var(--mono);font-size:9px;transform:translate(-50%,-50%);white-space:nowrap}

  #cortex-hud{position:fixed;left:10px;bottom:10px;z-index:22;width:min(456px,calc(50vw - 14px));max-height:305px;display:flex;flex-direction:column;background:rgba(5,11,26,.84);border:1px solid var(--bd);border-radius:12px;overflow:hidden;box-shadow:0 14px 40px rgba(0,0,0,.6)}
  .tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid rgba(148,163,184,.16);flex-wrap:wrap}
  .tab{padding:3px 7px;font-size:10px;font-family:var(--mono);border-radius:6px;background:rgba(10,20,42,.75)}
  .tab.active{background:rgba(34,211,238,.22);border-color:var(--cy);color:#fff}
  .hud-body{padding:8px 10px;overflow-y:auto;display:flex;flex-direction:column;gap:6px}
  .sub{font-family:var(--mono);font-size:9.5px;color:var(--cy)}
  .out{background:rgba(2,6,14,.92);border:1px solid rgba(34,211,238,.2);border-radius:7px;padding:6px 8px;font-family:var(--mono);font-size:9.5px;color:#d1fae5;max-height:110px;overflow:auto;white-space:pre-wrap;word-break:break-word}
  table.tbl{width:100%;border-collapse:collapse;font-size:9.5px;font-family:var(--mono)}
  table.tbl th,table.tbl td{text-align:left;padding:3px 4px;border-bottom:1px solid rgba(148,163,184,.14)}
  .deck-pane{display:none}.deck-pane.active{display:block}

  #flow-panel{position:fixed;right:10px;bottom:10px;z-index:22;width:min(450px,calc(50vw - 14px));max-height:280px;display:flex;flex-direction:column;gap:5px;padding:8px 10px;background:rgba(5,11,26,.84);border:1px solid rgba(52,211,153,.3);border-radius:12px}
  #flow-feed{display:flex;flex-direction:column;gap:4px;overflow-y:auto;max-height:215px;font-family:var(--mono);font-size:9.5px}
  .fline{padding:4px 6px;border-radius:6px;background:rgba(7,16,34,.88);border-left:3px solid var(--cy);display:flex;justify-content:space-between;gap:6px}
  .fline.compute{border-left-color:var(--am)}.fline.crypto{border-left-color:var(--vi)}.fline.tarpit{border-left-color:var(--gr)}

  #spotlight-modal{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:70px;background:rgba(2,5,13,.76)}
  #spotlight-modal.open{display:flex}
  .pal-card{width:min(620px,92vw);background:#071124;border:1px solid rgba(34,211,238,.5);border-radius:13px;padding:12px;display:flex;flex-direction:column;gap:8px}

  #tactical-deck{position:fixed;top:60px;left:10px;right:10px;bottom:10px;z-index:25;display:none;flex-direction:column;gap:8px;overflow:auto;padding:12px;background:rgba(3,9,7,.98);border:1px solid var(--bd);border-radius:12px;font-family:var(--mono)}
  .tac-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px}
  .tac-box{border:1px solid rgba(52,211,153,.28);border-radius:8px;padding:8px 10px;background:rgba(5,15,11,.88)}
</style>
</head>
<body>
<!-- CHIMERA-HYPER v2.0 / v12.0 / v14.0 PHANTOM-CORTEX UNIFIED -->
<canvas id="gl"></canvas>
<div id="node-tags" class="hud3d">
  <div class="ntag" id="tag-win" style="color:#7dd3fc"><b>WIN-DESKTOP</b><span id="tw-sub">--</span></div>
  <div class="ntag" id="tag-core" style="color:var(--cy)"><b>SINGULARITY • VSA 10K</b><span id="tc-sub">10,000-bit Halo IDLE</span></div>
  <div class="ntag" id="tag-sv" style="color:var(--gr)"><b>SVHOME HUB • TARPIT</b><span id="ts-sub">--</span></div>
  <div class="wtag" id="tag-l1" style="color:#22d3ee">⚡ PHANTOM 5ms</div>
  <div class="wtag" id="tag-l2" style="color:#fbbf24">🧠 WASM • FROST 2-of-3</div>
  <div class="wtag" id="tag-l3" style="color:#34d399">🤖 AI :12550 • SSH :2222</div>
</div>

<header id="topbar">
  <div class="row">
    <div class="orb"></div>
    <span class="brand">PHANTOM-CORTEX v17.0</span>
    <span class="pill ok" id="p-tun">PHANTOM ...</span>
    <span class="pill ok" id="p-ram">WIN -- ⇄ SV --</span>
    <span class="pill" id="p-gov">GOV --</span>
    <span class="pill ok" id="p-plat">v17 APPS:-- • :9781</span>
    <span class="pill" id="p-rate">WIRE 0 KB/s</span>
    <span class="pill" id="p-fps">GPU</span>
  </div>
  <div class="row">
    <button class="act" onclick="focusCam('over')">Overview</button>
    <button onclick="focusCam('win')">WIN</button>
    <button onclick="focusCam('core')">CORE+VSA</button>
    <button onclick="focusCam('sv')">SVHOME+Tarpit</button>
    <button id="btn-ks" onclick="toggleKillSwitch()">🛡️ ROI Guard</button>
    <button id="btn-tac" onclick="toggleTactical()">Tab 0-GPU</button>
    <button id="btn-sonic" onclick="toggleSonic()">🔇 Sonic</button>
    <button class="pri" onclick="openPalette()">🔎 Ctrl+K</button>
  </div>
</header>

<aside id="cortex-hud" class="hud3d">
  <div class="tabs" id="sector-tabs"></div>
  <div class="hud-body">
    <div class="row" style="justify-content:space-between">
      <b id="hud-title" style="color:#fff;font-size:11.5px">UNIFIED CLUSTER FABRIC</b>
      <span class="sub" id="hud-sub">Live WIN ⇄ PHANTOM 5ms ⇄ SVHOME</span>
    </div>
    <div class="row" id="hud-actions"></div>
    <div id="pane-hyperdrive" class="deck-pane"><span class="sub">Sector 00 • v9.0 HYPERDRIVE (PH9N, NVMe, SpeedFusion, Spotlight)</span></div>
    <div id="pane-galactic" class="deck-pane"><span class="sub">Sector 10 • v12.0 OMEGA-GALACTIC (29 Breakthroughs + VSA/FROST/WASM)</span></div>
    <div id="hud-table" style="max-height:110px;overflow:auto"></div>
    <div class="out" id="hud-out">Kéo xoay 3D • Shift+Kéo trực tiếp lên vòng sáng quanh lõi để phá 40% hạt VSA • Bấm nút để bắn dữ liệu thật qua hầm 5ms.</div>
  </div>
</aside>

<aside id="flow-panel" class="hud3d">
  <div class="row" style="justify-content:space-between">
    <span style="color:var(--gr);font-weight:700;font-size:11px">📡 LIVE CAUSAL WIRE TRACE (WIN ⇄ SVHOME)</span>
    <span class="pill ok" id="vsa-pill">VSA 100% COHERENT</span>
  </div>
  <div id="flow-feed">Đang chờ gói thực từ /api/pulse...</div>
</aside>

<section id="tactical-deck" aria-label="Tactical Zero-GPU Console">
  <div class="row" style="justify-content:space-between;border-bottom:1px solid rgba(52,211,153,.28);padding-bottom:6px">
    <div><b style="color:#fff">NERV // UNIFIED ZERO-GPU SCHEMATIC</b> <span style="color:var(--gr)">[0% GPU — requestAnimationFrame STOPPED]</span></div>
    <div class="row">
      <button onclick="liveTeleport()">🌀 WASM Teleport</button>
      <button onclick="liveFrost()">🔐 FROST 2-of-3</button>
      <button onclick="reconstructVsa()">⚡ VSA 10K Heal</button>
      <button onclick="probeTarpit('/env/prod.yml')">🕸️ Tarpit 0KB</button>
      <button onclick="runBench('/api/hyperdrive/benchmark','hyp')">⚡ Bench v9</button>
      <button onclick="runBench('/api/galactic/benchmark','gal',{wave:'all'})">🌌 Bench v12</button>
      <button class="pri" onclick="toggleTactical()">Tab 3D Scene</button>
    </div>
  </div>
  <svg viewBox="0 0 880 120" style="width:100%;height:120px;border:1px solid rgba(52,211,153,.25);border-radius:8px;background:#020705">
    <rect x="16" y="20" width="175" height="80" rx="10" fill="#06141a" stroke="#22d3ee"/>
    <text x="103" y="42" text-anchor="middle" fill="#7dd3fc" font-size="11" font-weight="bold">WIN-DESKTOP</text>
    <text id="svg-win" x="103" y="64" text-anchor="middle" fill="#e2e8f0" font-size="10">RAM --</text>
    <text x="103" y="84" text-anchor="middle" fill="#8aa3c7" font-size="9">:9788 :9789 :12550 :2222</text>
    <path d="M 191 36 Q 440 8 689 36" fill="none" stroke="#22d3ee" stroke-width="2" stroke-dasharray="6 4"/>
    <line x1="191" y1="60" x2="689" y2="60" stroke="#fbbf24" stroke-width="2"/>
    <path d="M 191 84 Q 440 112 689 84" fill="none" stroke="#34d399" stroke-width="1.8" stroke-dasharray="4 4"/>
    <circle cx="440" cy="60" r="26" fill="#091529" stroke="#fbbf24" stroke-width="2"/>
    <text x="440" y="57" text-anchor="middle" fill="#fbbf24" font-size="9" font-weight="bold">VSA 10K</text>
    <text x="440" y="70" text-anchor="middle" fill="#a78bfa" font-size="8">FROST+WASM</text>
    <text id="svg-tun" x="440" y="18" text-anchor="middle" fill="#22d3ee" font-size="10">PHANTOM-5MS DIRECT</text>
    <rect x="689" y="20" width="175" height="80" rx="10" fill="#061a14" stroke="#34d399"/>
    <text x="776" y="42" text-anchor="middle" fill="#34d399" font-size="11" font-weight="bold">SVHOME HUB</text>
    <text id="svg-sv" x="776" y="64" text-anchor="middle" fill="#e2e8f0" font-size="10">RAM --</text>
    <text x="776" y="84" text-anchor="middle" fill="#8aa3c7" font-size="9">C11 AVX2 • TARPIT 0KB</text>
  </svg>
  <div class="tac-grid">
    <div class="tac-box"><b>WIN &amp; TUNNEL HEALTH</b><div id="tac-zw" style="margin-top:4px">--</div></div>
    <div class="tac-box"><b>SVHOME PEER LIVE</b><div id="tac-peer" style="margin-top:4px;color:#6ee7b7">Probing...</div></div>
    <div class="tac-box"><b>TRINITY GOD-MODE</b><div id="tac-tri" style="margin-top:4px;color:#67e8f9">--</div></div>
    <div class="tac-box"><b>LATEST DAEMON EVENT</b><div id="tac-ev" style="margin-top:4px;color:#fde68a">--</div></div>
  </div>
  <div class="out" id="tac-out" style="max-height:220px">--</div>
</section>

<div id="spotlight-modal" onclick="if(event.target===this)closePalette()">
  <div class="pal-card">
    <div class="row" style="justify-content:space-between">
      <span style="font-weight:700;color:var(--cy)">🔎 JARVIS Command &amp; Cross-Node Spotlight (Ctrl+K / Ctrl+Space)</span>
      <button onclick="closePalette()">ESC</button>
    </div>
    <div class="row">
      <input id="spotlight-input" style="flex:1" placeholder="Tìm symbol code (VD: PhantomTunnel) hoặc lệnh: teleport / frost / vsa / tarpit / bench / zero-gpu" onkeydown="if(event.key==='Enter')execPalette()">
      <button class="pri" onclick="execPalette()">Chạy / Tìm</button>
    </div>
    <div class="out" id="spotlight-out" style="max-height:220px">Tìm kiếm toàn cụm &lt;5 ms qua LiveClusterIndexer &amp; ghi nhận luồng thật lên đồ thị 3D.</div>
  </div>
</div>

<script>
window.__INIT_STATE__=/*__INIT_STATE__*/null;
let _etag=/*__INIT_ETAG__*/"";

const SECTORS=[
  {id:'flow',key:'1',pane:'',title:'UNIFIED CLUSTER FABRIC',sub:'Click any live primitive to watch it traverse WIN ⇄ 5ms Tunnel ⇄ SVHOME',acts:[['🌀 Live WASM Teleport','liveTeleport()'],['🔐 Live FROST 2-of-3','liveFrost()'],['💥 Blast 40% VSA','blastVsa(0.42)'],['⚡ AVX2 VSA Heal','reconstructVsa()'],['🕸️ Tarpit 0-KB','probeTarpit("/env/prod.yml")'],['💣 Live CHMC 3-Strike','liveChmc()'],['📜 Proofs (5s)',"runGet('/api/trinity/proofs?limit=8')"],['🧬 VSA Sync',"runCmd('/api/vsa/sync-peer')"]]},
  {id:'hyperdrive',key:'0',pane:'pane-hyperdrive',title:'v9.0 HYPERDRIVE',sub:'Sector 00 • PH9N 2.6+ Gbps, NVMe, SpeedFusion, App Stream',acts:[['⚡ Bench v9 (6/6)',"runBench('/api/hyperdrive/benchmark','hyp')"],['📡 Status v9',"runGet('/api/hyperdrive/status')"],['⚡ PHANTOM 5ms',"runCmd('/api/phantom/connect')"],['🔎 Spotlight','openPalette()']]},
  {id:'galactic',key:'X',pane:'pane-galactic',title:'v12.0 OMEGA-GALACTIC',sub:'Sector 10 • 29 Wave 2-4 Breakthroughs',acts:[['🌌 Bench All (29)',"runBench('/api/galactic/benchmark','gal',{wave:'all'})"],['🛡️ v10 (13)',"runBench('/api/galactic/benchmark','gal',{wave:'v10'})"],['🧬 v11 (11)',"runBench('/api/galactic/benchmark','gal',{wave:'v11'})"],['✨ v12 (5)',"runBench('/api/galactic/benchmark','gal',{wave:'v12'})"],['📡 Status v12',"runGet('/api/galactic/status')"]]},
  {id:'ops',key:'8',pane:'',title:'v7–v8 & OPS SERVICES',sub:'OMEGA, SINGULARITY, WebDAV /dav/, Eval',acts:[['🚀 Bench v7 (14)',"runBench('/api/omega/benchmark','omg')"],['🕳️ Bench v8 (7)',"runBench('/api/singularity/benchmark','sing')"],['▶ Eval Cụm',"runCmd('/api/run')"],['📁 WebDAV /dav/',"window.open('/dav/','_blank')"]]}
];

const VS_SDF=`precision highp float;
attribute vec2 p;varying vec2 vUv;
void main(){vUv=p*0.5+0.5;gl_Position=vec4(p,0.0,1.0);}`;

const FS_SDF=`precision highp float;
uniform vec2 uRes,uRot,uMob,uPan;
uniform float uTime,uSpike,uTel,uFrost,uTarp,uZoom;
varying vec2 vUv;
float smin(float a,float b,float k){float h=clamp(0.5+0.5*(b-a)/k,0.0,1.0);return mix(b,a,h)-k*h*(1.0-h);}
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
vec2 cdiv(vec2 a,vec2 b){return vec2(a.x*b.x+a.y*b.y,a.y*b.x-a.x*b.y)/max(0.001,dot(b,b));}
vec2 cmul(vec2 a,vec2 b){return vec2(a.x*b.x-a.y*b.y,a.x*b.y+a.y*b.x);}

float seg(vec3 p,vec3 a,vec3 b){vec3 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.0,1.0);return length(pa-ba*h);}

float map(vec3 p){
  vec3 wP=vec3(-2.05,0.08*sin(uTime*1.3),0.0);
  vec3 cP=vec3(0.0,0.0,0.0);
  vec3 sP=vec3(2.05,-0.08*sin(uTime*1.3),0.0);
  float spk=pow(max(0.0,sin(p.x*8.0+uTime*2.4)*cos(p.y*8.0-uTime*1.9)*sin(p.z*8.0+uTime)),2.0);
  float dW=length(p-wP)-(0.36+spk*0.04*(1.0+uSpike));
  float dC=length(p-cP)-(0.50+spk*(0.04+uSpike*0.16));
  float dS=length(p-sP)-(0.42+spk*0.04*(1.0+uSpike));
  float d=min(dW,min(dC,dS));
  if(uTel>0.005){
    float arc=sin(uTel*3.14159);
    vec3 tP=mix(wP,sP,uTel)+vec3(0.0,arc*0.92,0.12*sin(uTel*6.283));
    d=smin(d,length(p-tP)-(0.15+0.07*arc),0.34);
  }
  vec2 tr=vec2(length((p-sP).xz)-0.66,(p-sP).y);
  float dShield=length(tr)-0.032;
  return min(d,dShield);
}

vec3 calcN(vec3 p){vec2 e=vec2(0.006,0.0);return normalize(vec3(map(p+e.xyy)-map(p-e.xyy),map(p+e.yxy)-map(p-e.yxy),map(p+e.yyx)-map(p-e.yyx)));}

float pipeGlow(vec3 ro,vec3 rd,float maxT){
  float acc=0.0;
  for(int j=0;j<18;j++){
    float t=1.2+float(j)*0.34;
    if(t>maxT)break;
    vec3 p=ro+rd*t;
    if(abs(p.x)<2.15){
      float curve=0.58*cos(p.x*0.72);
      float dTop=length(vec2(p.y-curve,p.z));
      float dMid=length(vec2(p.y,p.z));
      float dBot=length(vec2(p.y+curve,p.z));
      acc+=exp(-dTop*11.0)*0.055*(1.0+uSpike);
      acc+=exp(-dMid*13.0)*0.042*(1.0+uFrost*2.2+uTel*1.8);
      acc+=exp(-dBot*11.0)*0.048;
      if(uFrost>0.01){
        float xL=mix(-2.05,0.0,uFrost),xR=mix(2.05,0.0,uFrost);
        float pL=length(p-vec3(xL,0.0,0.0)),pR=length(p-vec3(xR,0.0,0.0));
        acc+=(exp(-pL*8.0)+exp(-pR*8.0))*0.24*sin(uFrost*3.14159);
      }
    }
  }
  return acc;
}

void main(){
  vec2 uv=(vUv*2.0-1.0)*vec2(uRes.x/uRes.y,1.0);
  uv.y-=0.12;
  vec3 ro=vec3(0.0,0.22,uZoom);
  vec3 rd=normalize(vec3(uv,-1.65));
  ro.yz*=rot(uRot.y);rd.yz*=rot(uRot.y);
  ro.xz*=rot(uRot.x);rd.xz*=rot(uRot.x);
  ro.x+=uPan.x;

  vec3 col=vec3(0.010,0.022,0.060)+vec3(0.018,0.045,0.11)*max(0.0,1.0-length(uv));
  if(rd.y<-0.015&&ro.y>-1.32){
    float tp=(-1.32-ro.y)/rd.y;
    if(tp>0.0&&tp<30.0){
      vec2 z=(ro+rd*tp).xz*0.21;
      float r2=dot(z,z);
      if(r2<1.0){
        vec2 m=clamp(uMob,vec2(-0.55),vec2(0.55));
        vec2 w=cdiv(z-m,vec2(1.0,0.0)-cmul(vec2(m.x,-m.y),z));
        float g1=smoothstep(0.04,0.0,abs(fract(atan(w.y,w.x)*3.82)-0.5)-0.46);
        float g2=smoothstep(0.04,0.0,abs(fract(log(max(0.02,length(w)))*2.4)-0.5)-0.46);
        col+=vec3(0.06,0.34,0.52)*(g1+g2)*smoothstep(1.0,0.9,r2)*exp(-tp*0.09);
      }
    }
  }

  float t=0.0,glow=0.0;bool hit=false;
  for(int i=0;i<44;i++){
    float d=map(ro+rd*t);
    glow+=exp(-abs(d)*3.6)*0.024;
    if(d<0.004){hit=true;break;}
    t+=d*0.86;
    if(t>18.0)break;
  }
  float pG=pipeGlow(ro,rd,hit?t:12.0);
  if(hit){
    vec3 p=ro+rd*t,n=calcN(p),r=reflect(rd,n);
    float fr=pow(1.0-clamp(dot(n,-rd),0.0,1.0),3.0);
    vec3 base=vec3(0.06,0.14,0.28);
    if(p.x<-0.9)base=vec3(0.12,0.72,0.92);
    else if(p.x>0.9){
      bool isShield=length(p.xz-vec2(2.05,0.0))>0.52;
      base=isShield?mix(vec3(0.10,0.78,0.55),vec3(0.98,0.35,0.48),uTarp):vec3(0.14,0.82,0.55);
    }
    float s1=pow(max(0.0,dot(r,normalize(vec3(-2.0,1.6,1.5)))),26.0);
    col=base*(0.28+0.72*max(0.0,dot(n,normalize(vec3(0.2,1.0,0.8)))))+vec3(0.55,0.94,1.0)*s1+vec3(0.25,0.8,1.0)*fr*0.8;
    if(uTel>0.01)col+=vec3(0.98,0.78,0.2)*0.45*sin(uTel*3.14159)*exp(-abs(p.x-mix(-2.05,2.05,uTel))*2.2);
  }
  vec3 pipeCol=mix(vec3(0.13,0.83,0.93),vec3(0.98,0.75,0.14),clamp(uFrost+uTel*0.7,0.0,1.0));
  col+=vec3(0.13,0.82,0.93)*glow*(1.0+uSpike*1.2)+pipeCol*pG;
  gl_FragColor=vec4(clamp(col,0.0,1.0),1.0);
}`;

const VS_PTS=`precision highp float;
attribute vec3 aBase,aRand;
attribute float aDmg,aKind;
uniform vec2 uRot,uPan;
uniform float uTime,uShred,uZoom,uAspect,uSpike;
varying float vDmg,vShred,vKind;
mat2 rot(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
void main(){
  vec3 p=aBase;
  if(aKind<0.5){
    p=aBase*(1.0+0.03*sin(uTime*1.8+aRand.x*6.28))+aRand*(aDmg*1.35+uShred*2.4);
    p.xz*=rot(uTime*0.22);
  }else{
    float u=fract(aBase.x+uTime*(0.28+uSpike*0.38)*aBase.y);
    float x=mix(-2.05,2.05,u);
    float y=0.0;
    if(aKind<1.5)y=0.58*cos(x*0.72);
    else if(aKind>2.5)y=-0.58*cos(x*0.72);
    p=vec3(x,y+aBase.z*0.04,aRand.z*0.04);
  }
  p.x-=uPan.x;
  p.xz*=rot(uRot.x);p.yz*=rot(uRot.y);
  p.z-=uZoom;
  float sy=p.y/(max(0.4,-p.z)*0.605)+0.12;
  gl_Position=vec4(p.x/(max(0.4,-p.z)*0.605*uAspect),sy,clamp(-p.z/14.0,-1.0,1.0),1.0);
  gl_PointSize=aKind<0.5?max(1.3,3.8/max(1.0,-p.z)):max(2.6,6.8/max(1.0,-p.z));
  vDmg=aDmg;vShred=uShred;vKind=aKind;
}`;

const FS_PTS=`precision highp float;
varying float vDmg,vShred,vKind;
void main(){
  vec2 c=gl_PointCoord*2.0-1.0;
  if(dot(c,c)>1.0)discard;
  vec3 col=vec3(0.22,0.84,0.96);
  if(vKind<0.5){
    col=mix(vec3(0.24,0.84,0.98),vec3(0.98,0.38,0.52),clamp(vDmg,0.0,1.0));
    col=mix(col,vec3(0.26,0.29,0.33),clamp(vShred,0.0,1.0));
  }else if(vKind<1.5)col=vec3(0.42,0.95,1.0);
  else if(vKind<2.5)col=vec3(0.98,0.80,0.22);
  else col=vec3(0.25,0.92,0.65);
  gl_FragColor=vec4(col,vKind<0.5?max(0.2,0.85-vShred*0.65):0.95);
}`;

const ST={sector:'flow',tactical:false,sonic:false,yaw:0.04,pitch:0.24,tYaw:0.04,tPitch:0.24,panX:0,tPanX:0,zoom:5.15,tZoom:5.15,mobX:0,mobY:0,spike:0.25,tel:0,telOn:false,frost:0,frostOn:false,tarp:0,shred:0,lastBytes:0,lastByteTs:0,rateKbs:0,lastFlowId:0,flows:[],peer:null,glOk:false,raf:0,drag:false,lx:0,ly:0};
const C=window.__CORTEX__={version:'14.0',unified:true,glOk:false,glError:0,shaderCount:4,gpuPaused:false,particles:10360,destroyedPct:0,flowsSeen:0};

let actx=null;
function sonic(k){if(!ST.sonic)return;try{if(!actx)actx=new(window.AudioContext||window.webkitAudioContext)();const o=actx.createOscillator(),g=actx.createGain(),t=actx.currentTime;o.type=k==='shred'?'sawtooth':'sine';const f=k==='teleport'?720:k==='frost'?860:k==='heal'?600:k==='shred'?150:460;o.frequency.setValueAtTime(f,t);o.frequency.exponentialRampToValueAtTime(k==='heal'?920:f*0.68,t+0.12);g.gain.setValueAtTime(0.03,t);g.gain.exponentialRampToValueAtTime(0.0001,t+0.13);o.connect(g);g.connect(actx.destination);o.start();o.stop(t+0.14);}catch(_){}}
function toggleSonic(){ST.sonic=!ST.sonic;const b=document.getElementById('btn-sonic');b.textContent=ST.sonic?'🔊 Sonic':'🔇 Sonic';b.classList.toggle('act',ST.sonic);if(ST.sonic)sonic('pulse');}

const N_VSA=10000,N_PKT=360,N_PTS=N_VSA+N_PKT;
const ptsBase=new Float32Array(N_PTS*3),ptsRand=new Float32Array(N_PTS*3),ptsDmg=new Float32Array(N_PTS),ptsKind=new Float32Array(N_PTS);
for(let i=0;i<N_VSA;i++){
  const u=(i+0.5)/N_VSA,phi=Math.acos(1-2*u),th=i*2.3999632,r=0.88+(i%7)*0.032;
  ptsBase[i*3]=r*Math.sin(phi)*Math.cos(th);ptsBase[i*3+1]=r*Math.cos(phi);ptsBase[i*3+2]=r*Math.sin(phi)*Math.sin(th);
  ptsRand[i*3]=Math.sin(i*12.9898);ptsRand[i*3+1]=Math.cos(i*78.233);ptsRand[i*3+2]=Math.sin(i*39.425);
  ptsKind[i]=0;
}
for(let j=0;j<N_PKT;j++){
  const i=N_VSA+j,lane=(j%3)+1;
  ptsKind[i]=lane;
  ptsBase[i*3]=(j/N_PKT);ptsBase[i*3+1]=(j%2===0?1:-1);ptsBase[i*3+2]=Math.sin(j*1.7);
  ptsRand[i*3+2]=Math.cos(j*3.1);
}

const canvas=document.getElementById('gl'),gl=canvas.getContext('webgl',{antialias:true,alpha:false})||canvas.getContext('experimental-webgl');
let pSdf=null,pPts=null,uSdf={},uPts={},bT=null,bB=null,bR=null,bD=null,bK=null,ptsDirty=false;
function cSh(src,tp){const s=gl.createShader(tp);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
function mkP(vs,fs){const p=gl.createProgram();gl.attachShader(p,cSh(vs,gl.VERTEX_SHADER));gl.attachShader(p,cSh(fs,gl.FRAGMENT_SHADER));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));return p;}
function initGL(){
  if(!gl)return;
  try{
    pSdf=mkP(VS_SDF,FS_SDF);pPts=mkP(VS_PTS,FS_PTS);
    ['uRes','uRot','uMob','uPan','uTime','uSpike','uTel','uFrost','uTarp','uZoom'].forEach(k=>uSdf[k]=gl.getUniformLocation(pSdf,k));
    ['uRot','uPan','uTime','uShred','uZoom','uAspect','uSpike'].forEach(k=>uPts[k]=gl.getUniformLocation(pPts,k));
    bT=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bT);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
    bB=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bB);gl.bufferData(gl.ARRAY_BUFFER,ptsBase,gl.STATIC_DRAW);
    bR=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bR);gl.bufferData(gl.ARRAY_BUFFER,ptsRand,gl.STATIC_DRAW);
    bD=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bD);gl.bufferData(gl.ARRAY_BUFFER,ptsDmg,gl.DYNAMIC_DRAW);
    bK=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,bK);gl.bufferData(gl.ARRAY_BUFFER,ptsKind,gl.STATIC_DRAW);
    C.glError=gl.getError();ST.glOk=true;C.glOk=true;
  }catch(e){console.error('WebGL error:',e);document.getElementById('p-fps').textContent='GL ERR';}
}

let lastT=performance.now(),fc=0,fT=lastT;
function loop(now){
  if(ST.tactical)return;
  ST.raf=requestAnimationFrame(loop);
  const dt=Math.min(0.05,(now-lastT)*0.001);lastT=now;
  fc++;if(now-fT>650){document.getElementById('p-fps').textContent=Math.round(fc*1000/(now-fT))+' FPS';fc=0;fT=now;}
  ST.yaw+=(ST.tYaw-ST.yaw)*0.12;ST.pitch+=(ST.tPitch-ST.pitch)*0.12;ST.panX+=(ST.tPanX-ST.panX)*0.12;ST.zoom+=(ST.tZoom-ST.zoom)*0.12;
  ST.spike=Math.max(0.22,ST.spike-dt*0.42);ST.tarp=Math.max(0,ST.tarp-dt*0.55);ST.shred=Math.max(0,ST.shred-dt*0.35);
  if(ST.telOn){ST.tel+=dt*0.85;if(ST.tel>=1){ST.tel=0;ST.telOn=false;ST.spike=0.95;}}
  if(ST.frostOn){ST.frost+=dt*1.05;if(ST.frost>=1){ST.frost=0;ST.frostOn=false;ST.spike=0.9;}}
  if(!gl||!ST.glOk)return;
  const w=canvas.width=Math.max(2,Math.floor(innerWidth*Math.min(1.5,devicePixelRatio||1))),h=canvas.height=Math.max(2,Math.floor(innerHeight*Math.min(1.5,devicePixelRatio||1)));
  gl.viewport(0,0,w,h);
  gl.useProgram(pSdf);
  gl.bindBuffer(gl.ARRAY_BUFFER,bT);
  const lp=gl.getAttribLocation(pSdf,'p');gl.enableVertexAttribArray(lp);gl.vertexAttribPointer(lp,2,gl.FLOAT,false,0,0);
  gl.uniform2f(uSdf.uRes,w,h);gl.uniform2f(uSdf.uRot,ST.yaw,ST.pitch);gl.uniform2f(uSdf.uMob,ST.mobX,ST.mobY);gl.uniform2f(uSdf.uPan,ST.panX,0);
  gl.uniform1f(uSdf.uTime,now*0.001);gl.uniform1f(uSdf.uSpike,ST.spike);gl.uniform1f(uSdf.uTel,ST.tel);gl.uniform1f(uSdf.uFrost,ST.frost);gl.uniform1f(uSdf.uTarp,ST.tarp);gl.uniform1f(uSdf.uZoom,ST.zoom);
  gl.drawArrays(gl.TRIANGLES,0,3);

  if(ptsDirty){gl.bindBuffer(gl.ARRAY_BUFFER,bD);gl.bufferSubData(gl.ARRAY_BUFFER,0,ptsDmg);ptsDirty=false;}
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE);
  gl.useProgram(pPts);
  const lB=gl.getAttribLocation(pPts,'aBase'),lR=gl.getAttribLocation(pPts,'aRand'),lD=gl.getAttribLocation(pPts,'aDmg'),lK=gl.getAttribLocation(pPts,'aKind');
  gl.bindBuffer(gl.ARRAY_BUFFER,bB);gl.enableVertexAttribArray(lB);gl.vertexAttribPointer(lB,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bR);gl.enableVertexAttribArray(lR);gl.vertexAttribPointer(lR,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bD);gl.enableVertexAttribArray(lD);gl.vertexAttribPointer(lD,1,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bK);gl.enableVertexAttribArray(lK);gl.vertexAttribPointer(lK,1,gl.FLOAT,false,0,0);
  gl.uniform2f(uPts.uRot,ST.yaw,ST.pitch);gl.uniform2f(uPts.uPan,ST.panX,0);gl.uniform1f(uPts.uTime,now*0.001);gl.uniform1f(uPts.uShred,ST.shred);gl.uniform1f(uPts.uZoom,ST.zoom);gl.uniform1f(uPts.uAspect,w/h);gl.uniform1f(uPts.uSpike,ST.spike);
  gl.drawArrays(gl.POINTS,0,N_PTS);
  gl.disable(gl.BLEND);

  const cy=Math.cos(ST.yaw),sy=Math.sin(ST.yaw),cp=Math.cos(ST.pitch),sp=Math.sin(ST.pitch),asp=innerWidth/innerHeight;
  const proj=(id,wx,wy,wz,dy)=>{
    const el=document.getElementById(id);if(!el)return;
    const dx=wx-ST.panX,x1=dx*cy-wz*sy,z1=dx*sy+wz*cy,y2=wy*cp-z1*sp,z2=wy*sp+z1*cp-ST.zoom;
    if(z2>-0.4){el.style.display='none';return;}
    el.style.display='block';
    el.style.left=(50+(x1/(-z2*0.605*asp))*50).toFixed(1)+'%';
    el.style.top=(50-(y2/(-z2*0.605)+0.12)*50+dy).toFixed(1)+'%';
  };
  proj('tag-win',-2.05,0.08*Math.sin(now*0.0013),0,-16);
  proj('tag-core',0,0,0,-19);
  proj('tag-sv',2.05,-0.08*Math.sin(now*0.0013),0,-15);
  proj('tag-l1',-0.98,0.56,0,-5);
  proj('tag-l2',1.02,0.48,0,-3);
  proj('tag-l3',-0.98,-0.52,0,4);
}

function focusCam(k){
  if(k==='win'){ST.tPanX=-1.45;ST.tZoom=3.9;ST.mobX=-0.35;ST.mobY=0;}
  else if(k==='core'){ST.tPanX=0;ST.tZoom=3.7;ST.mobX=0;ST.mobY=0;}
  else if(k==='sv'){ST.tPanX=1.45;ST.tZoom=3.9;ST.mobX=0.35;ST.mobY=0;}
  else{ST.tPanX=0;ST.tZoom=5.15;ST.tYaw=0.04;ST.tPitch=0.24;ST.mobX=0;ST.mobY=0;}
}

function fireAnim(op){
  const u=String(op||'').toUpperCase();
  if(u.includes('TELEPORT')){ST.tel=0.01;ST.telOn=true;sonic('teleport');}
  else if(u.includes('FROST')){ST.frost=0.01;ST.frostOn=true;sonic('frost');}
  else if(u.includes('TARPIT')){ST.tarp=1.0;ST.spike=0.85;}
  else if(u.includes('CHMC')){ST.shred=1.0;sonic('shred');}
  else if(u.includes('VSA')){ptsDmg.fill(0);ptsDirty=true;updateVsaPct();sonic('heal');}
  else{ST.spike=0.85;}
}

function updateVsaPct(){
  let c=0;for(let i=0;i<N_VSA;i++)if(ptsDmg[i]>0.5)c++;
  const pct=+(c*100/N_VSA).toFixed(1);C.destroyedPct=pct;
  document.getElementById('vsa-pill').textContent=pct>0?`VSA ${pct}% DAMAGED`:'VSA 100% COHERENT';
  document.getElementById('vsa-pill').className='pill '+(pct>0?'warn':'ok');
  document.getElementById('tc-sub').textContent=pct>0?`Halo ${pct}% Damaged (AVX2 Ready)`:'10,000-bit Halo • Connected';
}

function blastVsa(frac){
  for(let i=0;i<N_VSA;i++)ptsDmg[i]=i<Math.floor(N_VSA*frac)?1.0:0.0;
  ptsDirty=true;ST.spike=0.85;updateVsaPct();
  logOut(`💥 Đã phá ${C.destroyedPct}% mây VSA quanh lõi trung tâm — bấm AVX2 VSA Heal để phục hồi qua cụm.`);
}

async function reconstructVsa(){
  logOut('⚡ Đang chạy VSA AVX2 POPCNT reconstruct 100 trials x 40% damage...');
  try{
    const r=await api('/api/galactic/vsa-query',{method:'POST',body:JSON.stringify({trials:100,corrupt_pct:0.40})});
    fireAnim('VSA');
    logOut(`✅ VSA Reconstructed: ${r.recall_pct}% recall trong ${r.mean_query_ms} ms/query`);
    await pulse();
  }catch(e){logOut('Lỗi VSA: '+e.message);}
}
async function liveTeleport(){
  logOut('🌀 Đang đóng băng WASM checkpoint trên WIN & dịch chuyển sang SVHOME...');
  try{const r=await api('/api/galactic/live-teleport',{method:'POST',body:'{}'});fireAnim('TELEPORT');logOut(`✅ WASM Teleport: ${r.paused_at_step}/${r.total_steps} steps, ${r.checkpoint_wire_bytes}B wire, ${r.teleport_ms}ms, peer=${r.resumed_on_peer}`);await pulse();}
  catch(e){logOut('Lỗi Teleport: '+e.message);}
}
async function liveFrost(){
  logOut('🔐 Đang ký FROST 2-of-3 Ed25519 xuyên 2 máy WIN ⇄ SVHOME...');
  try{const r=await api('/api/galactic/live-frost',{method:'POST',body:'{}'});fireAnim('FROST');logOut(`✅ FROST 2-of-3: 3 pairs OK, peer=${r.peer_signed_live}, tamper_blocked=${r.tamper_rejected} (${r.elapsed_ms}ms)`);await pulse();}
  catch(e){logOut('Lỗi FROST: '+e.message);}
}
async function liveChmc(){
  logOut('💣 Đang chạy thử nghiệm CHMC Active-Matter Cell (Blind Search + ECC Heal + 3-Strike Shred)...');
  try{const r=await api('/api/galactic/live-chmc',{method:'POST',body:'{}'});fireAnim('CHMC');logOut(`✅ CHMC Cell: blind_search=${r.blind_search_encrypted_ok}, heal=${r.bit_rot_self_healed_and_unlocked}, 3_strike_shred=${r.self_shred_after_3_strikes}`);await pulse();}
  catch(e){logOut('Lỗi CHMC: '+e.message);}
}
async function probeTarpit(p){
  try{const r=await api('/api/galactic/tarpit/'+(p||'env/prod.yml').replace(/^\/+/,''));fireAnim('TARPIT');logOut(`🕸️ Tarpit 0-KB [${r.node_name}]: ${r.path}\n${r.content||''}`);await pulse();}
  catch(e){logOut('Lỗi Tarpit: '+e.message);}
}

function toggleTactical(){
  ST.tactical=!ST.tactical;C.gpuPaused=ST.tactical;
  document.body.classList.toggle('tactical',ST.tactical);
  document.getElementById('btn-tac').classList.toggle('act',ST.tactical);
  if(ST.tactical){cancelAnimationFrame(ST.raf);document.getElementById('p-fps').textContent='0% GPU';}
  else{lastT=performance.now();ST.raf=requestAnimationFrame(loop);}
}
function selectSector(id){
  ST.sector=id;const s=SECTORS.find(x=>x.id===id)||SECTORS[0];
  document.getElementById('hud-title').textContent=s.title;document.getElementById('hud-sub').textContent=s.sub;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.id===id));
  document.querySelectorAll('.deck-pane').forEach(p=>p.classList.remove('active'));
  if(s.pane){const pn=document.getElementById(s.pane);if(pn)pn.classList.add('active');}
  document.getElementById('hud-actions').innerHTML=s.acts.map(([l,f])=>`<button onclick="${f}">${l}</button>`).join('');
}
function initTabs(){document.getElementById('sector-tabs').innerHTML=SECTORS.map(s=>`<button class="tab" data-id="${s.id}" onclick="selectSector('${s.id}')">[${s.key}] ${s.id.toUpperCase()}</button>`).join('');selectSector('flow');}

function openPalette(){document.getElementById('spotlight-modal').classList.add('open');const i=document.getElementById('spotlight-input');i.focus();i.select();}
function closePalette(){document.getElementById('spotlight-modal').classList.remove('open');}
function togglePalette(){document.getElementById('spotlight-modal').classList.contains('open')?closePalette():openPalette();}
async function execPalette(){
  const q=(document.getElementById('spotlight-input').value||'').trim(),out=document.getElementById('spotlight-out'),low=q.toLowerCase();
  if(!q)return;
  if(low==='teleport'){closePalette();return liveTeleport();}
  if(low==='frost'){closePalette();return liveFrost();}
  if(low==='vsa'){closePalette();return reconstructVsa();}
  if(low==='tarpit'){closePalette();return probeTarpit('/env/prod.yml');}
  if(low==='bench'){closePalette();return runBench('/api/galactic/benchmark','gal',{wave:'all'});}
  if(low==='zero-gpu'||low==='tactical'){closePalette();return toggleTactical();}
  out.textContent='Đang tìm xuyên cụm (<5 ms)...';
  try{const r=await api('/api/hyperdrive/search?q='+encodeURIComponent(q)+'&limit=12');out.textContent=JSON.stringify(r,null,2);await pulse();}
  catch(e){out.textContent='Lỗi: '+e.message;}
}

const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function logOut(txt){document.getElementById('hud-out').textContent=txt;document.getElementById('tac-out').textContent=txt;}
async function api(url,opt){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...opt});const t=await r.text();let j;try{j=JSON.parse(t);}catch(_){j={raw:t};}if(!r.ok)throw new Error(j.error||r.statusText);return j;}
async function runGet(url){logOut('Reading '+url+'...');try{logOut(JSON.stringify(await api(url),null,2));await pulse();}catch(e){logOut('Lỗi: '+e.message);}}
async function runCmd(url){logOut('Calling '+url+'...');try{logOut(JSON.stringify(await api(url,{method:'POST',body:'{}'}),null,2));await refresh();await pulse();}catch(e){logOut('Lỗi: '+e.message);}}
async function runBench(url,kind,bodyObj={}){
  fireAnim(kind==='gal'?'TELEPORT':'PHANTOM');
  logOut('Đang benchmark '+url+'...');
  try{
    const r=await api(url,{method:'POST',body:JSON.stringify(bodyObj)});
    const items=Object.values(r.ideas||{}).slice(0,29);
    document.getElementById('hud-table').innerHTML='<table class="tbl"><thead><tr><th>Đột phá</th><th>Kết quả</th><th>OK</th></tr></thead><tbody>'+items.map(it=>`<tr><td>${esc(it.name)}</td><td style="color:var(--cy)">${esc(it.after)}</td><td style="color:${it.ok?'#34d399':'#fb7185'}">${it.ok?'PASS':'FAIL'}</td></tr>`).join('')+'</tbody></table>';
    logOut(JSON.stringify({ok:r.ok,verified:r.ideas_verified,total:r.ideas_total,ms:r.total_ms},null,2));
    await pulse();
  }catch(e){logOut('Lỗi Bench: '+e.message);}
}

function renderFlows(flows){
  if(!flows||!flows.length)return;
  const newest=flows[0].id;
  if(newest>ST.lastFlowId&&ST.lastFlowId>0)fireAnim(flows[0].op);
  ST.lastFlowId=Math.max(ST.lastFlowId,newest);
  C.flowsSeen=flows.length;
  document.getElementById('flow-feed').innerHTML=flows.map(f=>`<div class="fline ${esc(f.lane)}"><span><b>[${esc(f.ts)}] ${esc(f.src)} ──► ${esc(f.dst)}</b><br><span style="color:var(--mut)">${esc(f.op)} • ${esc(f.detail)}</span></span><span style="text-align:right;color:${f.ok?'var(--gr)':'var(--rd)'}">${f.bytes}B<br>${f.ms}ms</span></div>`).join('');
}

function applyState(d){
  if(!d)return;
  const cfg=d.config||{},zw=d.zero_weight||{},ph=(d.phantom||{}).client||{},hw=d.hardware||{};
  if(zw.daemon_ram_mb!=null){
    document.getElementById('tw-sub').textContent=`${hw.avx2?'AVX2':''} ${zw.cpu_threads}T • ${zw.daemon_ram_mb} MB`;
    document.getElementById('svg-win').textContent=`RAM ${zw.daemon_ram_mb} MB • ${zw.cpu_threads}T`;
    document.getElementById('tac-zw').textContent=`WIN RAM ${zw.daemon_ram_mb}/80 MB • Free ${zw.host_free_ram_gb} GB • Mode ${ph.mode||'--'}`;
  }
  if(ph.direct_rtt_ms!=null){
    const rtt=ph.direct_rtt_ms.toFixed(2)+'ms';
    document.getElementById('p-tun').textContent='PHANTOM '+rtt;
    document.getElementById('svg-tun').textContent=`${ph.mode||'PHANTOM'} (${rtt} • TX ${Math.round((ph.tx_bytes||0)/1024)}KB / RX ${Math.round((ph.rx_bytes||0)/1024)}KB)`;
    document.getElementById('tag-l1').textContent=`⚡ PHANTOM ${rtt} • TX ${Math.round((ph.tx_bytes||0)/1024)}KB`;
  }
}

async function pulse(){
  if(document.hidden)return;
  try{
    const p=await api('/api/pulse'),zw=p.zero_weight||{},ph=(p.phantom||{}).client||{},peer=p.peer||ST.peer;
    if(peer){ST.peer=peer;}
    const wRam=zw.daemon_ram_mb!=null?zw.daemon_ram_mb+'MB':'--';
    const sRam=(peer&&peer.zero_weight&&peer.zero_weight.daemon_ram_mb!=null)?peer.zero_weight.daemon_ram_mb+'MB':'--';
    document.getElementById('p-ram').textContent=`WIN ${wRam} ⇄ SV ${sRam}`;
    if(zw.daemon_ram_mb!=null){
      document.getElementById('tw-sub').textContent=`${zw.cpu_threads}T • ${wRam}`;
      document.getElementById('svg-win').textContent=`RAM ${wRam} • ${zw.cpu_threads}T`;
      document.getElementById('tac-zw').textContent=`WIN ${wRam}/80 MB • Free ${zw.host_free_ram_gb} GB • Direct ${ph.direct_rtt_ms!=null?ph.direct_rtt_ms.toFixed(2)+'ms':'--'}`;
    }
    if(peer&&peer.online){
      const phw=peer.hardware||{},pzw=peer.zero_weight||{};
      document.getElementById('ts-sub').textContent=`${phw.avx2?'C11 AVX2':'Linux'} ${pzw.cpu_threads||4}T • ${sRam} • Tarpit 0B`;
      document.getElementById('svg-sv').textContent=`RAM ${sRam} • v${peer.version||'12'}`;
      document.getElementById('tac-peer').textContent=`${peer.node_name} ONLINE • RAM ${sRam} • AVX2=${phw.avx2} • probe=${peer.probe_ms}ms`;
    }
    const totB=(ph.tx_bytes||0)+(ph.rx_bytes||0),now=performance.now();
    if(ST.lastByteTs>0&&totB>=ST.lastBytes){
      ST.rateKbs=Math.round(((totB-ST.lastBytes)/1024)/Math.max(0.2,(now-ST.lastByteTs)/1000));
      if(ST.rateKbs>1)ST.spike=Math.min(1.0,ST.spike+0.3);
    }
    ST.lastBytes=totB;ST.lastByteTs=now;
    document.getElementById('p-rate').textContent=`WIRE ${ST.rateKbs} KB/s`;
    if(ph.direct_rtt_ms!=null){
      const rtt=ph.direct_rtt_ms.toFixed(2)+'ms';
      document.getElementById('p-tun').textContent='PHANTOM '+rtt;
      document.getElementById('tag-l1').textContent=`⚡ PHANTOM ${rtt} • TX ${Math.round((ph.tx_bytes||0)/1024)}KB / RX ${Math.round((ph.rx_bytes||0)/1024)}KB`;
      document.getElementById('svg-tun').textContent=`${ph.mode} ${rtt} • TX ${Math.round((ph.tx_bytes||0)/1024)}KB / RX ${Math.round((ph.rx_bytes||0)/1024)}KB`;
    }
    if(p.latest_event)document.getElementById('tac-ev').textContent=`[${p.latest_event.ts_local}] [${p.latest_event.category}] ${p.latest_event.message}`;
    if(p.trinity){
      const t=p.trinity;ST.ks=!!t.kill_switch;
      const g=document.getElementById('p-gov'),b=document.getElementById('btn-ks'),tt=document.getElementById('tac-tri');
      if(g){g.textContent=`GOV ${t.governor_mode} • Q409:${t.tquota_quarantined||0} • Rules:${t.radar_learned_rules||0}`;g.className='pill '+(ST.ks?'warn':'ok');}
      if(b){b.textContent=ST.ks?'🛑 ROI HALTED':'🛡️ ROI Guard';b.className=ST.ks?'act':'';}
      if(tt)tt.textContent=`${t.governor_mode} • Colab:${t.colab_cu||0}CU(q=${t.colab_queued||0}) • VSA:${t.radar_crystals||0} • Rules:${t.radar_learned_rules||0}`;
    }
    if(p.platform){
      const pl=p.platform,el=document.getElementById('p-plat'),l3=document.getElementById('tag-l3');
      const linked=(pl.apps_linked&&pl.apps_linked.length)?pl.apps_linked.join(','):`${pl.apps_total||0}`;
      const vg=pl.vgpu_ready?'GPU:OK':'CPU';
      if(el)el.textContent=`v17 APPS:${linked} • ${vg} • HIT:${pl.egress_hit_pct||0}%`;
      if(l3)l3.textContent=`🚀 APPS(${pl.apps_total||0}): ${linked} • PULSE#${pl.pulse_seq||0} • JOBS:${pl.immortal_jobs||0}`;
    }
    if(p.flows)renderFlows(p.flows);
    if(p.status_etag&&p.status_etag!==_etag)await refresh();
  }catch(_){}
}
async function toggleKillSwitch(){try{const r=await api('/api/trinity/kill-switch',{method:'POST',body:JSON.stringify({active:!ST.ks,reason:ST.ks?'manual_resume':'manual_guard'})});logOut(JSON.stringify(r,null,2));await pulse();}catch(e){logOut('Lỗi ROI: '+e.message);}}
async function refresh(){
  try{
    const h=_etag?{'If-None-Match':_etag}:{};
    const r=await fetch('/api/status',{headers:h});
    if(r.status===304||!r.ok)return;
    const et=r.headers.get('ETag');if(et)_etag=et;
    applyState(await r.json());
  }catch(_){}
}

canvas.addEventListener('pointerdown',e=>{ST.drag=true;ST.lx=e.clientX;ST.ly=e.clientY;canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointerup',()=>ST.drag=false);
canvas.addEventListener('pointermove',e=>{
  const nx=(e.clientX/innerWidth)*2-1,ny=1-(e.clientY/innerHeight)*2;
  ST.mobX=nx*0.38;ST.mobY=ny*0.38;
  if(!ST.drag)return;
  const dx=e.clientX-ST.lx,dy=e.clientY-ST.ly;ST.lx=e.clientX;ST.ly=e.clientY;
  if(e.shiftKey){
    const asp=innerWidth/innerHeight,cy=Math.cos(ST.yaw),sy=Math.sin(ST.yaw),cp=Math.cos(ST.pitch),sp=Math.sin(ST.pitch);
    let hits=0;
    for(let i=0;i<N_VSA;i++){
      if(ptsDmg[i]>0.5)continue;
      const px=ptsBase[i*3]-ST.panX,py=ptsBase[i*3+1],pz=ptsBase[i*3+2],x1=px*cy-pz*sy,z1=px*sy+pz*cy,y2=py*cp-z1*sp,z2=py*sp+z1*cp-ST.zoom;
      const sx=x1/(Math.max(0.4,-z2)*0.605*asp),sy2=y2/(Math.max(0.4,-z2)*0.605)+0.12;
      if((sx-nx)*(sx-nx)+(sy2-ny)*(sy2-ny)<0.04){ptsDmg[i]=1.0;hits++;}
    }
    if(hits){ptsDirty=true;ST.spike=0.85;updateVsaPct();}
    return;
  }
  ST.tYaw+=dx*0.0065;ST.tPitch=Math.max(-0.85,Math.min(0.95,ST.tPitch+dy*0.0065));
});
canvas.addEventListener('wheel',e=>{ST.tZoom=Math.max(2.9,Math.min(7.5,ST.tZoom+Math.sign(e.deltaY)*0.32));},{passive:true});

window.addEventListener('keydown',e=>{
  if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K'||e.code==='Space'||e.key===' ')){e.preventDefault();togglePalette();return;}
  if(e.key==='Escape'){closePalette();return;}
  if(e.key==='Tab'){e.preventDefault();toggleTactical();return;}
  if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;
  if(e.key==='0')selectSector('hyperdrive');
  else if(e.key==='1')selectSector('flow');
  else if(e.key==='x'||e.key==='X')selectSector('galactic');
  else if(e.key==='8')selectSector('ops');
});

initTabs();initGL();
if(window.__INIT_STATE__)applyState(window.__INIT_STATE__);else refresh();
ST.raf=requestAnimationFrame(loop);
setInterval(pulse,1800);
setTimeout(pulse,250);
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
    """Emit self-unpacking DecompressionStream('deflate-raw') capsule (~14 KB gzipped wire)."""
    s_b64 = _deflate_raw_b64(init_state_json)
    boot = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>CHIMERA-HYPER v12.0 OMEGA-GALACTIC — PHANTOM-CORTEX (Packed)</title></head>"
        "<body style='margin:0;background:#02050d;color:#67e8f9;font-family:monospace;padding:20px'>"
        "<!-- CHIMERA-HYPER v2.0 / v14.0 KOLMOGOROV-PACKED -->"
        "Unpacking PHANTOM-CORTEX Unified Topology..."
        "<script>"
        "const _u=x=>new Response(new Blob([Uint8Array.from(atob(x),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();"
        f"(async()=>{{const[h0,s0]=await Promise.all([_u('{_RAW_DEFLATE_B64}'),_u('{s_b64}')]);"
        f"const h=h0.replace('/*__INIT_STATE__*/null',()=>s0).replace('/*__INIT_ETAG__*/\"\"',()=>JSON.stringify({etag_json}));"
        "document.open();document.write(h);document.close();})();"
        "</script></body></html>"
    )
    return boot.encode("utf-8")

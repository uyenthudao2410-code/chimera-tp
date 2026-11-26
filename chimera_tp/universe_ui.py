"""CHIMERA-HYPER v25.0 OMNISCIENCE — Raymarched Volumetric Singularity + 4-Form GPU Morphing Entity."""

from __future__ import annotations

import base64
import zlib

UNIVERSE_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA // OMNISCIENCE v25 — CHIMERA-HYPER v12.0 OMEGA-GALACTIC</title>
<style>
:root{--fg:#e8f4ff;--mu:#6f8db0;--cy:#00f0ff;--gr:#00ffaa;--am:#ffb830;--vi:#b47cff;--rd:#ff4d79;--bd:rgba(0,240,255,.26);--b1:rgba(0,240,255,.14);--bg:rgba(3,10,24,.9);--m:ui-monospace,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#02050c;color:var(--fg);font:10.5px/1.3 var(--m)}
body.tac #stage{display:none!important}body.tac #tactical-deck{display:flex}body.tac{background:#020806;color:#bbf7d0;--cy:#00ffaa;--bd:rgba(0,255,170,.35)}
.mu{color:var(--mu)}.ok{color:var(--gr)}.wn{color:var(--am)}.er{color:var(--rd)}.in{color:var(--cy)}.vi{color:var(--vi)}.cv{width:100%;display:block}.s7{font-size:7.6px}
#stage,#gl,#mesh-svg,#sl,#hud{position:absolute;inset:0}#stage{position:fixed;overflow:hidden;background:#02050c}
#gl{width:100%;height:100%;display:block;cursor:grab;z-index:2}#mesh-svg{width:100%;height:100%;pointer-events:none;z-index:5;overflow:visible}#sl{pointer-events:none;z-index:6}
.sat,.pn,.cc,.pp,.tag,.cb,#cban{border-radius:99px}
.sat{position:absolute;transform:translate(-50%,-50%);pointer-events:auto;cursor:pointer;display:flex;align-items:center;gap:6px;padding:3px 9px 3px 6px;background:var(--bg);border:1px solid var(--sc);box-shadow:0 0 18px -4px var(--sc);transition:transform .16s}
.sat:hover,.sat.on{transform:translate(-50%,-50%) scale(1.1);box-shadow:0 0 24px -2px var(--sc)}.sat i,.pn i,.wt i,.cc i,.dot{border-radius:50%;display:inline-block}
.sat i{width:7px;height:7px;background:var(--sc);box-shadow:0 0 10px var(--sc)}.sat b{font-size:8.6px;letter-spacing:.08em;color:#fff}.sat small{font-size:7.4px;color:var(--sc)}
#hud{pointer-events:none;z-index:10;display:grid;grid-template-rows:46px 1fr 82px;padding:10px 14px;gap:8px}
.g{pointer-events:auto;background:linear-gradient(155deg,rgba(7,18,38,.87),rgba(3,9,22,.82));border:1px solid var(--bd);position:relative;transition:opacity .2s,border-color .18s}
.ch{clip-path:polygon(12px 0,100% 0,100% calc(100% - 12px),calc(100% - 12px) 100%,0 100%,0 12px)}
.g.dim{opacity:.28}.g.lk{border-color:var(--lk,var(--cy))!important;box-shadow:0 0 26px -5px var(--lk,var(--cy));opacity:1!important}
.r,.sb,.wh,.tb{display:flex;align-items:center;gap:5px}.sb,.wh{justify-content:space-between}
#top{display:flex;align-items:center;justify-content:space-between;padding:0 12px;gap:10px;border-radius:8px}
.em{width:28px;height:28px;border-radius:50%;background:radial-gradient(circle at 35% 35%,#00f0ff,#0a2b6e 72%);border:1px solid var(--cy);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;box-shadow:0 0 14px rgba(0,240,255,.55);flex-shrink:0}
.pp{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;background:rgba(0,255,170,.09);border:1px solid rgba(0,255,170,.45);color:var(--gr);font-size:8.2px;font-weight:800;white-space:nowrap}
.dot{width:6px;height:6px;background:var(--gr);box-shadow:0 0 8px var(--gr);transition:transform .12s}.dot.hit{transform:scale(1.8);background:#fff}
#pipe{display:flex;align-items:center;gap:4px;overflow:hidden}.pn{display:flex;align-items:center;gap:5px;padding:3px 8px;border:1px solid var(--bd);background:rgba(4,14,32,.8);cursor:pointer;font-size:8.1px;font-weight:700;white-space:nowrap}
.pn:hover,.pn.on{border-color:var(--pc);background:rgba(0,240,255,.16);color:#fff;box-shadow:0 0 14px -3px var(--pc)}.pn i{width:5px;height:5px;background:var(--pc)}.pa{color:rgba(0,240,255,.5);font-size:8px}
button,input{font:700 8.2px var(--m);color:var(--fg);background:rgba(7,18,38,.86);border:1px solid var(--bd);border-radius:4px;padding:3px 6.5px;outline:none}
button{cursor:pointer}button:hover,.tab.active,.cb button.on{border-color:var(--cy);background:rgba(0,240,255,.22);color:#fff}button.pri{background:linear-gradient(135deg,#0891b2,#2563eb);border-color:var(--cy);color:#fff}button.act{border-color:var(--am);color:var(--am)}button.xs,.tab{padding:2px 5.5px;font-size:7.8px}
#ar{display:grid;grid-template-columns:344px 1fr 356px;grid-template-rows:1fr 1fr;gap:12px;min-height:0}
#w-win{grid-column:1;grid-row:1}#w-sv{grid-column:1;grid-row:2}#w-gpu{grid-column:3;grid-row:1}#w-cmd{grid-column:3;grid-row:2}
#chud{grid-column:2;grid-row:1/3;pointer-events:none;display:flex;flex-direction:column;justify-content:space-between;align-items:center;padding:3px 0}
.cb{pointer-events:auto;display:flex;gap:4px;align-items:center;padding:3px 7px;background:var(--bg);border:1px solid var(--bd)}.cb .sep{width:1px;height:12px;background:var(--bd);margin:0 2px}
#cban{pointer-events:auto;max-width:560px;text-align:center;padding:6px 14px;background:var(--bg);border:1px solid rgba(0,240,255,.38);box-shadow:0 0 22px -8px rgba(0,240,255,.5)}
.wg{padding:8px 11px;display:flex;flex-direction:column;justify-content:space-between;min-height:0;overflow:hidden}
.wh{padding-bottom:4px;margin-bottom:5px;border-bottom:1px solid var(--b1)}.wt{font-size:8.6px;font-weight:800;letter-spacing:.1em;display:flex;align-items:center;gap:6px;color:#fff}.wt i{width:6px;height:6px;background:currentColor;box-shadow:0 0 8px currentColor}
.tag{font-size:7.8px;font-weight:700;padding:1.5px 6px;border:1px solid var(--bd);color:var(--cy)}
.rgw,.mg{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:2px 0 4px}
.rg,.mc{border-radius:6px;background:rgba(3,10,22,.62);border:1px solid var(--b1)}.rg{display:flex;flex-direction:column;align-items:center;padding:4px 2px;cursor:pointer}
.rg:hover,.rg.hi{border-color:var(--cy);background:rgba(0,240,255,.1)}.rg svg{width:62px;height:62px;overflow:visible}.rg-b{fill:none;stroke:rgba(255,255,255,.08);stroke-width:5}.rg-f{fill:none;stroke-width:5;stroke-linecap:round;transform:rotate(-90deg);transform-origin:32px 32px;transition:stroke-dashoffset .4s}
.rg-v{font-size:10.5px;font-weight:800;fill:#fff;text-anchor:middle}.rg-u{font-size:6.8px;fill:var(--mu);text-anchor:middle}.rg-l{font-size:7.5px;color:#b8d4f0;margin-top:2px;font-weight:700}.rg-s{font-size:7.2px;color:var(--mu)}
.mc{padding:4px 6px}.mc small{display:block;font-size:7.1px;color:var(--mu)}.mc b{font-size:10px}
#flow-feed{display:flex;flex-direction:column;gap:4px;overflow-y:auto;flex:1;min-height:0}
.fl{padding:4px 7px;border-radius:4px;border:1px solid var(--b1);border-left:3px solid var(--cy);background:rgba(4,12,26,.8);cursor:pointer}.fl:hover,.fl.sel{border-color:var(--am);background:rgba(255,184,48,.09)}
.fl.compute{border-left-color:var(--am)}.fl.crypto{border-left-color:var(--vi)}.fl.tarpit{border-left-color:var(--rd)}.fl.phantom{border-left-color:var(--gr)}.fb{font-size:7.6px;font-weight:800;padding:1px 4px;border-radius:3px;border:1px solid currentColor}
.tb{flex-wrap:wrap;margin-bottom:4px}.dpn{display:none;flex:1;min-height:0;overflow:auto}.dpn.active{display:flex;flex-direction:column;gap:4px}
.out{background:rgba(2,6,14,.86);border:1px solid var(--bd);border-radius:4px;padding:4px 6px;font-size:8px;color:#b8ffe3;max-height:52px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.tbl{width:100%;border-collapse:collapse;font-size:8px}.tbl th,.tbl td{text-align:left;padding:2px 4px;border-bottom:1px solid var(--b1)}
#dock{display:grid;grid-template-columns:232px 1fr 224px;align-items:center;gap:10px;padding:6px 12px;border-radius:8px}
#c-ch{display:flex;flex-wrap:wrap;gap:4px;justify-content:center}
.cc{display:inline-flex;align-items:center;gap:4px;font-size:7.7px;font-weight:700;padding:2.5px 6px;border:1px solid rgba(0,255,170,.35);background:rgba(0,255,170,.08);color:#c4ffe8;cursor:pointer}
.cc i{width:4.5px;height:4.5px;background:var(--gr)}.cc.off{border-color:rgba(255,77,121,.4);color:var(--rd);opacity:.7}.cc.off i{background:var(--rd)}
.cc:hover,.cc.hi{border-color:#fff;background:rgba(0,240,255,.26);color:#fff;box-shadow:0 0 12px rgba(0,240,255,.5)}
#spotlight-modal{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:72px;background:rgba(2,5,12,.78)}#spotlight-modal.open{display:flex}
.pc{width:min(580px,92vw);background:#050f22;border:1px solid var(--cy);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}
#tactical-deck{position:fixed;inset:10px;z-index:30;display:none;flex-direction:column;gap:8px;overflow:auto;padding:14px;background:#020907;border:1px solid var(--bd);border-radius:10px}#tactical-deck svg text{text-anchor:middle;font-size:10px;fill:#e2e8f0}
.tg2{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.tb2{border:1px solid var(--bd);border-radius:6px;padding:8px;background:#040e0a}
@media(max-width:1180px){html,body{overflow:auto}#ar,#dock{grid-template-columns:1fr}#mesh-svg,#sl{display:none}}
</style>
</head>
<body>
<!-- CHIMERA-HYPER v2.0 / v12.0 OMEGA-GALACTIC / OMNISCIENCE v24 / v25 -->
<div id="stage">
<canvas id="gl"></canvas><svg id="mesh-svg"></svg><div id="sl"></div>
<div id="hud">
<header id="top" class="g">
<div class="r" style="gap:9px"><div class="em">CH</div><div><div style="font:900 11.4px var(--m);letter-spacing:.1em;color:#fff">CHIMERA // OMNISCIENCE v25</div><div class="mu s7">QUANTUM SINGULARITY ENTITY</div></div><span class="pp"><span class="dot" id="hb-d"></span><span id="hb-l">SYNC #0</span></span><canvas id="c-ecg" style="width:90px;height:22px"></canvas></div>
<nav id="pipe"></nav>
<div class="r"><span class="tag ok" id="p-fps">30 FPS</span><button id="b-ks" onclick="act('ks')">ROI</button><button onclick="pip()">PiP</button><button id="b-tac" onclick="tac()">0-GPU</button><button id="b-son" onclick="tSon()">Sonic</button><button class="pri" onclick="oPal()">Ctrl+K</button></div>
</header>
<main id="ar">
<section id="w-win" class="wg g ch" data-org="win">
<div><div class="wh"><span class="wt in"><i></i>01 // WIN-DESKTOP · SILICON</span><span class="tag ok" id="p-gov">ACTIVE</span></div><div id="sil-list" class="rgw"></div><div class="mg"><div class="mc"><small>HYPERDESK</small><b class="ok" id="hd-gb">+0.00 GB</b></div><div class="mc"><small>CRYO / WALL</small><b class="in" id="hd-cw">0 / 0</b></div><div class="mc"><small>ZERO-WEIGHT</small><b class="in" id="w-ram">--/80MB</b></div></div></div>
<div><canvas id="c-bow" class="cv" style="height:60px"></canvas><div class="sb" style="margin-top:4px"><span class="mu s7">WIN ⇄ SVHOME RAM</span><div class="r"><button class="xs" onclick="act('cryo')">Cryo</button><button class="xs" onclick="act('thaw')">Thaw</button><button class="xs" onclick="act('wall')">Wall</button></div></div></div>
</section>
<section id="w-sv" class="wg g ch" data-org="sv">
<div><div class="wh"><span class="wt ok"><i></i>03 // PHANTOM-5MS · SVHOME</span><span class="tag ok" id="p-tun">-- ms</span></div><div id="sv-rg" class="rgw"></div></div>
<div><canvas id="c-kal" class="cv" style="height:90px"></canvas><div class="sb" style="margin-top:4px"><span class="mu s7">APPS: <b class="ok" id="p-pl">--</b> • <b class="vi" id="oai-m">UNIFY</b></span><span class="in s7" id="p-rt">0 KB/s</span></div></div>
</section>
<div id="chud">
<div class="cb" id="cam-b"></div>
<div id="cban"><div class="in" style="font:800 8.8px var(--m);letter-spacing:.06em" id="an-o">SERAPH SINGULARITY • 8,620 NEURAL PARTICLES</div><div class="mu s7" id="an-s">[SERAPH · DNA-LOOM · 4D-CUBE · BLACKHOLE] • phím M để biến hình 3D</div></div>
</div>
<section id="w-gpu" class="wg g ch" data-org="gpu">
<div><div class="wh"><span class="wt vi"><i></i>02 // COLAB ELASTIC · THERMO</span><span class="tag vi" id="p-cu">2350CU</span></div><div id="gp-rg" class="rgw"></div><div class="mg"><div class="mc"><small>REGIME</small><b class="ok" id="th-r">COOL</b></div><div class="mc"><small>GENOME</small><b class="wn" id="om-g">lz4_simd</b></div><div class="mc"><small>POWER</small><b class="wn" id="p-thm">0W</b></div></div></div>
<div><canvas id="c-ph" class="cv" style="height:68px"></canvas><div class="sb" style="margin-top:4px"><span class="mu s7">THERMO ATTRACTOR</span><div class="r"><button class="xs" id="b-thm" onclick="cycThm()">CAP 99%</button><button class="xs" onclick="act('ptx')">PTX</button><button class="xs" onclick="act('emb')">Embed</button><button class="xs" onclick="act('ctrlz')">Ctrl+Z</button></div></div></div>
</section>
<section id="w-cmd" class="wg g ch" data-org="core">
<div class="wh"><span class="wt wn"><i></i>04 // CAUSAL NERVE STREAM</span><span class="tag ok" id="w-ct">LIVE</span></div>
<div class="tb" id="s-tb"></div>
<div id="pane-wire" class="dpn active"><div id="flow-feed">Syncing...</div></div>
<div id="pane-hyperdrive" class="dpn"><div class="r" id="ac-h"></div></div>
<div id="pane-galactic" class="dpn"><div class="r" id="ac-g"></div><div id="h-tb" style="flex:1;overflow:auto"></div></div>
<div id="pane-ops" class="dpn"><div class="r" id="ac-o"></div><div id="t-lg" class="s7" style="overflow:auto;flex:1"></div></div>
<div class="out" id="h-out">OMNISCIENCE v25 ready.</div>
</section>
</main>
<footer id="dock" class="g">
<div><div class="sb"><span class="in s7" style="font-weight:800">NEURAL MATRIX</span><span class="ok s7" id="c-cnt">15/15 ON</span></div><canvas id="c-ht" class="cv" style="height:52px"></canvas></div>
<div id="c-ch"></div>
<div style="display:flex;flex-direction:column;gap:3px;align-items:flex-end"><div class="r" id="q-act"></div><div class="mu s7" id="v-pl">VSA 100% COHERENT</div></div>
</footer>
</div>
</div>
<section id="tactical-deck"><div class="sb" style="border-bottom:1px solid var(--bd);padding-bottom:6px"><b>0-GPU TACTICAL</b><div class="r" id="t-act"></div></div><svg viewBox="0 0 880 56" style="width:100%;height:56px;border:1px solid var(--bd);border-radius:8px;background:#020705"><line x1="160" y1="28" x2="720" y2="28" stroke="#ffb830" stroke-dasharray="6 4"/><text id="sw" x="88" y="32">WIN</text><text id="st" x="440" y="22">PHANTOM</text><text id="ss" x="792" y="32">SVHOME</text></svg><div class="tg2" id="t-gr"></div><div class="out" id="t-out" style="max-height:200px">--</div></section>
<div id="spotlight-modal" onclick="if(event.target===this)cPal()"><div class="pc"><div class="sb"><span class="in">Spotlight (Ctrl+K)</span><button onclick="cPal()">ESC</button></div><div class="r"><input id="spotlight-input" style="flex:1" placeholder="seraph/dna/cube/blackhole/cryo/ptx/bench" onkeydown="if(event.key==='Enter')xPal()"><button class="pri" onclick="xPal()">Run</button></div><div class="out" id="spotlight-out" style="max-height:200px">&lt;5ms search</div></div></div>
<script>
window.__INIT_STATE__=/*__INIT_STATE__*/null;let _et=/*__INIT_ETAG__*/"";
const $=i=>document.getElementById(i),Q=s=>document.querySelectorAll(s),T=(i,v)=>{const e=$(i);if(e)e.textContent=v;},E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),M=Math,cs=M.cos,sn=M.sin,mn=M.min,mx=M.max,psh=(a,v)=>{a.push(v);a.shift();},clm=(v,a,b)=>mx(a,mn(b,v)),bt=(a,c)=>a.map(([l,f])=>`<button${c?' class="'+c+'"':''} onclick="${f}">${l}</button>`).join('');
const C0='#00f0ff',C1='#00ffaa',C2='#ffb830',C3='#b47cff',C4='#ff4d79';
const O={win:[C0,2.55,'w-win','WIN-SILICON','AVX-512 • Cryo','WIN → HyperDesk + Governor (<80MB)'],gpu:[C3,.58,'w-gpu','COLAB-T4','Elastic CUDA','GTX1650 → 4-Tier Pareto → Colab T4'],sv:[C1,3.72,'w-sv','SVHOME-HUB','PHANTOM • AVX2','PHANTOM ⇄ svhome ⇄ Egress + Unify'],core:[C2,5.7,'w-cmd','VSA-CORTEX','Causal Synapse','Quantum Core ⇄ 15 Cartridges']};
const CO={egress_membrane:'sv',pulse:'sv',immortal_jobs:'sv',zygote_canary:'sv',vault_sql:'sv',vgpu_pareto:'gpu',cosmos_entity:'gpu',browser_grid:'win',hyper_desk:'win'};
const P1='/v1/hyperdesk/',P2='/api/galactic/',A={opt:[P1+'optimize','DESK'],cryo:[P1+'cryo','CRYO'],thaw:[P1+'thaw','THAW'],wall:[P1+'silicon-wall','WALL'],ptx:['/v1/vgpu/ptx-bench','PTX',{n:65536,force:true}],emb:['/v1/openai/v1/embeddings','EMBED',{input:['hosi'],dimensions:128}],teleport:[P2+'live-teleport','TELEPORT'],frost:[P2+'live-frost','FROST'],vsa:[P2+'vsa-query','VSA',{trials:100,corrupt_pct:.4}],chmc:[P2+'live-chmc','CHMC'],freeze:['/v1/blackbox/freeze','FREEZE'],ctrlz:['/v1/omega/multiverse/ctrl-z','CTRLZ'],ph:['/api/phantom/connect','PHANTOM']};
const FM=['SERAPH','DNA-LOOM','4D-CUBE','BLACKHOLE'],FD=['Quantum Seraph + 4 Ferrofluid Organs','Twin DNA-Loom (WIN ⇄ SVHOME)','4D Hypercube Tesseract','Gargantua Black Hole + Polar Jets'];
const SH=[
`precision highp float;attribute vec2 q;varying vec2 v;void main(){v=q;gl_Position=vec4(q,0.,1.);}`,
`precision highp float;varying vec2 v;uniform vec2 R;uniform vec4 P,E;uniform float S,F;mat2 r(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}float sm(float a,float b,float k){float h=clamp(.5+.5*(b-a)/k,0.,1.);return mix(b,a,h)-k*h*(1.-h);}float mp(vec3 p){p.yz*=r(-R.y);p.xz*=r(-R.x);float d,t=P.x,b=P.w;if(F>2.5){vec3 q=p;q.xz*=r(t*.7);d=min(length(p)-(.52+b*.03),max(abs(q.y)-.035,abs(length(q.xz)-1.08)-.34));}else if(F>1.5){vec3 q=p;q.xz*=r(t*.5);q.xy*=r(t*.35);vec3 x=abs(q)-vec3(.48+b*.035);d=max(length(max(x,0.))+min(max(x.x,max(x.y,x.z)),0.)-.08,-(min(length(q.xy),min(length(q.yz),length(q.xz)))-.26));}else if(F>.5){float a=p.y*2.8+t*.9,py=max(0.,abs(p.y)-1.3);vec2 c=vec2(cos(a),sin(a))*.52;d=sm(min(length(vec3(p.xz-c,py)),length(vec3(p.xz+c,py)))-.14,length(p)-(.34+b*.04),.28);}else{float w=sin(p.x*5.2+t*2.1)*cos(p.y*5.2-t*1.6)*sin(p.z*5.2+t*1.8)*(.09+b*.045);vec3 g=p;g.xy*=r(t*.4);d=sm(length(p)-(.62+b*.055+w),length(vec2(length(g.xz)-1.02,g.y))-.032,.22);}for(int i=0;i<4;i++){float fi=float(i),a=fi*1.57+t*.32*(mod(fi,2.)<.5?1.:-.8),oR=F>2.5?1.24:1.08,oY=F>2.5?.12:.45;d=sm(d,length(p-vec3(cos(a)*oR,sin(a*1.3+t*.5)*oY,sin(a)*oR))-(.14+b*.025),F>2.5?.18:.34);}return d;}vec3 nm(vec3 p){vec2 e=vec2(.006,-.006);return normalize(e.xyy*mp(p+e.xyy)+e.yyx*mp(p+e.yyx)+e.yxy*mp(p+e.yxy)+e.xxx*mp(p+e.xxx));}void main(){vec3 ro=vec3(0.,0.,P.y),rd=normalize(vec3(v.x*P.z*.55,v.y*.55,-1.));float rv=length(vec2(v.x*P.z*.55,v.y*.55)),b=dot(ro,rd),h=b*b-dot(ro,ro)+3.6;vec3 col=vec3(.006,.016,.038)+vec3(0.,.09,.18)*exp(-rv*2.3)+vec3(.09,.02,.18)*exp(-length(v-vec2(.28,.16))*2.8);if(h>0.){float t=max(.1,-b-sqrt(h)),tm=-b+sqrt(h),ac=0.,ht=0.;vec3 p=ro;for(int i=0;i<26;i++){p=ro+rd*t;float d=mp(p);ac+=exp(-abs(d)*5.8)*.048;if(d<.006){ht=1.;break;}t+=max(d*.82,.028);if(t>tm)break;}vec3 cA=mix(vec3(0.,.92,1.),vec3(1.,.48,.16),clamp(E.w,0.,.65))+vec3(1.,.6,.1)*E.x+vec3(1.,.1,.3)*E.z,cB=mix(vec3(.55,.32,1.),vec3(0.,1.,.68),sin(P.x*.6)*.5+.5)+vec3(.6,.3,1.)*E.y;col+=mix(cA,cB,.45)*ac*(1.15+P.w*.55+S*.4);if(ht>.5){vec3 n=nm(p),V=-rd,l=normalize(vec3(.6,.8,.9));float fr=pow(1.-max(0.,dot(n,V)),2.3),sp=pow(max(0.,dot(reflect(-l,n),V)),28.),ir=sin(dot(n,vec3(3.,4.,5.))+P.x*1.6)*.5+.5;vec3 sf=F>2.5&&length(p)<.62?vec3(.01,.015,.03)+cA*fr*1.4:mix(vec3(.02,.08,.18),mix(cA,cB,ir),.36)+mix(cA,vec3(.92,.98,1.),.5)*fr*1.35+vec3(sp*.9);col=mix(col,sf+cA*P.w*.22,.92);}}gl_FragColor=vec4(col,1.);}`,
`precision highp float;attribute vec3 aB,aR;attribute float aD,aK;uniform vec2 R;uniform vec4 P,M;uniform float S;varying float vD,vSh,vK,vDp,vPh;mat2 rt(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}vec2 cs(float a){return vec2(cos(a),sin(a));}vec3 fm(float m,vec3 s){float u=s.x,v=s.y,w=s.z,t=P.x,b=P.w;if(m<.5){if(u<.58){float a=v*125.66+t*.28,el=u/.58*3.1416-.35,rr=(1.15+.28*w)*(1.+.24*sin(6.*a+t*2.2)*sin(el)+b*.08);vec2 c=cs(a)*rr*sin(el);return vec3(c.x,rr*cos(el)*.82+.12*sin(a*3.+t),c.y);}float am=floor(v*12.),q=(u-.58)/.42,a=am*.5236+q*2.4+sin(t*1.5+am)*.22;vec2 c=cs(a)*(.78+q*1.42+.14*sin(q*7.-t*3.2+am));return vec3(c.x,.3-q*1.28+.24*cos(q*5.-t*2.4+am),c.y);}if(m<1.5){float y=(v-.5)*3.1,a=y*2.9+t*.95+(u<.5?0.:3.1416);if(w<.72){vec2 c=cs(a)*(.84+.08*sin(y*4.+t*2.)+b*.05);return vec3(c.x,y,c.y);}float ry=(floor(v*14.)+.5)/14.*2.8-1.4;vec2 c=cs(ry*2.9+t*.95)*(u-.5)*1.68;return vec3(c.x,ry,c.y);}if(m<2.5){float ei=floor(u*32.),ax=floor(ei/8.),bi=mod(ei,8.);vec4 q=vec4(mod(bi,2.),mod(floor(bi/2.),2.),mod(floor(bi/4.),2.),v)*2.-1.;if(ax<.5)q=q.wxyz;else if(ax<1.5)q=q.xwyz;else if(ax<2.5)q=q.xywz;q.xw*=rt(t*.62);q.yz*=rt(t*.42);q.xz*=rt(t*.25);return q.xyz*(1.85/(2.55-q.w))*(1.+b*.05)+aR*(w-.5)*.05;}if(u<.62){float rr=.78+pow(v,.72)*1.65,a=w*6.283+t*(1.7/pow(rr,1.15));vec2 c=cs(a)*rr;return vec3(c.x,.16*sin(a*2.+t)*exp(-(rr-.9)*1.2)+(u-.31)*.2,c.y);}if(u<.78){float a=w*6.283+t*1.3,rr=.72+(u-.62)/.16*.34;return vec3(cs(a)*rr,.18*sin(a*2.+t));}float sg=v<.5?1.:-1.,q=(u-.78)/.22;vec2 c=cs(w*6.283+t*3.5*sg-q*4.)*(.08+q*.36);return vec3(c.x,sg*(.62+q*1.65),c.y);}void main(){vec3 p;if(aK<1.5){p=mix(fm(M.y,aB),fm(M.z,aB),M.w);if(aK<.5)p+=aR*(aD*1.45+M.x*2.2);else p*=1.06+P.w*.06;}else{float u=aB.x*6.283+P.x*(.62+S*.9)*(aB.y<.5?1.:-1.),v=aB.z*6.283+u*2.;vec2 c=cs(u)*(1.36+.26*sin(v+P.x*1.6));p=vec3(c.x,.68*sin(v+u),c.y);}p.xz*=rt(R.x);p.yz*=rt(R.y);p.z-=P.y;float d=max(.45,-p.z);gl_Position=vec4(p.x/(d*.55*P.z),p.y/(d*.55),clamp(-p.z/16.,-1.,1.),1.);gl_PointSize=aK<.5?max(1.5,3.8/d):(aK<1.5?max(3.2,8.2/d):max(3.8,9.4/d));vD=aD;vSh=M.x;vK=aK;vPh=aB.x;vDp=clamp((p.z+P.y+2.)/4.,.16,1.);}`,
`precision highp float;varying float vD,vSh,vK,vDp,vPh;void main(){vec2 c=gl_PointCoord*2.-1.;float r2=dot(c,c);if(r2>1.)discard;vec3 b=mix(vec3(0.,.92,1.),vec3(.72,.48,1.),smoothstep(.2,.85,vPh)),col=vK<.5?mix(mix(b,vec3(1.,.28,.48),clamp(vD,0.,1.)),vec3(.25,.3,.38),clamp(vSh,0.,1.)):vK<1.5?vec3(.95,1.,1.):vK<2.5?vec3(1.,.78,.22):vK<3.5?vec3(0.,1.,.68):vec3(.78,.52,1.);gl_FragColor=vec4(col,clamp((exp(-r2*4.2)+.35*exp(-r2*1.4))*(vK<.5?max(.2,.82-vSh*.55):.96)*vDp,0.,1.));}`
];
const S={tac:0,son:0,yw:.25,pt:.22,tY:.25,tP:.22,zm:4.35,tZ:4.35,mx:0,my:0,sp:.3,tl:0,fr:0,tp:0,sh:0,hb:0,hbS:0,lb:0,lt:0,rk:0,lf:0,fl:[],si:0,pr:null,ok:0,raf:0,dr:0,lx:0,ly:0,ks:0,wR:32,sR:56,dWR:32,dSR:56,rtt:7.2,kx:7.2,kp:1.6,kk:.42,th:{cpu_pct:18,watts:45},eh:0,egR:0,dlp:0,gt:49,gu:8,vf:2048,vt:4096,cu:2350,cm:'AUTO:SLEEP',oaiM:3,uni:0,apps:[],ct:{},foc:null,bolts:[],f0:0,f1:0,mt:1,tM:'cool_99'};
const C=window.__CORTEX__={version:'25.0',unified:true,torus:true,living:true,hosi:true,raymarch:true,form:'SERAPH',glOk:false,glError:0,shaderCount:4,gpuPaused:false,particles:8620,destroyedPct:0,flowsSeen:0};
const R={w:Array(26).fill(32),s:Array(26).fill(56),ecg:Array(44).fill(0),kr:Array(32).fill(7.2),ke:Array(32).fill(7.2),kk:Array(32).fill(.42),hn:['PHANTOM','COLAB','EGRESS','HYPRDSK','VSA-10K'],ho:['sv','gpu','sv','win','core'],ht:Array.from({length:5},()=>Array(16).fill(.22)),ph:Array.from({length:24},(_,i)=>({x:.22+i*.01,y:.3+sn(i*.3)*.05})),tr:[]};
let ac;const son=f=>{if(S.son)try{ac=ac||new AudioContext();const o=ac.createOscillator(),g=ac.createGain();o.frequency.value=f||520;g.gain.value=.018;o.connect(g);g.connect(ac.destination);o.start();o.stop(ac.currentTime+.09);}catch(_){}},tSon=()=>{S.son=!S.son;$('b-son').classList.toggle('act',S.son);son(680);};
const NV=8000,NT=8620,pB=new Float32Array(NT*3),pR=new Float32Array(NT*3),pD=new Float32Array(NT),pK=new Float32Array(NT),Q6=new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]);
for(let i=0;i<NT;i++){pB.set([(i+.5)/NT,(i*1.6180339)%1,(i*.7548776)%1],i*3);pR.set([sn(i*12.99),cs(i*78.23),sn(i*39.42)],i*3);pK[i]=i<NV?0:(i<8260?1:2+i%3);}
const cv=$('gl'),gl=cv.getContext('webgl',{antialias:false,alpha:false,powerPreference:'low-power'});
let p1,p2,u1={},u2={},bq,b3,b4,b5,b6,dirty=0;
const mkP=(v,f)=>{const p=gl.createProgram();[[v,gl.VERTEX_SHADER],[f,gl.FRAGMENT_SHADER]].forEach(([s,t])=>{const h=gl.createShader(t);gl.shaderSource(h,s);gl.compileShader(h);if(!gl.getShaderParameter(h,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(h));gl.attachShader(p,h);});gl.linkProgram(p);return p;},mkB=(d,y)=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,d,y?gl.DYNAMIC_DRAW:gl.STATIC_DRAW);return b;};
function initGL(){if(!gl)return;try{p1=mkP(SH[0],SH[1]);p2=mkP(SH[2],SH[3]);'R,P,E,S,F'.split(',').forEach(k=>u1[k]=gl.getUniformLocation(p1,k));'R,P,M,S'.split(',').forEach(k=>u2[k]=gl.getUniformLocation(p2,k));bq=mkB(Q6);b3=mkB(pB);b4=mkB(pR);b5=mkB(pD,1);b6=mkB(pK);C.glError=gl.getError();S.ok=C.glOk=true;}catch(e){console.error(e);T('p-fps','GL ERR');}}
function setForm(idx){const n=((idx%4)+4)%4;S.f0=S.f1;S.f1=n;S.mt=0;S.hb=1;S.sp=.95;C.form=FM[n];Q('#cam-b [data-f]').forEach(b=>b.classList.toggle('on',+b.dataset.f===n));sB('core','#00f0ff');sB('gpu','#b47cff');son(520+n*110);T('an-o',`MORPH → ${FM[n]}`);T('an-s',FD[n]);}
const sRg=(id,a)=>$(id).innerHTML=a.map(([p,c,v,u,l,s,o])=>`<div class="rg ${S.foc===o?'hi':''}" data-org="${o}" onclick="fCam('${o}')"><svg viewBox="0 0 64 64"><circle class="rg-b" cx="32" cy="32" r="24"/><circle class="rg-f" cx="32" cy="32" r="24" stroke="${c}" stroke-dasharray="150.8" stroke-dashoffset="${(150.8*(1-clm(p,2,100)/100)).toFixed(1)}" style="filter:drop-shadow(0 0 5px ${c})"/><text class="rg-v" x="32" y="34">${E(v)}</text><text class="rg-u" x="32" y="44">${E(u)}</text></svg><div class="rg-l">${l}</div><div class="rg-s">${E(s)}</div></div>`).join('');
function renRg(){
  const cpu=+S.th.cpu_pct||0,vr=S.vt?M.round((S.vt-S.vf)/S.vt*100):0,rp=S.wR/.8,sp=S.sR/.8;
  sRg('sil-list',[[cpu,C0,`${cpu|0}%`,'CPU','WIN CPU',`${S.th.watts||0}W`,'win'],[rp,S.wR>72?C4:C1,`${S.wR.toFixed(0)}`,'MB/80','DAEMON',`${rp|0}%`,'win'],[clm(S.oaiM*5,22,100),'#7dd3fc',`${S.oaiM}`,S.uni?'UNIFY':'LOC','MODELS',`${S.apps.length} apps`,'core']]);
  sRg('gp-rg',[[S.gt/.85,S.gt>70?C4:C2,`${S.gt.toFixed(0)}°`,'TEMP','GTX1650',`${S.gu|0}%`,'gpu'],[vr,C0,`${vr}%`,'VRAM',`${((S.vt-S.vf)/1024).toFixed(1)}G`,'local','gpu'],[S.cu/25,C3,`${S.cu|0}`,'CU',S.cm,'Colab T4','gpu']]);
  sRg('sv-rg',[[sp,S.sR>75?C4:C1,`${S.sR.toFixed(0)}`,'MB/80','SVHOME',`${sp|0}%`,'sv'],[clm(100-S.kx*1.5,14,98),S.kx>40?C2:C0,`${S.kx.toFixed(1)}`,'MS','PHANTOM','Kalman','sv'],[clm(S.eh,S.egR?24:10,100),C3,`${S.eh|0}%`,'CACHE','EGRESS',`${S.dlp} dlp`,'sv']]);
}
function fOrg(o,cu){
  if(S.foc===o&&!cu&&o)return;S.foc=o;const ov=o&&O[o];
  Q('.wg').forEach(e=>{const h=!!(ov&&e.id===ov[2]);e.classList.toggle('lk',h);e.classList.toggle('dim',!!ov&&!h);if(h)e.style.setProperty('--lk',ov[0]);});
  Q('.sat,.pn').forEach(e=>e.classList.toggle('on',e.dataset.org===o));Q('.cc,.rg').forEach(e=>e.classList.toggle('hi',!!o&&e.dataset.org===o));
  if(cu){T('an-o',cu[0]);T('an-s',cu[1]);}else if(ov){T('an-o',`NEURAL CIRCUIT LOCKED → ${ov[3]}`);T('an-s',ov[5]);}else{const c=S.fl[S.si];if(c){T('an-o',`${FM[S.f1]} · SIGNAL #${c.id} • ${c.op} (${c.ms}ms)`);T('an-s',`${c.src} ══► CORE ══► ${c.dst} • ${c.detail||'pulse'}`);}}
}
const sB=(o,c)=>{S.bolts.push({o,c:c||(O[o]&&O[o][0])||'#00f0ff',t:0});if(S.bolts.length>12)S.bolts.shift();};
function upMesh(now){
  const svg=$('mesh-svg'),rS=$('stage').getBoundingClientRect();if(rS.width<920){svg.innerHTML='';return;}
  const cy0=rS.height/2,cy=cs(S.yw),sy=sn(S.yw),cp=cs(S.pt),sp=sn(S.pt),a=rS.width/mx(1,rS.height),pos={},out=[];
  Object.entries(O).forEach(([k,v])=>{
    const u=v[1]+sn(now*.00045)*.08,wx=1.78*cs(u),wy=1.78*sn(u),wz=.24*sn(u*2+now*.0006),x1=wx*cy-wz*sy,z1=wx*sy+wz*cy,dz=mx(.6,-(wy*sp+z1*cp-S.zm));
    const px=clm((.5+.5*x1/(dz*.55*a))*rS.width,372,rS.width-372),py=clm((.5-.5*(wy*cp-z1*sp)/(dz*.55))*rS.height,96,rS.height-114),el=$('sat-'+k);
    if(el){el.style.left=(px|0)+'px';el.style.top=(py|0)+'px';}pos[k]=[px,py,v[0]];
  });
  const bz=(x1,y1,x2,y2,c,op,w,ph,lbl)=>{
    const m1=(x1+x2)/2,m2=(y1+y2)/2+(y2<cy0?-24:24),d=`M${x1|0} ${y1|0}Q${m1|0} ${m2|0} ${x2|0} ${y2|0}`,t=(ph%1+1)%1,i=1-t,bx=i*i*x1+2*i*t*m1+t*t*x2,by=i*i*y1+2*i*t*m2+t*t*y2,fn=`fill="none" stroke="${c}"`;
    out.push(`<path d="${d}" ${fn} stroke-width="${w+3}" opacity="${(op*.2).toFixed(2)}"/><path d="${d}" ${fn} stroke-width="${w}" opacity="${op.toFixed(2)}" stroke-dasharray="6 5" stroke-dashoffset="${((-now*.04)%22)|0}"/><circle cx="${bx|0}" cy="${by|0}" r="${(w+1.7).toFixed(1)}" fill="#fff" stroke="${c}"/>`);
    if(lbl){const lx=.25*x1+.5*m1+.25*x2,ly=.25*y1+.5*m2+.25*y2-8;out.push(`<circle cx="${x1|0}" cy="${y1|0}" r="4.5" fill="${c}" stroke="#fff"/><circle cx="${x1|0}" cy="${y1|0}" r="${(7+S.hb*4).toFixed(1)}" ${fn} opacity="${(op*.55).toFixed(2)}"/><rect x="${(lx-52)|0}" y="${(ly-9)|0}" width="104" height="14" rx="7" fill="rgba(3,10,24,.9)" stroke="${c}" stroke-width=".8"/><text x="${lx|0}" y="${(ly+1)|0}" fill="${c}" font-size="7.3" font-family="monospace" font-weight="700" text-anchor="middle">${lbl}</text>`);}
  };
  [['win','gpu'],['gpu','core'],['core','sv'],['sv','win']].forEach(([a1,b1],i)=>{const pA=pos[a1],pB=pos[b1];if(pA&&pB)bz(pA[0],pA[1],pB[0],pB[1],pA[2],S.foc&&(S.foc===a1||S.foc===b1)?.65:.14+S.hb*.12,1,now*.00028+i*.25);});
  Object.entries(O).forEach(([k,v],i)=>{
    const wEl=$(v[2]),p0=pos[k];if(!wEl||!p0)return;
    const wr=wEl.getBoundingClientRect(),x1=(k==='win'||k==='sv'?wr.right:wr.left)-rS.left,y1=(k==='win'||k==='gpu'?wr.bottom-26:wr.top+26)-rS.top,hot=S.foc===k,op=hot?.96:S.foc?.14:.54+S.hb*.22;
    bz(x1,y1,p0[0],p0[1],v[0],op,hot?2.1:1.35,now*.00045+i*.22,k==='sv'?`PHANTOM ${S.kx.toFixed(1)}ms`:k==='gpu'?`COLAB ${S.cm}`:k==='win'?`HYPERDESK ${S.wR.toFixed(0)}M`:`${FM[S.f1]} · ${S.fl.length}`);
    S.bolts.forEach(b=>{if(b.o!==k)return;const t=b.t,i1=1-t,m1=(x1+p0[0])/2,m2=(y1+p0[1])/2+(p0[1]<cy0?-24:24);out.push(`<circle cx="${(i1*i1*x1+2*i1*t*m1+t*t*p0[0])|0}" cy="${(i1*i1*y1+2*i1*t*m2+t*t*p0[1])|0}" r="5.5" fill="#fff" stroke="${b.c}" stroke-width="2.4" opacity="${(1-t*.7).toFixed(2)}"/>`);});
  });
  svg.innerHTML=out.join('');
}
function drawCh(now){
  const t=(now||performance.now())*.001;
  const P=(id,fn)=>{const c=$(id);if(!c)return;const r=c.getBoundingClientRect();if(r.width<6||r.height<6)return;const d=mn(2,devicePixelRatio||1),W=M.round(r.width*d),H=M.round(r.height*d);if(c.width!==W||c.height!==H){c.width=W;c.height=H;}const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);x.clearRect(0,0,r.width,r.height);x.font='700 8.2px monospace';const ln=(p,cl,w)=>{x.strokeStyle=cl;x.lineWidth=w||1.5;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.stroke();},dt=(X,Y,rd,cl,s)=>{x.beginPath();x.arc(X,Y,rd,0,6.283);s?(x.strokeStyle=cl,x.lineWidth=1.2,x.stroke()):(x.fillStyle=cl,x.fill());},tx=(s,X,Y,cl)=>{x.fillStyle=cl||'#8eb0d6';x.fillText(s,X,Y);},pg=(p,cl,al)=>{x.fillStyle=cl;x.globalAlpha=al;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.closePath();x.fill();x.globalAlpha=1;};fn(x,r.width,r.height,ln,dt,tx,pg);};
  P('c-ecg',(x,W,H,ln,dt)=>{const m=H*.58,dx=W/(R.ecg.length-1),p=R.ecg.map((v,i)=>[i*dx,m-v*H*.46]);ln(p,C1,1.5);dt(...p[p.length-1],2.4,'#fff');});
  P('c-bow',(x,W,H,ln,dt,tx,pg)=>{const m=H*.52,mh=H*.38;ln([[0,m],[W,m]],'rgba(0,240,255,.2)',1);[[R.w,-1,C0],[R.s,1,C1]].forEach(([a,d,cl])=>{const p=a.map((v,i)=>[i*W/(a.length-1),m+d*mn(mh,v/80*mh)]);pg([[0,m],...p,[W,m]],cl,.18);ln(p,cl);});tx(`WIN ${S.dWR.toFixed(1)}M`,3,9,C0);tx(`SVH ${S.dSR.toFixed(1)}M`,3,H-2,C1);});
  P('c-kal',(x,W,H,ln,dt,tx,pg)=>{const sy=H*.66,kx=(W-10)/(R.ke.length-1),lo=mx(.5,mn(...R.kr)-1.8),hi=mx(lo+4,mx(...R.kr)+1.8),my=v=>sy-8-(v-lo)/(hi-lo)*(sy-20),ep=R.ke.map((v,i)=>[4+i*kx,my(v)]);pg([...ep.map(([X,Y])=>[X,Y-8]),...ep.slice().reverse().map(([X,Y])=>[X,Y+8])],C0,.15);R.kr.forEach((v,i)=>dt(4+i*kx,my(v),1.5,C4));ln(ep,C0,1.6);const lp=ep[ep.length-1];dt(lp[0],lp[1],2.5,'#fff');dt(lp[0],lp[1],5+S.hb*4,C0,1);ln([[0,sy+2],[W,sy+2]],'rgba(0,240,255,.18)',1);ln(R.kk.map((k,i)=>[4+i*kx,H-4-mn(H-sy-12,k*(H-sy-9))]),C3,1.3);tx(`KALMAN ${S.kx.toFixed(2)}ms (±2σ)`,3,9);tx(`K=${S.kk.toFixed(2)}`,3,sy+12);});
  P('c-ph',(x,W,H,ln,dt,tx)=>{const pL=4,pT=11,pw=W-8,ph=H-22;[['rgba(255,77,121,.12)',0,.28],['rgba(255,184,48,.08)',.28,.32],['rgba(0,255,170,.08)',.6,.4]].forEach(([c,y,h])=>{x.fillStyle=c;x.fillRect(pL,pT+ph*y,pw,ph*h);});for(let i=1;i<R.ph.length;i++){const a=R.ph[i-1],b=R.ph[i],al=i/R.ph.length;x.globalAlpha=.16+al*.84;ln([[pL+a.x*pw,pT+(1-a.y)*ph],[pL+b.x*pw,pT+(1-b.y)*ph]],b.y>.72?C4:b.y>.42?C2:C1,1+al*1.4);}x.globalAlpha=1;const lp=R.ph[R.ph.length-1],lx=pL+lp.x*pw,ly=pT+(1-lp.y)*ph,lc=lp.y>.72?C4:lp.y>.42?C2:C1;dt(lx,ly,3.2,lc);x.globalAlpha=.6;dt(lx,ly,5.5+sn(t*4.5)*2.2+S.hb*3,lc,1);x.globalAlpha=1;tx('HOT>72°',pL+2,8.5);tx('COOL<55°',pL+2,H-2);const rt=`${S.gt.toFixed(1)}°C • ${S.gu|0}%`;tx(rt,W-x.measureText(rt).width-4,8.5,'#fff');});
  P('c-ht',(x,W,H,ln,dt,tx)=>{const lw=48,cw=(W-lw-2)/16,rh=H/5;x.font='700 7.6px monospace';R.hn.forEach((nm,r)=>{const hi=S.foc&&R.ho[r]===S.foc,y0=r*rh;tx(nm,1,y0+rh*.78,hi?'#fff':'#7d9ec4');for(let k=0;k<16;k++){const v=mn(1,R.ht[r][k]+M.exp(-M.pow(k-(t*5.5)%16,2)*.48)*.32+(hi?.22:0));x.fillStyle=v>.78?C2:v>.48?C0:v>.26?'#1d4ed8':'#0c1a30';x.globalAlpha=v>.78?.96:v>.48?.72:.5;x.fillRect(lw+k*cw+1,y0+1.2,mx(2,cw-2.2),mx(2,rh-2.4));}});x.globalAlpha=1;});
}
let lT=performance.now(),lR=0,fc=0,fT=lT,_tk=0,_bl=0;
function loop(now){
  if(S.tac||document.hidden){S.raf=0;return;}
  S.raf=requestAnimationFrame(loop);if(now-lR<(_bl?250:33))return;lR=now;
  const dt=mn(.08,(now-lT)*.001);lT=now;
  if(++fc&&now-fT>600){T('p-fps',M.round(fc*1e3/(now-fT))+' FPS');fc=0;fT=now;}
  if(!S.dr)S.tY+=dt*(.18+S.hb*.12);
  S.yw+=(S.tY+S.mx*.16-S.yw)*.09;S.pt+=(S.tP+S.my*.12-S.pt)*.09;S.zm+=(S.tZ-S.zm)*.1;S.dWR+=(S.wR-S.dWR)*.14;S.dSR+=(S.sR-S.dSR)*.14;
  S.mt=mn(1,S.mt+dt*1.15);const sm=S.mt*S.mt*(3-2*S.mt);
  S.sp=mx(.26,S.sp-dt*.42);S.tl=mx(0,S.tl-dt*.6);S.fr=mx(0,S.fr-dt*.6);S.tp=mx(0,S.tp-dt*.55);S.sh=mx(0,S.sh-dt*.38);S.hb=mx(0,S.hb-dt*1.25);
  S.bolts.forEach(b=>b.t+=dt*1.35);S.bolts=S.bolts.filter(b=>b.t<1);
  const bpm=clm(60+S.gu*.35+(S.rtt>15?16:0)+S.hb*18,56,120),ph=(now*.001*bpm/60)%1,card=M.exp(-M.pow((ph-.12)/.055,2))+.55*M.exp(-M.pow((ph-.27)/.075,2))+S.hb*.45;
  if((_tk&1)===0)psh(R.ecg,M.exp(-M.pow((ph-.14)/.028,2))*.95-M.exp(-M.pow((ph-.19)/.024,2))*.45+M.exp(-M.pow((ph-.3)/.055,2))*.32+S.hb*.25);
  if(!gl||!S.ok)return;
  const rc=cv.getBoundingClientRect(),dp=mn(1,devicePixelRatio||1),w=mx(2,M.floor(rc.width*dp)),h=mx(2,M.floor(rc.height*dp));
  if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}
  gl.viewport(0,0,w,h);
  const att=(p,a)=>a.forEach(([n,b,sz])=>{const l=gl.getAttribLocation(p,n);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,sz,gl.FLOAT,false,0,0);}),tS=now*.001,asp=w/h;
  gl.disable(gl.BLEND);gl.useProgram(p1);att(p1,[['q',bq,2]]);gl.uniform2f(u1.R,S.yw,S.pt);gl.uniform4f(u1.P,tS,S.zm,asp,card);gl.uniform4f(u1.E,S.tl,S.fr+(S.cm.includes('WARM')?.5:0),S.tp,mx(0,(S.gt-52)/35));gl.uniform1f(u1.S,S.sp);gl.uniform1f(u1.F,S.f1);
  gl.drawArrays(gl.TRIANGLES,0,6);
  if(dirty){gl.bindBuffer(gl.ARRAY_BUFFER,b5);gl.bufferSubData(gl.ARRAY_BUFFER,0,pD);dirty=0;}
  gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE);gl.useProgram(p2);att(p2,[['aB',b3,3],['aR',b4,3],['aD',b5,1],['aK',b6,1]]);gl.uniform2f(u2.R,S.yw,S.pt);gl.uniform4f(u2.P,tS,S.zm,asp,card);gl.uniform4f(u2.M,S.sh,S.f0,S.f1,sm);gl.uniform1f(u2.S,S.sp);
  gl.drawArrays(gl.POINTS,0,NT);gl.disable(gl.BLEND);
  if((++_tk&1)===0){upMesh(now);drawCh(now);T('v-pl',`${FM[S.f1]} • ${C.destroyedPct?`VSA ${C.destroyedPct}%`:'100% COHERENT'} • ♥ ${bpm|0}`);}
}
function fCam(k){[S.tY,S.tP,S.tZ]={win:[-.52,.18,3.6],gpu:[.58,.32,3.6],sv:[2.6,.18,3.6],core:[0,.05,3.4],over:[.25,.22,4.35]}[k]||[.25,.22,4.35];Q('#cam-b [data-c]').forEach(b=>b.classList.toggle('on',b.dataset.c===k));fOrg(k==='over'?null:k);if(k!=='over')sB(k);}
function fireA(op){const u=String(op||'').toUpperCase();S.hb=1;if(/TELEPORT|DESK|CRYO|PTX/.test(u)){S.tl=1;S.sp=.96;sB('win',C0);sB('gpu',C2);son(740);}else if(/FROST|CART|COLAB|EMBED/.test(u)){S.fr=1;S.sp=.94;sB('gpu',C3);sB('core',C0);son(880);}else if(/TARPIT|DLP/.test(u)){S.tp=1;S.sp=.95;sB('sv',C4);}else if(u.includes('CHMC')){S.sh=1;sB('core',C4);son(170);}else if(u.includes('VSA')){pD.fill(0);dirty=1;C.destroyedPct=0;sB('core',C1);son(620);}else{S.sp=.88;sB('sv',C1);}}
function blast(f){for(let i=0;i<NV;i++)pD[i]=i<M.floor(NV*f)?1:0;dirty=1;C.destroyedPct=+(f*100).toFixed(1);S.sp=.95;S.hb=1;sB('core','#ff4d79');log(`VSA ${C.destroyedPct}% dmg.`);}
const log=t=>{T('h-out',t);T('t-out',t);};
async function api(u,b){const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined),t=await r.text();let j;try{j=JSON.parse(t);}catch(_){j={raw:t};}if(!r.ok)throw new Error(j.error||r.statusText);return j;}
async function rq(u,b,tag){if(tag)fireA(tag);try{const r=await api(u,b);if(tag)pTr(tag.toLowerCase(),JSON.stringify(r).slice(0,46),'ok');log(JSON.stringify(r,null,2));await pulse();return r;}catch(e){log('Err: '+e.message);}}
const act=k=>k==='ks'?rq('/api/trinity/kill-switch',{active:!S.ks,reason:S.ks?'resume':'guard'},'ROI'):A[k]&&rq(A[k][0],A[k][2]||{},A[k][1]);
const cycThm=()=>{S.tM=S.tM==='cool_99'?'eco_85':(S.tM==='eco_85'?'turbo_100':'cool_99');T('b-thm',S.tM==='cool_99'?'CAP 99%':S.tM==='eco_85'?'ECO 85%':'TURBO');rq(P1+'thermostat',{mode:S.tM},'THERMO');};
const tp=()=>rq(P2+'tarpit/env/prod.yml',null,'TARPIT'),togC=n=>n==='connect'?log('Core ON.'):rq('/v1/cartridges',{name:n,enabled:!S.ct[n]},'CART');
async function runB(u,b={}){const r=await rq(u,b,'TELEPORT');if(r&&r.ideas){selSec('galactic');$('h-tb').innerHTML='<table class="tbl"><thead><tr><th>Idea</th><th>Result</th><th>OK</th></tr></thead><tbody>'+Object.values(r.ideas).slice(0,29).map(x=>`<tr><td>${E(x.name)}</td><td class="in">${E(x.after)}</td><td class="${x.ok?'ok':'er'}">${x.ok?'PASS':'FAIL'}</td></tr>`).join('')+'</tbody></table>';}}
function tac(){S.tac=!S.tac;C.gpuPaused=S.tac;document.body.classList.toggle('tac',S.tac);$('b-tac').classList.toggle('act',S.tac);if(S.tac){cancelAnimationFrame(S.raf);S.raf=0;T('p-fps','0% GPU');}else{lT=performance.now();S.raf=requestAnimationFrame(loop);}}
function selSec(id){Q('.tab').forEach(t=>t.classList.toggle('active',t.dataset.id===id));Q('.dpn').forEach(p=>p.classList.remove('active'));const p=$('pane-'+id);if(p)p.classList.add('active');}
const oPal=()=>{$('spotlight-modal').classList.add('open');$('spotlight-input').focus();},cPal=()=>$('spotlight-modal').classList.remove('open');
async function xPal(){const q=($('spotlight-input').value||'').trim(),l=q.toLowerCase();if(!q)return;const fi={seraph:0,dna:1,cube:2,tesseract:2,blackhole:3,singularity:3}[l];if(fi!=null){cPal();return setForm(fi);}if(A[l]){cPal();return act(l);}if(l==='tarpit'){cPal();return tp();}if(l==='bench'){cPal();return runB(P2+'benchmark',{wave:'all'});}if(l==='zero-gpu'||l==='tactical'){cPal();return tac();}try{T('spotlight-out',JSON.stringify(await api('/api/hyperdrive/search?q='+encodeURIComponent(q)+'&limit=12'),null,2));}catch(e){T('spotlight-out','Err: '+e.message);}}
async function pip(){try{const w=await documentPictureInPicture.requestWindow({width:220,height:74}),u=()=>!w.closed&&(w.document.body.innerHTML=`<body style=margin:0;background:#02050c;color:#0ff;font:11px/1.4 monospace;padding:8px><b>CHIMERA v25</b><br>${S.kx.toFixed(1)}ms • ${S.wR|0}⇄${S.sR|0}M • ${S.gt|0}°C`);u();const iv=setInterval(()=>w.closed?clearInterval(iv):u(),1e3);}catch(e){log('PiP:'+e.message);}}
function pTr(k,m,c){R.tr.push([new Date().toTimeString().slice(0,8),k,m,c||'in']);if(R.tr.length>12)R.tr.shift();$('t-lg').innerHTML=R.tr.slice(-7).map(([t,k2,m2,c2])=>`<div><span class="mu">${t}</span> <b class="${c2}">${E(k2)}</b> ${E(m2)}</div>`).join('');}
function selFl(i){S.si=i;S.sp=.88;S.hb=.9;const f=S.fl[i];if(f)sB(f.lane==='compute'?'gpu':f.lane==='crypto'?'core':'sv');renFl(S.fl,1);}
function renFl(fl,keep){if(!fl||!fl.length)return;if(!keep){const n=fl[0].id;if(n>S.lf&&S.lf){fireA(fl[0].op);S.si=0;pTr(fl[0].lane||'wire',`${fl[0].op} ${fl[0].detail||''}`,fl[0].ok?'ok':'er');}S.lf=mx(S.lf,n);S.fl=fl;C.flowsSeen=fl.length;}if(S.si>=S.fl.length)S.si=0;T('w-ct',`${S.fl.length} LIVE`);$('flow-feed').innerHTML=S.fl.slice(0,6).map((f,i)=>`<div class="fl ${E(f.lane)} ${i===S.si?'sel':''}" onclick="selFl(${i})"><div class="sb"><span><span class="fb ${f.lane==='compute'?'wn':f.lane==='crypto'?'vi':f.lane==='tarpit'?'er':'ok'}">${E(f.op)}</span> <span class="mu">${E(f.src)}→${E(f.dst)}</span></span><span class="${f.ok?'ok':'er'}">${f.bytes?f.bytes+'B ':''}${f.ms}ms</span></div><div class="sb mu s7"><span>${E(f.detail||'rpc')}</span><span>${E(f.ts)}</span></div></div>`).join('');if(!S.foc)fOrg(null);}
function sKal(o){const p=S.kp+.08,K=p/(p+1.2);S.kx+=K*(o-S.kx);S.kp=(1-K)*p;S.kk=K;psh(R.kr,o);psh(R.ke,S.kx);psh(R.kk,K);}
function upB(z,ph,init){if(z&&z.daemon_ram_mb!=null){S.wR=z.daemon_ram_mb;if(init)S.dWR=S.wR;else psh(R.w,S.wR);T('w-ram',`${S.wR.toFixed(1)}/80MB`);T('sw',`${S.wR.toFixed(1)}MB`);T('tz',`${S.wR.toFixed(1)}/80MB`);}if(ph&&ph.direct_rtt_ms!=null){S.rtt=ph.direct_rtt_ms;if(init)S.kx=S.rtt;else sKal(S.rtt);T('p-tun',S.rtt.toFixed(2)+'ms');T('st',`${S.rtt.toFixed(1)}ms`);}else if(!init)sKal(S.kx);}
let _pB=0;
async function pulse(){
  if(document.hidden||_pB)return;_pB=1;
  try{
    const p=await api('/api/pulse'),{zero_weight:z={},phantom:ph0={},peer:pr0,platform:pl,trinity:tr}=p,ph=ph0.client||{},pr=pr0||S.pr;if(pr)S.pr=pr;
    S.hbS++;S.hb=mn(1,S.hb+.7);const d=$('hb-d');if(d){d.classList.add('hit');setTimeout(()=>d.classList.remove('hit'),150);}T('hb-l',`SYNC · #${S.hbS}`);
    upB(z,ph,0);if(pr&&pr.zero_weight&&pr.zero_weight.daemon_ram_mb!=null)S.sR=pr.zero_weight.daemon_ram_mb;psh(R.s,S.sR);
    if(pr&&pr.online){T('ss',`${S.sR.toFixed(1)}MB`);T('tp',`${pr.node_name} ${S.sR.toFixed(1)}MB`);}
    const tb=(ph.tx_bytes||0)+(ph.rx_bytes||0),now=performance.now();if(S.lt&&tb>=S.lb){S.rk=M.round((tb-S.lb)/1024/mx(.2,(now-S.lt)/1e3));if(S.rk>1){S.sp=mn(1,S.sp+.38);sB('sv','#00ffaa');}}S.lb=tb;S.lt=now;T('p-rt',`${S.rk} KB/s`);
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
      if(!R.tr.length)pTr('sync',`${S.rtt.toFixed(1)}ms • ${S.oaiM} OAI • ${S.cu|0}CU`,'ok');renRg();
    }
    if(p.flows)renFl(p.flows,0);if(p.status_etag&&p.status_etag!==_et)await refresh();
  }catch(_){}finally{_pB=0;}
}
function sched(){pulse().finally(()=>setTimeout(sched,_bl?2400:750));}
async function refresh(){try{const r=await fetch('/api/status',{headers:_et?{'If-None-Match':_et}:{}});if(r.status===304||!r.ok)return;_et=r.headers.get('ETag')||_et;const j=await r.json();upB(j.zero_weight,(j.phantom||{}).client,1);}catch(_){}}
$('stage').onmousemove=e=>{S.mx=(e.clientX/innerWidth-.5)*2;S.my=(e.clientY/innerHeight-.5)*2;};
$('hud').onmouseover=e=>{const c=e.target.closest('[data-cart]');if(c){const og=c.dataset.org;fOrg(og,[`CARTRIDGE · ${c.dataset.cart.toUpperCase()} → ${(O[og]||O.core)[3]}`,O[og][5]]);return;}const t=e.target.closest('[data-org]');fOrg(t?t.dataset.org:null);};
$('hud').onmouseleave=()=>fOrg(null);
cv.onpointerdown=e=>{S.dr=1;S.lx=e.clientX;S.ly=e.clientY;cv.setPointerCapture(e.pointerId);};cv.onpointerup=()=>S.dr=0;
cv.onpointermove=e=>{if(!S.dr)return;const dx=e.clientX-S.lx,dy=e.clientY-S.ly;S.lx=e.clientX;S.ly=e.clientY;if(e.shiftKey){for(let i=0;i<NV;i++)if(pD[i]<.5&&M.random()<.04)pD[i]=1;dirty=1;let c2=0;for(let i=0;i<NV;i++)if(pD[i]>.5)c2++;C.destroyedPct=+(c2*100/NV).toFixed(1);S.sp=.95;S.hb=1;return;}S.tY+=dx*.007;S.tP=clm(S.tP+dy*.007,-1.1,1.1);};
cv.addEventListener('wheel',e=>{S.tZ=clm(S.tZ+M.sign(e.deltaY)*.28,2.6,6.6);},{passive:true});
window.onresize=()=>{drawCh(performance.now());upMesh(performance.now());};window.onblur=()=>_bl=1;window.onfocus=()=>_bl=0;
document.onvisibilitychange=()=>{if(!document.hidden&&!S.tac&&!S.raf){lT=performance.now();S.raf=requestAnimationFrame(loop);pulse();}};
window.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K'||e.code==='Space')){e.preventDefault();$('spotlight-modal').classList.contains('open')?cPal():oPal();return;}if(e.key==='Escape')return cPal();if(e.key==='Tab'){e.preventDefault();return tac();}if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;if(e.key==='m'||e.key==='M')return setForm(S.f1+1);const k={'1':'wire','0':'hyperdrive','x':'galactic','X':'galactic','8':'ops'}[e.key];if(k)selSec(k);};
const bW=w=>runB(P2+'benchmark',{wave:w});
$('pipe').innerHTML=[['win','WIN-DESKTOP',C0],['sv','PHANTOM ⇄ SVHOME',C1],['core','VSA-10K CORE',C2],['gpu','COLAB T4',C3]].map(([k,l,c],i)=>(i?'<span class="pa">══►</span>':'')+`<span class="pn" style="--pc:${c}" data-org="${k}" onclick="fCam('${k}')"><i></i>${l}</span>`).join('');
$('sl').innerHTML=Object.entries(O).map(([k,v])=>`<div class="sat" id="sat-${k}" style="--sc:${v[0]}" data-org="${k}" onmouseenter="fOrg('${k}')" onmouseleave="fOrg(null)" onclick="fCam('${k}')"><i></i><div><b>${v[3]}</b><br><small>${v[4]}</small></div></div>`).join('');
$('cam-b').innerHTML=FM.map((l,i)=>`<button class="xs ${i===0?'on':''}" data-f="${i}" onclick="setForm(${i})">${l}</button>`).join('')+'<span class="sep"></span>'+[['over','ORBIT'],['win','WIN'],['core','CORE'],['sv','SVH'],['gpu','COLAB']].map(([k,l])=>`<button class="xs ${k==='over'?'on':''}" data-c="${k}" onclick="fCam('${k}')">${l}</button>`).join('');
$('s-tb').innerHTML=[['wire','[1] WIRE'],['hyperdrive','[0] v9'],['galactic','[X] v12'],['ops','[8] OPS']].map(([k,l])=>`<button class="tab ${k==='wire'?'active':''}" data-id="${k}" onclick="selSec('${k}')">${l}</button>`).join('');
$('ac-h').innerHTML=bt([['Bench',"runB('/api/hyperdrive/benchmark')"],['Status',"rq('/api/hyperdrive/status')"],['PHANTOM',"act('ph')"]],'xs');
$('ac-g').innerHTML=bt([['All 29',"bW('all')"],['v10',"bW('v10')"],['v11',"bW('v11')"],['v12',"bW('v12')"]],'xs');
$('ac-o').innerHTML=bt([['Unify',"rq('/v1/unify/status')"],['Colab',"rq('/v1/vgpu/colab/policy')"],['SMI',"rq('/v1/smi')"],['Models',"rq('/v1/openai/v1/models')"],['Freeze',"act('freeze')"]],'xs');
$('q-act').innerHTML=bt([['WASM',"act('teleport')"],['FROST',"act('frost')"],['Blast',"blast(.42)"],['Heal',"act('vsa')"],['Tarpit','tp()'],['CHMC',"act('chmc')"]],'xs');
$('t-act').innerHTML=bt([['Cryo',"act('opt')"],['WASM',"act('teleport')"],['FROST',"act('frost')"],['VSA',"act('vsa')"],['Bench',"bW('all')"]])+'<button class="pri" onclick="tac()">3D</button>';
$('t-gr').innerHTML=[['WIN','tz',''],['SVHOME','tp','ok'],['COLAB','tt2','in'],['EVENT','te','wn']].map(([l,i,c])=>`<div class="tb2"><b>${l}</b><div id="${i}" class="${c}">--</div></div>`).join('');
initGL();if(window.__INIT_STATE__)upB(window.__INIT_STATE__.zero_weight,(window.__INIT_STATE__.phantom||{}).client,1);else refresh();renRg();drawCh(performance.now());S.raf=requestAnimationFrame(loop);setTimeout(sched,100);
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
        "<!doctype html><meta charset=utf-8><title>CHIMERA v25</title>"
        "<body style=margin:0;background:#02050c;color:#0ff;font:12px/1 monospace;padding:12px>"
        "<!-- CHIMERA-HYPER v2.0 -->CHIMERA v25...<script>"
        "const _u=x=>new Response(new Blob([Uint8Array.from(atob(x),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();"
        f"(async()=>{{const[h,s]=await Promise.all([_u('{_RAW_DEFLATE_B64}'),_u('{s_b64}')]);"
        f"document.open();document.write(h.replace('/*__INIT_STATE__*/null',()=>s).replace('/*__INIT_ETAG__*/\"\"',()=>JSON.stringify({etag_json})));document.close()}})();</script>"
    )
    return boot.encode("utf-8")

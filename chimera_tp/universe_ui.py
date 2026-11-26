"""CHIMERA-HYPER v23.0 LIVING ORGANISM CORTEX — Bioluminescent Retina 60FPS Unified Deck (<15KB Gzip)."""

from __future__ import annotations

import base64
import zlib

UNIVERSE_DASHBOARD_HTML = r"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CHIMERA-HYPER v23.0 LIVING CORTEX // CHIMERA-HYPER v12.0 OMEGA-GALACTIC</title>
<style>
:root{--fg:#e6eef9;--mu:#7d95b8;--cy:#22d3ee;--gr:#34d399;--am:#fbbf24;--vi:#a78bfa;--rd:#fb7185;--bd:rgba(56,189,248,.22);--m:ui-monospace,Consolas,monospace}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:radial-gradient(ellipse 75% 55% at 32% 48%,rgba(14,50,92,.3),#02050b 68%);color:var(--fg);font:10.5px/1.3 var(--m);font-variant-numeric:tabular-nums;overflow-x:hidden}
body.tactical #dm{display:none!important}body.tactical #tactical-deck{display:flex}body.tactical{background:#020806;color:#bbf7d0;--cy:#34d399;--bd:rgba(52,211,153,.32)}
.mu{color:var(--mu)}.ok{color:var(--gr)}.wn{color:var(--am)}.er{color:var(--rd)}.in{color:var(--cy)}.vi{color:var(--vi)}.cv{width:100%;display:block}
#dm,.st,#tbx,#flow-feed,#sil-list,.tl,.kvl,.pc,#tactical-deck,.kc,.kp{display:flex;flex-direction:column}
#dm{gap:6px;padding:6px 8px;min-height:100vh;max-width:1920px;margin:0 auto;position:relative}#mesh-svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:18;overflow:visible}
.b,button,input,.fl,.sg,.out,.tb2,.pc,.tg,.hc,.op{border:1px solid var(--bd);border-radius:6px}
.b{background:linear-gradient(180deg,rgba(8,17,34,.95),rgba(4,9,20,.98));border-radius:9px;padding:6px 9px;position:relative;overflow:hidden;transition:border-color .15s,box-shadow .15s}
.b.linked{border-color:var(--lk,var(--cy))!important;box-shadow:0 0 18px -3px var(--lk,var(--cy))}
.r,.tbs,.cg,#tb,#tk,#fb,.hd,.ft,.fs,.sbw,.cb{display:flex;align-items:center;gap:5px}.r,.tbs,.cg,#tb,#tk,#fb{flex-wrap:wrap}#tb,#tk,#fb,.hd,.ft,.fs,.sbw{justify-content:space-between}#tb,#tk,#fb{padding:5px 9px}
.em{width:25px;height:25px;border-radius:7px;background:radial-gradient(circle,#38bdf8,#1d4ed8 76%);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:900;box-shadow:0 0 12px var(--cy);flex-shrink:0}
.kp{align-items:flex-end;cursor:pointer;padding:1px 4px}.kl,.kk{font-size:7.6px;color:var(--mu)}.kv{font-weight:700;font-size:11px}
button,input{font:700 8.5px var(--m);color:var(--fg);background:#091428;padding:3px 6px;outline:none}button{cursor:pointer}button:hover,.cb button.on,.tab.active{border-color:var(--cy);background:rgba(34,211,238,.22);color:#fff}
button.pri{background:linear-gradient(135deg,#0e7490,#2563eb);border-color:var(--cy);color:#fff}button.act{border-color:var(--am);color:var(--am)}button.xs,.tab{padding:2px 5px;font-size:8px}
.lp{display:inline-flex;align-items:center;gap:5px;padding:2px 7px;border-radius:999px;border:1px solid var(--gr);color:var(--gr);font-size:8.1px;font-weight:800;flex-shrink:0}
.dp{width:6px;height:6px;border-radius:50%;background:var(--gr);box-shadow:0 0 7px var(--gr);transition:transform .12s}.dp.hit{transform:scale(1.55);background:#fff}
.tw{flex:1;min-width:120px;overflow:hidden;white-space:nowrap}.tt{display:inline-block;font-size:9px;color:#9bb2d4;animation:sx 42s linear infinite}@keyframes sx{to{transform:translateX(-50%)}}
.g3,.gh,.k3,.tg2{display:grid;gap:6px}.g3{grid-template-columns:1.02fr 1.2fr 1.08fr}.gh{grid-template-columns:1.14fr 1fr;flex:1;min-height:348px}.k3{grid-template-columns:repeat(3,1fr);margin:3px 0}.tg2{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}.st{gap:6px;min-width:0}
.hd{padding-bottom:4px;margin-bottom:5px;border-bottom:1px solid rgba(56,189,248,.14)}.pt{font-size:8.7px;font-weight:800;letter-spacing:.04em;display:flex;align-items:center;gap:5px;white-space:nowrap}
.pd,.cc i,.sg i{width:5px;height:5px;border-radius:50%;display:inline-block;background:currentColor;box-shadow:0 0 6px currentColor}.tg{font-size:8px;font-weight:700;padding:1px 6px;border-radius:999px;color:var(--mu);white-space:nowrap}
.bn{font-size:21px;font-weight:800;line-height:1.05;margin:1px 0 3px}.cg{gap:3px;margin-top:4px}
.cc{display:inline-flex;align-items:center;gap:4px;font-size:7.6px;font-weight:700;padding:2px 5px;border-radius:4px;border:1px solid rgba(52,211,153,.4);background:rgba(52,211,153,.09);color:#a7f3d0;cursor:pointer}
.cc.off{border-color:rgba(251,113,133,.4);background:rgba(251,113,133,.1);color:var(--rd);opacity:.72}.cc:hover,.cc.hi,.sg:hover,.sg.hi{border-color:var(--cy);background:rgba(34,211,238,.18);color:#fff}
#tbx{justify-content:space-between;min-height:348px}#tst{position:relative;flex:1;min-height:266px;border-radius:7px;overflow:hidden;background:radial-gradient(circle,rgba(12,35,68,.5),#02060e 76%)}
#gl{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab}
.op,.hc,.cb{position:absolute;z-index:5}.op{transform:translate(-50%,-50%);padding:2px 6px;border-radius:999px;background:rgba(3,9,20,.88);font-size:8px;font-weight:700;color:#e2e8f0;cursor:pointer;white-space:nowrap}.op:hover,.op.on{border-color:var(--am);color:#fff;box-shadow:0 0 10px var(--am)}
.hc{padding:3px 6px;background:rgba(3,9,20,.84);font-size:8px;font-weight:700;pointer-events:none;z-index:4}.cb{top:6px;left:50%;transform:translateX(-50%);gap:3px;z-index:6}
.sb{margin-top:5px;padding:4px 8px;border-radius:6px;border:1px solid var(--bd);background:rgba(34,211,238,.07)}
#flow-feed{gap:4px;max-height:164px;overflow-y:auto}.fl{padding:4px 7px;border-left:3px solid var(--cy);background:#060d1b;cursor:pointer}.fl.sel{border-color:var(--am)}
.fl.compute{border-left-color:var(--am)}.fl.crypto{border-left-color:var(--vi)}.fl.tarpit{border-left-color:var(--rd)}.fl.phantom{border-left-color:var(--gr)}.fb{font-size:7.8px;font-weight:800;padding:1px 4px;border-radius:3px;border:1px solid currentColor}.fs{font-size:8px;color:var(--mu)}
.tbs{gap:3px;margin-bottom:4px}.dpn{display:none}.dpn.active{display:block}
#sil-list{gap:4px;margin-bottom:4px}.sg{display:grid;grid-template-columns:92px 1fr 122px;align-items:center;gap:6px;padding:3px 6px;background:#040a16;cursor:pointer;font-size:8.1px;font-weight:700}
.sg-l{color:#b7cae6;display:flex;align-items:center;gap:5px;white-space:nowrap}.sg-tr{height:8px;border-radius:999px;background:#142642;overflow:hidden}
.sg-f{height:100%;border-radius:999px;transition:width .35s ease;position:relative}.sg-f::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);animation:sh 2.4s linear infinite}@keyframes sh{0%{transform:translateX(-100%)}to{transform:translateX(120%)}}
.sg-v{text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.out{background:#02050c;padding:4px 6px;font-size:8.2px;color:#d1fae5;max-height:58px;overflow:auto;white-space:pre-wrap;word-break:break-word;margin-top:4px}
.tbl{width:100%;border-collapse:collapse;font-size:8.1px;margin-top:4px}.tbl th,.tbl td{text-align:left;padding:2px 4px;border-bottom:1px solid var(--bd)}
.tl{gap:2px;height:108px;overflow:hidden;font-size:8.2px}.tr{display:grid;grid-template-columns:46px 40px 1fr;gap:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kvl{gap:2px;margin-top:4px;font-size:8.2px}.kvr{display:flex;justify-content:space-between;gap:8px;border-bottom:1px dashed var(--bd);padding-bottom:2px}.kvr:last-child{border:none}
#spotlight-modal{position:fixed;inset:0;z-index:50;display:none;align-items:flex-start;justify-content:center;padding-top:64px;background:rgba(2,5,12,.8)}#spotlight-modal.open{display:flex}
.pc{width:min(580px,92vw);background:#061022;border-color:var(--cy);padding:12px;gap:8px}
#tactical-deck{position:fixed;inset:8px;z-index:25;display:none;gap:8px;overflow:auto;padding:12px;background:#020907;border:1px solid var(--bd);border-radius:10px}#tactical-deck svg text{text-anchor:middle;font-size:10px;fill:#e2e8f0}.tb2{padding:8px;background:#040e0a}
@media(max-width:1020px){.g3,.gh{grid-template-columns:1fr}#mesh-svg{display:none}}
</style>
</head>
<body>
<!-- CHIMERA-HYPER v2.0 / v12.0 OMEGA-GALACTIC / v23.0 LIVING ORGANISM CORTEX -->
<div id="dm"><svg id="mesh-svg"></svg>
<header id="tb" class="b">
  <div class="r" style="gap:8px"><div class="em">CH</div><div><div style="font-weight:800;font-size:12px;color:#fff">CHIMERA-HYPER v23 // LIVING ORGANISM CORTEX</div><div class="mu" style="font-size:8.2px">WIN GTX1650 ⇄ PHANTOM-5MS ⇄ SVHOME ⇄ COLAB ELASTIC • 15 CARTRIDGES</div></div></div>
  <div class="r" style="gap:9px" id="kpi-bar"></div>
  <div class="r"><button id="b-ks" onclick="act('ks')">ROI</button><button onclick="pip()">PiP</button><button id="b-tac" onclick="tac()">0-GPU</button><button id="b-son" onclick="tSon()">Sonic</button><button class="pri" onclick="oPal()">Ctrl+K</button></div>
</header>
<div id="tk" class="b"><span class="lp"><span class="dp" id="hb-dot"></span><span id="hb-lbl">BEAT #0</span></span><div class="tw"><span class="tt" id="tkt">LIVING ORGANISM SYNCING...&nbsp;&nbsp;</span></div><div class="r" id="q-act"></div></div>
<div class="g3">
  <section class="b" id="p-hd" data-org="win"><div class="hd" data-h="ok|HYPERDESK · MEMORY|ACTIVE|ok"></div><div class="sbw"><div class="bn ok" id="hd-gb">+0.00 GB</div><div class="r"><button class="xs" onclick="act('cryo')">Cryo</button><button class="xs" onclick="act('thaw')">Thaw</button><button class="xs" onclick="act('wall')">Wall</button></div></div><div class="k3" data-k="CRYO:hd-c:|WALL:hd-w:in|ORPHANS:hd-o:wn"></div><canvas id="c-bow" class="cv" style="height:54px"></canvas></section>
  <section class="b" id="p-osc" data-org="sv"><div class="hd" data-h="in|PHANTOM-5MS · WAVE|0 KB/s|in|p-rt"></div><canvas id="c-osc" class="cv" style="height:76px"></canvas><div class="k3" data-k="EGRESS HIT:eg-h:ok|OPENAI UNIFY:oai-m:vi|DLP:eg-d:er"></div></section>
  <section class="b" id="p-mat" data-org="core"><div class="hd" data-h="wn|CARTRIDGE MATRIX|15/15 ON|ok|c-cnt"></div><canvas id="c-ht" class="cv" style="height:64px"></canvas><div class="cg" id="c-ch"></div></section>
</div>
<div class="gh">
  <section class="b" id="tbx">
    <div class="hd" data-h="in|NEURAL ORGANISM · VSA-10K|VSA 100%|ok|v-pl"></div>
    <div id="tst"><canvas id="gl"></canvas><div class="cb" id="cam-b"></div><div id="org-pills"></div><div class="hc" style="top:30px;right:7px"><div class="in" id="tc-s">VSA-10K • 10,620 PTS</div><div class="mu" id="sp-s">BPM 64</div></div><div class="hc" style="bottom:7px;right:7px"><div class="wn" id="an-o">SYNAPSE → LIVE</div><div class="mu" id="an-s">8 ORGANS COUPLED</div></div></div>
    <div class="sb"><div class="sbw" style="font-size:8.4px;font-weight:800"><span class="in" id="sg-h">ORGANISM LIVE</span><span class="ok" id="sg-st">ALL 8 ORGANS LIVE</span></div><div class="mu" style="font-size:8px" id="sg-b">Hover Organ/Chip/Gauge = khóa tia thần kinh • Shift+Drag phá VSA</div></div>
  </section>
  <div class="st">
    <section class="b" id="p-wire" data-org="sv"><div class="hd" data-h="ok|LIVE CAUSAL WIRE · WIN ⇄ SVHOME|STREAM||w-ct"></div><div id="flow-feed">Syncing...</div></section>
    <section class="b" id="p-sil" data-org="gpu" style="flex:1;display:flex;flex-direction:column"><div class="hd" style="margin-bottom:4px"><span class="pt"><span class="pd vi"></span><span id="h-ti">SILICON TELEMETRY &amp; COMMAND</span></span><span class="tg ok">COUPLED</span></div><div class="tbs" id="s-tb"></div><div id="pane-silicon" class="dpn active"><div id="sil-list"></div></div><div id="pane-hyperdrive" class="dpn">v9.0 HYPERDRIVE</div><div id="pane-galactic" class="dpn">v12.0 OMEGA-GALACTIC</div><div class="r" id="h-ac" style="margin-top:4px"></div><div id="h-tbl" style="max-height:70px;overflow:auto"></div><div class="out" id="h-out">LIVING CORTEX v23 • 0.8s live pulse + synaptic mesh.</div></section>
  </div>
</div>
<div class="g3">
  <section class="b" id="p-kal" data-org="sv"><div class="hd" data-h="in|KALMAN RTT|±2σ FILTER|in"></div><canvas id="c-kal" class="cv" style="height:108px"></canvas></section>
  <section class="b" id="p-bb" data-org="core"><div class="hd"><span class="pt"><span class="pd wn"></span>BLACKBOX TRACE</span><div class="r"><button class="xs" onclick="act('freeze')">Freeze</button><span class="tg ok" id="bb-t">0-DISK</span></div></div><div class="tl" id="t-lg"></div></section>
  <section class="b" id="p-th" data-org="gpu"><div class="hd"><span class="pt"><span class="pd ok"></span>THERMO ATTRACTOR</span><div class="r"><button class="xs" onclick="act('ctrlz')">Ctrl+Z</button><span class="tg ok" id="th-r">COOL</span></div></div><canvas id="c-ph" class="cv" style="height:76px"></canvas><div class="kvl"><div class="kvr"><span class="mu">autopoietic dna</span><span class="wn" id="om-g">lz4_simd</span></div><div class="kvr"><span class="mu">apps / yield</span><span class="in" id="p-pl">--</span></div></div></section>
</div>
<footer id="fb" class="b" style="font-size:8.2px"><span id="f-l">WIN ⇄ PHANTOM-5MS ⇄ SVHOME ⇄ COLAB</span><span class="mu">Tab=0-GPU • Ctrl+K=Spotlight</span></footer>
</div>
<section id="tactical-deck"><div class="sbw" style="border-bottom:1px solid var(--bd);padding-bottom:6px"><b>CHIMERA // 0-GPU TACTICAL</b><div class="r" id="t-act"></div></div><svg viewBox="0 0 880 72" style="width:100%;height:72px;border:1px solid var(--bd);border-radius:8px;background:#020705"><rect x="16" y="8" width="160" height="56" rx="8" fill="#06141a" stroke="#22d3ee"/><text x="96" y="30" fill="#7dd3fc">WIN</text><text id="sw" x="96" y="48">--</text><line x1="176" y1="36" x2="704" y2="36" stroke="#fbbf24" stroke-width="2" stroke-dasharray="6 4"/><circle cx="440" cy="36" r="18" fill="#091529" stroke="#fbbf24" stroke-width="2"/><text x="440" y="40" fill="#fbbf24">VSA</text><text id="st" x="440" y="13" fill="#22d3ee">PHANTOM</text><rect x="704" y="8" width="160" height="56" rx="8" fill="#061a14" stroke="#34d399"/><text x="784" y="30" fill="#34d399">SVHOME</text><text id="ss" x="784" y="48">--</text></svg><div class="tg2" id="t-grid"></div><div class="out" id="t-out" style="max-height:200px">--</div></section>
<div id="spotlight-modal" onclick="if(event.target===this)cPal()"><div class="pc"><div class="sbw"><span class="in" style="font-weight:800">Spotlight (Ctrl+K)</span><button onclick="cPal()">ESC</button></div><div class="r"><input id="spotlight-input" style="flex:1" placeholder="Symbol / cryo / ptx / emb / teleport / frost / vsa / tarpit / bench / zero-gpu" onkeydown="if(event.key==='Enter')xPal()"><button class="pri" onclick="xPal()">Run</button></div><div class="out" id="spotlight-out" style="max-height:200px">Cluster search &lt;5ms.</div></div></div>
<script>
window.__INIT_STATE__=/*__INIT_STATE__*/null;let _et=/*__INIT_ETAG__*/"";
const $=i=>document.getElementById(i),Q=s=>document.querySelectorAll(s),T=(i,v)=>{const e=$(i);if(e)e.textContent=v;},E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),M=Math,cs=M.cos,sn=M.sin,mn=M.min,mx=M.max,psh=(a,v)=>{a.push(v);a.shift();},clm=(v,a,b)=>mx(a,mn(b,v)),bt=(a,c)=>a.map(([l,f])=>`<button${c?' class="'+c+'"':''} onclick="${f}">${l}</button>`).join('');
const O={win:['#34d399',0,['p-hd','p-sil'],'WIN-SILICON'],core:['#22d3ee',1.57,['p-mat','p-bb','p-sil'],'VSA-10K'],sv:['#38bdf8',3.14,['p-osc','p-wire','p-kal'],'SVHOME-HUB'],gpu:['#a78bfa',4.71,['p-sil','p-th','p-mat'],'COLAB-T4']};
const CO={egress_membrane:'sv',pulse:'sv',immortal_jobs:'sv',zygote_canary:'sv',vault_sql:'sv',vgpu_pareto:'gpu',cosmos_entity:'gpu',browser_grid:'win',hyper_desk:'win'};
const P1='/v1/hyperdesk/',P2='/api/galactic/',A={opt:[P1+'optimize','DESK'],cryo:[P1+'cryo','CRYO'],thaw:[P1+'thaw','THAW'],wall:[P1+'silicon-wall','WALL'],ptx:['/v1/vgpu/ptx-bench','PTX',{n:65536,force:true}],emb:['/v1/openai/v1/embeddings','EMBED',{input:['hi'],dimensions:128}],teleport:[P2+'live-teleport','TELEPORT'],frost:[P2+'live-frost','FROST'],vsa:[P2+'vsa-query','VSA',{trials:100,corrupt_pct:.4}],chmc:[P2+'live-chmc','CHMC'],freeze:['/v1/blackbox/freeze','FREEZE'],ctrlz:['/v1/omega/multiverse/ctrl-z','CTRLZ'],ph:['/api/phantom/connect','PHANTOM']};
const SEC=[['silicon','1','pane-silicon','SILICON TELEMETRY',[['Cryo',"act('opt')"],['PTX',"act('ptx')"],['Embed',"act('emb')"],['SMI',"rq('/v1/smi')"]]],['flow','2','','CAUSAL PRIMITIVES',[['WASM',"act('teleport')"],['FROST',"act('frost')"],['Blast',"blast(.42)"],['Heal',"act('vsa')"],['Tarpit','tp()'],['CHMC',"act('chmc')"],['Models',"rq('/v1/openai/v1/models')"]]],['hyperdrive','0','pane-hyperdrive','v9 HYPERDRIVE',[['Bench',"runB('/api/hyperdrive/benchmark')"],['Status',"rq('/api/hyperdrive/status')"],['PHANTOM',"act('ph')"]]],['galactic','X','pane-galactic','v12 GALACTIC',[['All29',"runB(P2+'benchmark',{wave:'all'})"],['v10',"runB(P2+'benchmark',{wave:'v10'})"],['v11',"runB(P2+'benchmark',{wave:'v11'})"],['v12',"runB(P2+'benchmark',{wave:'v12'})"]]],['ops','8','','UNIFY & OPS',[['Unify',"rq('/v1/unify/status')"],['Colab',"rq('/v1/vgpu/colab/policy')"],['Bench7',"runB('/api/omega/benchmark')"]]]];
const SH=[`precision highp float;attribute vec3 aP,aM;uniform vec2 uR;uniform float uT,uZ,uA,uS,uW,uG,uB;varying float vA,vK,vH,vW;mat2 rt(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}void main(){vec3 p=aP;if(aM.y<2.5)p*=1.+uB*.05+.018*sin(uT*2.1+aM.x*3.)*(1.+uS);vH=exp(-pow((length(p.xy)-.66)*2.3,2.));p.xz*=rt(uR.x);p.yz*=rt(uR.y);p.z-=uZ;float d=max(.45,-p.z);gl_Position=vec4(p.x/(d*.58*uA),p.y/(d*.58),clamp(-p.z/14.,-1.,1.),1.);vW=exp(-pow(mod(aM.x-uW+6.283,6.283)-3.14,2.)*2.8)*uG;vA=aM.z*(.4+.6*clamp((p.z+uZ+1.5)/3.1,0.,1.))*(1.+uS*.55+vW*1.3+uB*.34);vK=aM.y;}`,`precision highp float;uniform float uTl,uFr,uTp,uTh;varying float vA,vK,vH,vW;void main(){vec3 c=vK<.5?vec3(.14,.86,.98):vK<1.5?vec3(.84,.96,1.):vK<2.5?vec3(.2,.9,.66):vK<3.5?vec3(.66,.54,.99):vec3(.24,.44,.66);c=mix(c,vec3(.99,.56,.22),clamp(uTh,0.,.55));c=mix(c,vec3(.96,1.,1.),clamp(vH*.52+vW*.42,0.,.85));if(uTl>.02)c=mix(c,vec3(.99,.78,.2),uTl*.58);if(uFr>.02)c=mix(c,vec3(.72,.52,1.),uFr*.62);if(uTp>.02)c=mix(c,vec3(.98,.36,.5),uTp*.65);gl_FragColor=vec4(c,clamp(vA,.03,.94));}`,`precision highp float;attribute vec3 aB,aRn;attribute float aD,aK;uniform vec2 uR;uniform float uT,uSh,uZ,uA,uS,uB;varying float vD,vSh,vK,vDp;mat2 rt(float a){return mat2(cos(a),-sin(a),sin(a),cos(a));}void main(){vec3 p=aB;if(aK<.5){p=aB*(1.+uB*.035+.022*sin(uT*1.9+aRn.x*6.28))+aRn*(aD*1.25+uSh*2.1);p.xy*=rt(uT*.11);}else if(aK>1.5){float u=aB.x+uT*(.48+uS*.75)*aB.y,v=aB.z+u*2.4,r=.52+.09*sin(v*2.+uT);p=vec3((1.08+r*cos(v))*cos(u),(1.08+r*cos(v))*sin(u),r*sin(v));}else p*=1.+uB*.055;p.xz*=rt(uR.x);p.yz*=rt(uR.y);p.z-=uZ;float d=max(.45,-p.z);gl_Position=vec4(p.x/(d*.58*uA),p.y/(d*.58),clamp(-p.z/14.,-1.,1.),1.);gl_PointSize=aK<.5?max(1.2,3.4/d):(aK<1.5?max(2.6,6.8/d):max(3.,7.8/d));vD=aD;vSh=uSh;vK=aK;vDp=clamp((p.z+uZ+1.5)/3.2,.16,1.);}`,`precision highp float;varying float vD,vSh,vK,vDp;void main(){vec2 c=gl_PointCoord*2.-1.;float r2=dot(c,c);if(r2>1.)discard;vec3 col=vK<.5?mix(mix(vec3(.28,.88,.99),vec3(.98,.36,.52),clamp(vD,0.,1.)),vec3(.28,.32,.38),clamp(vSh,0.,1.)):vK<1.5?vec3(.95,.99,1.):vK<2.5?vec3(.99,.78,.22):vK<3.5?vec3(.22,.94,.68):vec3(.74,.56,1.);gl_FragColor=vec4(col,exp(-r2*3.6)*(vK<.5?max(.18,.8-vSh*.55):.98)*vDp);}`];
const S={tac:0,son:0,yw:.35,pt:.32,tY:.35,tP:.32,zm:3.65,tZ:3.65,sp:.26,tl:0,fr:0,tp:0,sh:0,hb:0,hbS:0,lb:0,lt:0,rk:0,lf:0,fl:[],si:0,pr:null,ok:0,raf:0,dr:0,lx:0,ly:0,ks:0,wR:32,sR:56,dWR:32,dSR:56,rtt:7.5,kx:7.5,kp:1.6,kk:.42,th:{cpu_pct:18,watts:45},eh:0,egR:0,dlp:0,gt:49,gu:8,vf:2048,vt:4096,cu:2350,cm:'AUTO:SLEEP',oaiM:3,uni:0,apps:[],ct:{},foc:null};
const C=window.__CORTEX__={version:'23.0',unified:true,torus:true,living:true,glOk:false,glError:0,shaderCount:4,gpuPaused:false,particles:10620,destroyedPct:0,flowsSeen:0};
const R={w:Array(24).fill(32),s:Array(24).fill(56),o:Array.from({length:36},(_,i)=>sn(i*.26)*.18),kr:Array(28).fill(7.5),ke:Array(28).fill(7.5),kk:Array(28).fill(.42),hn:['PHANTOM','COLAB','EGRESS','HYPRDSK','UNIFY','COSMOS','VSA-10K'],ho:['sv','gpu','sv','win','core','gpu','core'],ht:Array.from({length:7},()=>Array(16).fill(.22)),ph:Array.from({length:22},(_,i)=>({x:.22+i*.01,y:.3+sn(i*.3)*.05})),tr:[]};
let ac;const son=f=>{if(S.son)try{ac=ac||new(window.AudioContext||window.webkitAudioContext)();const o=ac.createOscillator(),g=ac.createGain(),t=ac.currentTime;o.frequency.value=f||520;g.gain.setValueAtTime(.02,t);g.gain.exponentialRampToValueAtTime(.0001,t+.1);o.connect(g);g.connect(ac.destination);o.start();o.stop(t+.11);}catch(_){}},tSon=()=>{S.son=!S.son;$('b-son').classList.toggle('act',S.son);son(640);};
const NS=1050,SG=12,NP=260,NV=10000,NK=360,NL=(NS*SG+NP+192)*2,NT=NV+NP+NK,tP=new Float32Array(NL*3),tM=new Float32Array(NL*3),pB=new Float32Array(NT*3),pR=new Float32Array(NT*3),pD=new Float32Array(NT),pK=new Float32Array(NT);
(()=>{let l=0;const rad=1.08,pv=(x,y,z,u,k,a)=>{tP.set([x,y,z],l*3);tM.set([u,k,a],l*3);l++;};for(let i=0;i<NS;i++){const u0=i/NS*6.283,v0=i*7.31%6.283,tw=1.55+i%5*.31,rm=.39+i*19%100*.0024,k=i%4,al=k===1?.34:.25;let px=0,py=0,pz=0,pu=0;for(let s=0;s<=SG;s++){const f=s/SG,u=u0+f*1.38,v=v0+f*tw*1.45,rr=rm+.045*sn(3*u+2*v),x=(rad+rr*cs(v))*cs(u),y=(rad+rr*cs(v))*sn(u),z=rr*sn(v);if(s){pv(px,py,pz,pu,k,al);pv(x,y,z,u,k,al);}px=x;py=y;pz=z;pu=u;}}for(let i=0;i<NP;i++){const u=i/NP*6.283,v=i*2.4%6.283,r0=.52,r1=.78+i*37%100*.0036,x1=(rad+r1*cs(v))*cs(u),y1=(rad+r1*cs(v))*sn(u),z1=r1*sn(v),q=NV+i;pv((rad+r0*cs(v))*cs(u),(rad+r0*cs(v))*sn(u),r0*sn(v),u,1,.34);pv(x1,y1,z1,u,1,.54);pB.set([x1,y1,z1],q*3);pK[q]=1;}for(let r=0;r<3;r++){const rd=1.45+r*.3;for(let s=0;s<64;s++){const a0=s/64*6.283,a1=(s+1)/64*6.283;pv(rd*cs(a0),rd*sn(a0),0,a0,4,.15);pv(rd*cs(a1),rd*sn(a1),0,a1,4,.15);}}for(let i=0;i<NV;i++){const u=i*2.4%6.283,v=(i+.5)/NV*144.5,rm=.44+i%11*.022;pB.set([(rad+rm*cs(v))*cs(u),(rad+rm*cs(v))*sn(u),rm*sn(v)],i*3);pR.set([sn(i*12.99),cs(i*78.23),sn(i*39.42)],i*3);}for(let j=0;j<NK;j++){const i=NV+NP+j;pK[i]=2+j%3;pB.set([j/NK*6.283,(j%2?-1:1)*(.72+j%5*.12),j*1.618%6.283],i*3);}})();
const cv=$('gl'),gl=cv.getContext('webgl',{antialias:true,alpha:false,powerPreference:'low-power'})||cv.getContext('experimental-webgl');
let p1,p2,u1={},u2={},b1,b2,b3,b4,b5,b6,dirty=0;
const mkP=(v,f)=>{const p=gl.createProgram();[[v,gl.VERTEX_SHADER],[f,gl.FRAGMENT_SHADER]].forEach(([s,t])=>{const h=gl.createShader(t);gl.shaderSource(h,s);gl.compileShader(h);gl.attachShader(p,h);});gl.linkProgram(p);return p;},mkB=(d,y)=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,d,y?gl.DYNAMIC_DRAW:gl.STATIC_DRAW);return b;};
function initGL(){if(!gl)return;try{p1=mkP(SH[0],SH[1]);p2=mkP(SH[2],SH[3]);'uR,uT,uZ,uA,uS,uW,uG,uB,uTl,uFr,uTp,uTh'.split(',').forEach(k=>u1[k]=gl.getUniformLocation(p1,k));'uR,uT,uSh,uZ,uA,uS,uB'.split(',').forEach(k=>u2[k]=gl.getUniformLocation(p2,k));b1=mkB(tP);b2=mkB(tM);b3=mkB(pB);b4=mkB(pR);b5=mkB(pD,1);b6=mkB(pK);C.glError=gl.getError();S.ok=C.glOk=true;}catch(e){T('p-fps','GL ERR');}}
function fOrg(o){if(S.foc===o&&o)return;S.foc=o;const ov=o&&O[o];Q('.b[data-org]').forEach(e=>{const h=!!(ov&&ov[2].includes(e.id));e.classList.toggle('linked',h);if(h)e.style.setProperty('--lk',ov[0]);});Q('.op').forEach(e=>e.classList.toggle('on',e.id==='op-'+o));Q('.sg,.cc').forEach(e=>e.classList.toggle('hi',!!o&&e.dataset.org===o));T('sg-st',ov?'LOCKED: '+o.toUpperCase():'ALL 8 ORGANS LIVE');}
function upMesh(now){
  const svg=$('mesh-svg'),dR=$('dm').getBoundingClientRect(),sR=$('tst').getBoundingClientRect();if(dR.width<920||sR.width<40){svg.innerHTML='';return;}
  const pos={},out=[],cy=cs(S.yw),sy=sn(S.yw),cp=cs(S.pt),sp=sn(S.pt),a=sR.width/mx(1,sR.height);
  const bz=(x1,y1,x2,y2,c,op,w,ph,ds)=>{const m1=(x1+x2)/2,m2=(y1+y2)/2-(y2<y1?18:-14),t=(ph%1+1)%1,i=1-t,bx=i*i*x1+2*i*t*m1+t*t*x2,by=i*i*y1+2*i*t*m2+t*t*y2;out.push(`<path d="M${x1|0} ${y1|0}Q${m1|0} ${m2|0} ${x2|0} ${y2|0}" fill="none" stroke="${c}" stroke-width="${w}" opacity="${op.toFixed(2)}"${ds?` stroke-dasharray="5 4" stroke-dashoffset="${((-now*.035)%18)|0}"`:''}/><circle cx="${bx|0}" cy="${by|0}" r="${(w+1.4).toFixed(1)}" fill="#fff" stroke="${c}"/>`);};
  Object.entries(O).forEach(([k,v])=>{const u=v[1]+sn(now*.0006)*.12,wx=1.54*cs(u),wy=1.54*sn(u),wz=.18*sn(u*2),x1=wx*cy-wz*sy,z1=wx*sy+wz*cy,dz=mx(.45,-(wy*sp+z1*cp-S.zm)),px=clm((.5+.5*x1/(dz*.58*a))*sR.width,42,sR.width-42),py=clm((.5-.5*(wy*cp-z1*sp)/(dz*.58))*sR.height,34,sR.height-18),el=$('op-'+k);if(el){el.style.left=(px|0)+'px';el.style.top=(py|0)+'px';}pos[k]=[sR.left-dR.left+px,sR.top-dR.top+py,v[0]];});
  const row=document.querySelector('#flow-feed .fl.sel')||document.querySelector('#flow-feed .fl');
  if(row){const r=row.getBoundingClientRect(),f=S.fl[S.si]||S.fl[0]||{lane:'phantom'},sp0=pos[f.lane==='compute'?'gpu':f.lane==='crypto'?'core':'sv']||pos.sv,col={compute:'#fbbf24',crypto:'#a78bfa',tarpit:'#fb7185'}[f.lane]||'#34d399';if(r.width>20)bz(sp0[0],sp0[1],r.left-dR.left,r.top-dR.top+r.height/2,col,.9,1.7,now*.00065,1);}
  [['win','p-hd',.5,1],['sv','p-osc',.5,1],['core','p-mat',.12,1],['gpu','p-sil',0,.5],['sv','p-kal',.5,0],['core','p-bb',.5,0],['gpu','p-th',.5,0]].forEach(([k,id,ax,ay],i)=>{const r=$(id).getBoundingClientRect(),sp0=pos[k];if(r.width>20)bz(sp0[0],sp0[1],r.left-dR.left+r.width*ax,r.top-dR.top+r.height*ay,sp0[2],S.foc===k?.92:.26+S.hb*.24,S.foc===k?1.8:1.1,now*.0004+i*.16,S.foc===k);});
  svg.innerHTML=out.join('');
}
function drawCh(now){
  const t=(now||performance.now())*.001;
  const P=(id,fn)=>{const c=$(id);if(!c)return;const r=c.getBoundingClientRect();if(r.width<6||r.height<6)return;const d=mn(2,devicePixelRatio||1),W=M.round(r.width*d),H=M.round(r.height*d);if(c.width!==W||c.height!==H){c.width=W;c.height=H;}const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);x.clearRect(0,0,r.width,r.height);x.font='700 8.5px monospace';const ln=(p,cl,w)=>{x.strokeStyle=cl;x.lineWidth=w||1.5;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.stroke();},dt=(X,Y,rd,cl,s)=>{x.beginPath();x.arc(X,Y,rd,0,6.283);s?(x.strokeStyle=cl,x.lineWidth=1.2,x.stroke()):(x.fillStyle=cl,x.fill());},tx=(s,X,Y,cl)=>{x.fillStyle=cl||'#94a3b8';x.fillText(s,X,Y);},pg=(p,cl,al)=>{x.fillStyle=cl;x.globalAlpha=al;x.beginPath();p.forEach(([X,Y],i)=>i?x.lineTo(X,Y):x.moveTo(X,Y));x.closePath();x.fill();x.globalAlpha=1;};fn(x,r.width,r.height,ln,dt,tx,pg);};
  P('c-bow',(x,W,H,ln,dt,tx,pg)=>{const m=H*.52,mh=H*.39;ln([[0,m],[W,m]],'rgba(56,189,248,.22)',1);[[R.w,-1,'#22d3ee'],[R.s,1,'#34d399']].forEach(([a,d,cl])=>{const p=a.map((v,i)=>[i*W/(a.length-1),m+d*mn(mh,v/80*mh)]);pg([[0,m],...p,[W,m]],cl,.18);ln(p,cl);});tx(`WIN ${S.dWR.toFixed(1)}/80MB`,4,10);tx(`SVH ${S.dSR.toFixed(1)}/80MB`,4,H-3);});
  P('c-osc',(x,W,H,ln,dt,tx,pg)=>{const m=H*.52,dx=W/(R.o.length-1),amp=clm(.24+S.rk/28+S.hb*.28,.18,.92);ln([[0,m],[W,m]],'rgba(56,189,248,.18)',1);for(let i=0;i<R.o.length-1;i++){const w0=R.o[i]+sn(t*3.2-i*.28)*.1*amp,w1=R.o[i+1]+sn(t*3.2-(i+1)*.28)*.1*amp,x0=i*dx,x1=x0+dx,y0=m-w0*H*.42,y1=m-w1*H*.42,cl=w0>=0?'#34d399':'#fb7185';pg([[x0,m],[x0,y0],[x1,y1],[x1,m]],cl,.2);ln([[x0,y0],[x1,y1]],cl);}ln(R.o.map((v,i)=>[i*dx,m-(v*.55+cs(t*2.4+i*.22)*.14)*H*.38]),'#22d3ee',1.2);tx('+CACHE / WIRE',4,10);tx('-JITTER / DLP',4,H-3);});
  P('c-ht',(x,W,H,ln,dt,tx)=>{const lw=52,cw=(W-lw-4)/16,rh=H/7;R.hn.forEach((nm,r)=>{const hi=S.foc&&R.ho[r]===S.foc,y0=r*rh;tx(nm,2,y0+rh*.76,hi?'#fff':'#8aa3c7');for(let k=0;k<16;k++){const v=mn(1,R.ht[r][k]+M.exp(-M.pow(k-(t*5)%16,2)*.45)*.28+(hi?.2:0));x.fillStyle=v>.78?'#fbbf24':v>.48?'#22d3ee':v>.26?'#1d4ed8':'#0f1f38';x.globalAlpha=v>.78?.95:v>.48?.68:.52;x.fillRect(lw+k*cw+1,y0+1.4,mx(2,cw-2.2),mx(2,rh-2.6));}});x.globalAlpha=1;});
  P('c-kal',(x,W,H,ln,dt,tx,pg)=>{const sy=H*.63,kx=(W-12)/(R.ke.length-1),lo=mx(.5,mn(...R.kr)-1.8),hi=mx(lo+4,mx(...R.kr)+1.8),my=v=>sy-10-(v-lo)/(hi-lo)*(sy-24),ep=R.ke.map((v,i)=>[4+i*kx,my(v)]);pg([...ep.map(([X,Y])=>[X,Y-9]),...ep.slice().reverse().map(([X,Y])=>[X,Y+9])],'#22d3ee',.15);R.kr.forEach((v,i)=>dt(4+i*kx,my(v),1.7,'#fb7185'));ln(ep,'#22d3ee',1.6);const lp=ep[ep.length-1];dt(lp[0],lp[1],2.5,'#fff');dt(lp[0],lp[1],5+S.hb*4,'#22d3ee',1);ln([[0,sy+2],[W,sy+2]],'rgba(56,189,248,.2)',1);ln(R.kk.map((k,i)=>[4+i*kx,H-5-mn(H-sy-15,k*(H-sy-11))]),'#a78bfa',1.3);tx(`RTT ${S.kx.toFixed(2)}ms (±2σ)`,4,10);tx(`KALMAN K=${S.kk.toFixed(2)}`,4,sy+13);});
  P('c-ph',(x,W,H,ln,dt,tx)=>{const pL=6,pT=13,pw=W-14,ph=H-26;[['rgba(251,113,133,.1)',0,.28],['rgba(251,191,36,.07)',.28,.32],['rgba(52,211,153,.08)',.6,.4]].forEach(([c,y,h])=>{x.fillStyle=c;x.fillRect(pL,pT+ph*y,pw,ph*h);});for(let i=1;i<R.ph.length;i++){const a=R.ph[i-1],b=R.ph[i],al=i/R.ph.length;x.globalAlpha=.16+al*.84;ln([[pL+a.x*pw,pT+(1-a.y)*ph],[pL+b.x*pw,pT+(1-b.y)*ph]],b.y>.72?'#fb7185':b.y>.42?'#fbbf24':'#34d399',1+al*1.4);}x.globalAlpha=1;const lp=R.ph[R.ph.length-1],lx=pL+lp.x*pw,ly=pT+(1-lp.y)*ph,lc=lp.y>.72?'#fb7185':lp.y>.42?'#fbbf24':'#34d399';dt(lx,ly,3.4,lc);x.globalAlpha=.55;dt(lx,ly,6+sn(t*4.5)*2.4+S.hb*3,lc,1);x.globalAlpha=1;tx('HOT >72°C',pL+2,9.5);tx('COOL <55°C',pL+2,H-3);const rt=`${S.gt.toFixed(1)}°C • ${S.gu|0}% GPU`;tx(rt,W-x.measureText(rt).width-6,9.5,'#e2e8f0');});
}
function renSil(){const cpu=+S.th.cpu_pct||0,vr=S.vt?M.round((S.vt-S.vf)/S.vt*100):0;$('sil-list').innerHTML=[['WIN SILICON','win',clm(cpu,4,100),'#22d3ee',`CPU ${cpu|0}% • ${S.wR.toFixed(1)}MB`],['GTX1650 GPU','gpu',clm(S.gt/.85,6,100),S.gt>70?'#fb7185':'#fbbf24',`${S.gt.toFixed(1)}°C • ${S.gu|0}% • ${vr}%VR`],['COLAB T4','gpu',clm(S.cu/25,4,100),'#a78bfa',`${S.cu|0}CU • ${S.cm}`],['OPENAI UNIFY','core',S.uni?clm(S.oaiM*5,45,100):18,'#38bdf8',`${S.oaiM} models • ${S.uni?'UNIFY':'LOC'}`],['EGRESS DLP','sv',clm(S.eh,S.egR?22:4,100),'#34d399',`${S.eh|0}% • ${S.egR}req • ${S.dlp}dlp`],['SVHOME HUB','sv',clm(S.sR/.8,6,100),S.sR>75?'#fb7185':'#34d399',`${S.sR.toFixed(1)}/80MB • ${S.apps.length} ON`]].map(([l,o,p,c,v])=>`<div class="sg ${S.foc===o?'hi':''}" data-org="${o}" onclick="fCam('${o}')"><span class="sg-l"><i style="color:${c}"></i>${l}</span><div class="sg-tr"><div class="sg-f" style="width:${p|0}%;background:${c}"></div></div><span class="sg-v" style="color:${c}">${E(v)}</span></div>`).join('');}
let lT=performance.now(),fc=0,fT=lT,_tk=0;
function loop(now){
  if(S.tac||document.hidden){S.raf=0;return;}
  S.raf=requestAnimationFrame(loop);const dt=mn(.05,(now-lT)*.001);lT=now;
  if(++fc&&now-fT>700){T('p-fps',M.round(fc*1e3/(now-fT))+' FPS');fc=0;fT=now;}
  if(!S.dr)S.tY+=dt*(.15+S.hb*.12);S.yw+=(S.tY-S.yw)*.1;S.pt+=(S.tP-S.pt)*.1;S.zm+=(S.tZ-S.zm)*.1;S.dWR+=(S.wR-S.dWR)*.12;S.dSR+=(S.sR-S.dSR)*.12;
  S.sp=mx(.22,S.sp-dt*.45);S.tl=mx(0,S.tl-dt*.62);S.fr=mx(0,S.fr-dt*.62);S.tp=mx(0,S.tp-dt*.56);S.sh=mx(0,S.sh-dt*.38);S.hb=mx(0,S.hb-dt*1.15);
  const bpm=clm(58+S.gu*.35+(S.rtt>15?16:0)+S.hb*18,54,118),ph=(now*.001*bpm/60)%1,card=M.exp(-M.pow((ph-.12)/.065,2))+.52*M.exp(-M.pow((ph-.28)/.085,2))+S.hb*.45;
  if(!gl||!S.ok)return;
  const rc=cv.getBoundingClientRect(),dp=mn(1.75,devicePixelRatio||1),w=mx(2,M.floor(rc.width*dp)),h=mx(2,M.floor(rc.height*dp));
  if(cv.width!==w||cv.height!==h){cv.width=w;cv.height=h;}
  gl.viewport(0,0,w,h);gl.clearColor(.01,.022,.048,1);gl.clear(gl.COLOR_BUFFER_BIT);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE);
  const att=(p,a)=>a.forEach(([n,b,sz])=>{const l=gl.getAttribLocation(p,n);gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,sz,gl.FLOAT,false,0,0);}),s1=(u,o)=>Object.entries(o).forEach(([k,v])=>gl.uniform1f(u[k],v));
  gl.useProgram(p1);att(p1,[['aP',b1,3],['aM',b2,3]]);gl.uniform2f(u1.uR,S.yw,S.pt);s1(u1,{uT:now*.001,uZ:S.zm,uA:w/h,uS:S.sp,uW:(now*.0028)%6.283,uG:S.sp+S.hb*1.1+S.tl+S.fr,uB:card,uTl:S.tl,uFr:S.fr+(S.cm.includes('WARM')?.45:0),uTp:S.tp,uTh:mx(0,(S.gt-54)/35)});gl.drawArrays(gl.LINES,0,NL);
  if(dirty){gl.bindBuffer(gl.ARRAY_BUFFER,b5);gl.bufferSubData(gl.ARRAY_BUFFER,0,pD);dirty=0;}
  gl.useProgram(p2);att(p2,[['aB',b3,3],['aRn',b4,3],['aD',b5,1],['aK',b6,1]]);gl.uniform2f(u2.uR,S.yw,S.pt);s1(u2,{uT:now*.001,uSh:S.sh,uZ:S.zm,uA:w/h,uS:S.sp,uB:card});gl.drawArrays(gl.POINTS,0,NT);gl.disable(gl.BLEND);
  if((++_tk&1)===0){upMesh(now);drawCh(now);T('sp-s',`BPM ${bpm|0} • ${(((S.yw*57.3)%360+360)%360)|0}° • ${S.cm}`);}
}
function fCam(k){[S.tY,S.tP,S.tZ]={win:[-.48,.16,3.1],core:[0,.04,2.82],sv:[1.15,.22,3.1],gpu:[2.05,.42,3.2],over:[.35,.32,3.65]}[k]||[.35,.32,3.65];Q('#cam-b button').forEach(b=>b.classList.toggle('on',b.dataset.c===k));fOrg(k==='over'?null:k);}
function fireA(op){const u=String(op||'').toUpperCase();S.hb=1;if(/TELEPORT|DESK|CRYO|PTX/.test(u)){S.tl=1;S.sp=.95;son(720);}else if(/FROST|CART|COLAB|EMBED/.test(u)){S.fr=1;S.sp=.92;son(860);}else if(/TARPIT|DLP/.test(u)){S.tp=1;S.sp=.95;}else if(u.includes('CHMC')){S.sh=1;son(160);}else if(u.includes('VSA')){pD.fill(0);dirty=1;upVsa();son(600);}else S.sp=.88;}
function upVsa(){let c=0;for(let i=0;i<NV;i++)if(pD[i]>.5)c++;const pc=+(c*100/NV).toFixed(1);C.destroyedPct=pc;const vp=$('v-pl');vp.textContent=pc?`VSA ${pc}% DMG`:'VSA 100%';vp.className='tg '+(pc?'wn':'ok');T('tc-s',pc?`Halo ${pc}%`:'VSA-10K • 10,620 PTS');}
function blast(f){for(let i=0;i<NV;i++)pD[i]=i<M.floor(NV*f)?1:0;dirty=1;S.sp=.92;S.hb=1;upVsa();log(`VSA ${C.destroyedPct}% damaged.`);}
const log=t=>{T('h-out',t);T('t-out',t);};
async function api(u,b){const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined),t=await r.text();let j;try{j=JSON.parse(t);}catch(_){j={raw:t};}if(!r.ok)throw new Error(j.error||r.statusText);return j;}
async function rq(u,b,tag){if(tag)fireA(tag);try{const r=await api(u,b);if(tag)pTr(tag.toLowerCase(),JSON.stringify(r).slice(0,46),'ok');log(JSON.stringify(r,null,2));await pulse();return r;}catch(e){log('Err: '+e.message);}}
const act=k=>k==='ks'?rq('/api/trinity/kill-switch',{active:!S.ks,reason:S.ks?'manual_resume':'manual_guard'},'ROI'):A[k]&&rq(A[k][0],A[k][2]||{},A[k][1]);
const tp=()=>rq(P2+'tarpit/env/prod.yml',null,'TARPIT'),togC=n=>n==='connect'?log('Core ON.'):rq('/v1/cartridges',{name:n,enabled:!S.ct[n]},'CART');
async function runB(u,b={}){const r=await rq(u,b,'TELEPORT');if(r&&r.ideas)$('h-tbl').innerHTML='<table class="tbl"><thead><tr><th>Idea</th><th>Result</th><th>OK</th></tr></thead><tbody>'+Object.values(r.ideas).slice(0,29).map(x=>`<tr><td>${E(x.name)}</td><td class="in">${E(x.after)}</td><td class="${x.ok?'ok':'er'}">${x.ok?'PASS':'FAIL'}</td></tr>`).join('')+'</tbody></table>';}
function tac(){S.tac=!S.tac;C.gpuPaused=S.tac;document.body.classList.toggle('tactical',S.tac);$('b-tac').classList.toggle('act',S.tac);if(S.tac){cancelAnimationFrame(S.raf);S.raf=0;T('p-fps','0% GPU');}else{lT=performance.now();S.raf=requestAnimationFrame(loop);}}
function selSec(id){const s=SEC.find(x=>x[0]===id)||SEC[0];T('h-ti',s[3]);Q('.tab').forEach(t=>t.classList.toggle('active',t.dataset.id===id));Q('.dpn').forEach(p=>p.classList.remove('active'));if(s[2]&&$(s[2]))$(s[2]).classList.add('active');$('h-ac').innerHTML=bt(s[4],'xs');if(id==='silicon')renSil();}
const oPal=()=>{$('spotlight-modal').classList.add('open');$('spotlight-input').focus();},cPal=()=>$('spotlight-modal').classList.remove('open');
async function xPal(){const q=($('spotlight-input').value||'').trim(),l=q.toLowerCase();if(!q)return;if(A[l]){cPal();return act(l);}if(l==='tarpit'){cPal();return tp();}if(l==='bench'){cPal();return runB(P2+'benchmark',{wave:'all'});}if(l==='zero-gpu'||l==='tactical'){cPal();return tac();}try{T('spotlight-out',JSON.stringify(await api('/api/hyperdrive/search?q='+encodeURIComponent(q)+'&limit=12'),null,2));}catch(e){T('spotlight-out','Err: '+e.message);}}
async function pip(){try{const w=await documentPictureInPicture.requestWindow({width:230,height:80});w.document.body.style.cssText='margin:0;background:#02050b;color:#22d3ee;font:11px monospace;padding:8px';const u=()=>!w.closed&&(w.document.body.innerHTML=`CHIMERA v23<br>${S.rtt.toFixed(1)}ms • ${S.wR.toFixed(1)}⇄${S.sR.toFixed(1)}MB • ${S.gt|0}°C`);u();const iv=setInterval(()=>w.closed?clearInterval(iv):u(),1e3);}catch(e){log('PiP:'+e.message);}}
function pTr(k,m,c){R.tr.push([new Date().toTimeString().slice(0,8),k,m,c||'in']);if(R.tr.length>10)R.tr.shift();$('t-lg').innerHTML=R.tr.slice(-7).map(([t,k2,m2,c2])=>`<div class="tr"><span class="mu">${t}</span><span class="${c2}" style="font-weight:700">${E(k2)}</span><span>${E(m2)}</span></div>`).join('');}
function selFl(i){S.si=i;S.sp=.88;S.hb=.9;renFl(S.fl,1);upMesh(performance.now());}
function renFl(fl,keep){if(!fl||!fl.length)return;if(!keep){const n=fl[0].id;if(n>S.lf&&S.lf){fireA(fl[0].op);S.si=0;pTr(fl[0].lane||'wire',`${fl[0].op} ${fl[0].detail||''}`,fl[0].ok?'ok':'er');}S.lf=mx(S.lf,n);S.fl=fl;C.flowsSeen=fl.length;}if(S.si>=S.fl.length)S.si=0;T('w-ct',`${S.fl.length} LIVE`);$('flow-feed').innerHTML=S.fl.slice(0,6).map((f,i)=>`<div class="fl ${E(f.lane)} ${i===S.si?'sel':''}" onclick="selFl(${i})"><div class="ft"><span><span class="fb ${f.lane==='compute'?'wn':f.lane==='crypto'?'vi':f.lane==='tarpit'?'er':'ok'}">${E(f.op)}</span> <span class="mu">${E(f.src)}→${E(f.dst)}</span></span><span class="${f.ok?'ok':'er'}">${f.bytes?f.bytes+'B ':''}${f.ms}ms</span></div><div class="fs"><span>${E(f.detail||'rpc')}</span><span>${E(f.ts)}</span></div></div>`).join('');const c=S.fl[S.si]||S.fl[0];if(!S.foc){T('an-o','SYNAPSE → '+c.op);T('an-s',`${c.src}→${c.dst} (${c.ms}ms)`);}T('sg-h',`#${c.id} | ${c.op} | ${c.bytes}B • ${c.ms}ms`);T('sg-b',`${c.src}→${c.dst} • ${c.detail||'flow'} • ${c.ts}`);}
function sKal(o){const p=S.kp+.08,K=p/(p+1.2);S.kx+=K*(o-S.kx);S.kp=(1-K)*p;S.kk=K;psh(R.kr,o);psh(R.ke,S.kx);psh(R.kk,K);}
function upB(z,ph,init){if(z&&z.daemon_ram_mb!=null){S.wR=z.daemon_ram_mb;if(init)S.dWR=S.wR;else psh(R.w,S.wR);T('sw',`${S.wR.toFixed(1)}MB`);T('tz',`${S.wR.toFixed(1)}/80MB`);}if(ph&&ph.direct_rtt_ms!=null){S.rtt=ph.direct_rtt_ms;if(init)S.kx=S.rtt;else sKal(S.rtt);T('p-tun',S.rtt.toFixed(2)+'ms');T('st',`${S.rtt.toFixed(1)}ms`);}else if(!init)sKal(S.kx);}
async function pulse(){
  if(document.hidden)return;
  try{
    const p=await api('/api/pulse'),{zero_weight:z={},phantom:ph0={},peer:pr0,platform:pl,trinity:tr}=p,ph=ph0.client||{},pr=pr0||S.pr;if(pr)S.pr=pr;
    S.hbS++;S.hb=mn(1,S.hb+.65);const d=$('hb-dot');if(d){d.classList.add('hit');setTimeout(()=>d.classList.remove('hit'),180);}T('hb-lbl',`BEAT #${S.hbS}`);
    upB(z,ph,0);if(pr&&pr.zero_weight&&pr.zero_weight.daemon_ram_mb!=null)S.sR=pr.zero_weight.daemon_ram_mb;psh(R.s,S.sR);
    T('p-ram',`${S.wR.toFixed(1)}⇄${S.sR.toFixed(1)}MB`);if(pr&&pr.online){T('ss',`${S.sR.toFixed(1)}MB`);T('tp',`${pr.node_name} ${S.sR.toFixed(1)}MB`);}
    const tb=(ph.tx_bytes||0)+(ph.rx_bytes||0),now=performance.now();if(S.lt&&tb>=S.lb){S.rk=M.round((tb-S.lb)/1024/mx(.2,(now-S.lt)/1e3));if(S.rk>1)S.sp=mn(1,S.sp+.38);}S.lb=tb;S.lt=now;T('p-rt',`${S.rk} KB/s`);
    if(p.latest_event)T('te',`${p.latest_event.ts_local} ${p.latest_event.message}`);
    if(tr){S.ks=!!tr.kill_switch;const g=$('p-gov'),b=$('b-ks');g.textContent=tr.governor_mode||'LOCAL';g.className='kv '+(S.ks?'wn':'ok');b.textContent=S.ks?'HALT':'ROI';b.className=S.ks?'act':'';}
    if(pl){
      const hd=pl.hyper_desk||{},th=pl.thermo||{},om=pl.omega||{};S.th=th;S.eh=pl.egress_hit_pct||0;S.egR=pl.egress_requests||0;S.dlp=pl.egress_dlp_blocked||0;
      if(pl.gpu_temp_c!=null)S.gt=+pl.gpu_temp_c;if(pl.gpu_util_pct!=null)S.gu=+pl.gpu_util_pct;
      S.vf=+pl.vram_free_mb||S.vf;S.vt=+pl.vram_total_mb||S.vt;S.cu=+pl.colab_cu||S.cu;S.cm=String(pl.colab_mode||'AUTO:SLEEP');S.oaiM=+pl.openai_models_count||S.oaiM;S.uni=!!pl.unify_active;S.apps=pl.apps_online||[];
      const gb=((hd.reclaimed_mb||0)/1024).toFixed(2),lk=S.apps.length?S.apps.join(','):`${pl.apps_total||0}`,sum=`#${S.hbS} • ${S.rtt.toFixed(2)}ms • ${S.wR.toFixed(1)}⇄${S.sR.toFixed(1)}MB • ${S.gt.toFixed(1)}°C(${S.gu|0}%) • ${S.cu|0}CU[${S.cm}] • OAI ${S.oaiM} • ${lk}`;
      [['hd-gb',`+${gb} GB`],['hd-c',hd.cryo_procs||0],['hd-w',hd.wall_pinned||0],['hd-o',hd.orphans||0],['eg-h',`${S.eh|0}%(${S.egR})`],['oai-m',`${S.oaiM} ${S.uni?'UNIFY':'LOC'}`],['eg-d',S.dlp],['p-thm',`${th.watts||0}W•${S.gt.toFixed(1)}°C`],['p-cu',`${S.cu|0}CU•${S.cm}`],['th-r',String(th.regime||'COOL').replace('_LOCAL','')],['om-g',`${om.genome||'lz4_simd'} #${om.gen||1}`],['p-pl',`${lk} • ${hd.vram_yield_ms||0}ms`],['bb-t',`${pl.blackbox_frames||0} FRM`],['tt2',`+${gb}GB • ${S.cu|0}CU`],['f-l',sum]].forEach(([i,v])=>T(i,v));
      if(pl.cartridges){S.ct=pl.cartridges;const en=Object.entries(pl.cartridges);T('c-cnt',`${en.filter(([,v])=>v).length}/${en.length} ON`);$('c-ch').innerHTML=en.map(([k,v])=>{const og=CO[k]||'core';return`<span class="cc ${v?'':'off'} ${S.foc===og?'hi':''}" data-org="${og}" onclick="togC('${E(k)}')"><i></i>${E(k.replace(/_(entity|membrane|pareto)/,'').replace('_',''))}</span>`;}).join('');}
      psh(R.o,clm(S.eh/100*.65+(S.rk>0?.38:.14)-(S.rtt>18?.48:0),-.9,.9));
      const rp=[mn(1,.32+S.rk/35+S.hb*.2),S.cm.includes('WARM')?.95:mn(.82,.42+S.gu/80),mn(1,.28+S.eh/100+S.egR*.02),hd.cryo_procs?.86:.36,S.uni?.84:.25,mn(1,.34+S.gt/120),C.destroyedPct?.96:.58];
      R.ht.forEach((r,i)=>psh(r,clm(rp[i]+sn(S.hbS*.7+i)*.1,.12,1)));psh(R.ph,{x:clm(((+th.cpu_pct||15)+S.gu*.6)/130,.08,.94),y:clm((S.gt-35)/50,.08,.94)});
      $('tkt').innerHTML=`${sum} •&nbsp;&nbsp;${sum} •&nbsp;&nbsp;`;if(!R.tr.length)pTr('live',`${S.rtt.toFixed(1)}ms • ${S.oaiM} OAI • ${S.cu|0}CU`,'ok');renSil();
    }
    if(p.flows)renFl(p.flows,0);if(p.status_etag&&p.status_etag!==_et)await refresh();
  }catch(_){}
}
async function refresh(){try{const r=await fetch('/api/status',{headers:_et?{'If-None-Match':_et}:{}});if(r.status===304||!r.ok)return;_et=r.headers.get('ETag')||_et;const j=await r.json();upB(j.zero_weight,(j.phantom||{}).client,1);}catch(_){}}
$('dm').onmouseover=e=>{const t=e.target.closest('[data-org]');fOrg(t?t.dataset.org:null);};$('dm').onmouseleave=()=>fOrg(null);
cv.onpointerdown=e=>{S.dr=1;S.lx=e.clientX;S.ly=e.clientY;cv.setPointerCapture(e.pointerId);};cv.onpointerup=()=>S.dr=0;
cv.onpointermove=e=>{if(!S.dr)return;const dx=e.clientX-S.lx,dy=e.clientY-S.ly;S.lx=e.clientX;S.ly=e.clientY;if(e.shiftKey){const rc=cv.getBoundingClientRect(),nx=(e.clientX-rc.left)/rc.width*2-1,ny=1-(e.clientY-rc.top)/rc.height*2,a=rc.width/mx(1,rc.height),cy=cs(S.yw),sy=sn(S.yw),cp=cs(S.pt),sp=sn(S.pt);let h=0;for(let i=0;i<NV;i++){if(pD[i]>.5)continue;const px=pB[i*3],py=pB[i*3+1],pz=pB[i*3+2],x1=px*cy-pz*sy,z1=px*sy+pz*cy,d=mx(.45,-(py*sp+z1*cp-S.zm));if((x1/(d*.58*a)-nx)**2+((py*cp-z1*sp)/(d*.58)-ny)**2<.055){pD[i]=1;h++;}}if(h){dirty=1;S.sp=.92;S.hb=1;upVsa();}return;}S.tY+=dx*.007;S.tP=clm(S.tP+dy*.007,-1.1,1.1);};
cv.addEventListener('wheel',e=>{S.tZ=clm(S.tZ+M.sign(e.deltaY)*.28,2.3,6.2);},{passive:true});
window.onresize=()=>{drawCh(performance.now());upMesh(performance.now());};
document.onvisibilitychange=()=>{if(!document.hidden&&!S.tac&&!S.raf){lT=performance.now();S.raf=requestAnimationFrame(loop);pulse();}};
window.onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K'||e.code==='Space')){e.preventDefault();$('spotlight-modal').classList.contains('open')?cPal():oPal();return;}if(e.key==='Escape')return cPal();if(e.key==='Tab'){e.preventDefault();return tac();}if(['INPUT','TEXTAREA'].includes(document.activeElement.tagName))return;const k={'1':'silicon','2':'flow','0':'hyperdrive','x':'galactic','X':'galactic','8':'ops'}[e.key];if(k)selSec(k);};
Q('[data-h]').forEach(e=>{const[dc,ti,tg,tc,id]=e.dataset.h.split('|');e.innerHTML=`<span class="pt"><span class="pd ${dc}"></span>${ti}</span><span class="tg ${tc||''}"${id?' id="'+id+'"':''}>${tg}</span>`;});
Q('[data-k]').forEach(e=>{e.innerHTML=e.dataset.k.split('|').map(x=>{const[l,id,c]=x.split(':');return`<div class="kc"><span class="kk">${l}</span><span class="kv2 ${c}" id="${id}">0</span></div>`;}).join('');});
$('t-grid').innerHTML=[['WIN','tz',''],['SVHOME','tp','ok'],['COLAB','tt2','in'],['EVENT','te','wn']].map(([l,i,c])=>`<div class="tb2"><b>${l}</b><div id="${i}" class="${c}">--</div></div>`).join('');
$('kpi-bar').innerHTML=[['RTT','p-tun','ok','sv'],['ZERO-WEIGHT','p-ram','in','win'],['THERMO','p-thm','wn','gpu'],['COLAB','p-cu','vi','gpu'],['GOV','p-gov','ok','win'],['FPS','p-fps','ok','core']].map(([l,id,c,o])=>`<div class="kp" data-org="${o}" onclick="fCam('${o}')"><span class="kl">${l}</span><span class="kv ${c}" id="${id}">--</span></div>`).join('');
$('q-act').innerHTML=bt([['Cryo',"act('opt')"],['PTX',"act('ptx')"],['WASM',"act('teleport')"],['FROST',"act('frost')"],['Blast','blast(.42)'],['Heal',"act('vsa')"],['Tarpit','tp()'],['CHMC',"act('chmc')"]],'xs');
$('t-act').innerHTML=bt([['Cryo',"act('opt')"],['WASM',"act('teleport')"],['FROST',"act('frost')"],['VSA',"act('vsa')"],['Bench',"runB(P2+'benchmark',{wave:'all'})"]])+'<button class="pri" onclick="tac()">3D</button>';
$('cam-b').innerHTML=[['over','ALL'],['win','WIN'],['core','VSA'],['sv','SVH'],['gpu','COLAB']].map(([k,l])=>`<button class="xs ${k==='over'?'on':''}" data-c="${k}" onclick="fCam('${k}')">${l}</button>`).join('');
$('org-pills').innerHTML=Object.entries(O).map(([k,v])=>`<div class="op" id="op-${k}" data-org="${k}" onclick="fCam('${k}')">${v[3]}</div>`).join('');
$('s-tb').innerHTML=SEC.map(s=>`<button class="tab" data-id="${s[0]}" onclick="selSec('${s[0]}')">[${s[1]}] ${s[0].toUpperCase()}</button>`).join('');
selSec('silicon');initGL();if(window.__INIT_STATE__)upB(window.__INIT_STATE__.zero_weight,(window.__INIT_STATE__.phantom||{}).client,1);else refresh();renSil();drawCh(performance.now());S.raf=requestAnimationFrame(loop);setInterval(pulse,800);setTimeout(pulse,120);
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
    """Emit self-unpacking DecompressionStream('deflate-raw') capsule (<15 KB gzipped wire)."""
    s_b64 = _deflate_raw_b64(init_state_json)
    boot = (
        "<!doctype html><html><head><meta charset='utf-8'><title>CHIMERA v23</title></head>"
        "<body style='margin:0;background:#02050b;color:#67e8f9;font:12px monospace;padding:16px'>"
        "<!-- CHIMERA-HYPER v2.0 -->Awakening CHIMERA v23..."
        "<script>const _u=x=>new Response(new Blob([Uint8Array.from(atob(x),c=>c.charCodeAt(0))]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();"
        f"(async()=>{{const[h0,s0]=await Promise.all([_u('{_RAW_DEFLATE_B64}'),_u('{s_b64}')]);"
        f"document.open();document.write(h0.replace('/*__INIT_STATE__*/null',()=>s0).replace('/*__INIT_ETAG__*/\"\"',()=>JSON.stringify({etag_json})));document.close();}})();</script></body></html>"
    )
    return boot.encode("utf-8")

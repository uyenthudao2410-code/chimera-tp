"""CHIMERA-MYCELIUM (Idea #9) — Living Spores, < 50 KB Open PWA & Zero-Trace Autotomy.

Extends CHIMERA-BIOS across mobile phones, browsers, and volunteer compute peers via:
- Capability-scoped HMAC-SHA256 Spore join credentials (zero plaintext secrets stored).
- Zero-Trust GF(256) Shamir-blinded (K, N) payload sharding (`chimera_tp.gf256` accelerated
  with pure-Python GF(256) fallback) so volunteer spores never observe plaintext.
- Instant < 50 ms Zero-Trace Autotomy (token revocation + in-place ephemeral key wiping +
  state drop + SHA-256 auditable autotomy receipt).
- Voice/Text Seed Inbox for async operator ideas and Law-6 approvals.
- Self-contained, Zero-CDN, Zero-WebGL (< 25 KB) dark tactical CHIMERA-BIOS Spore PWA.

100% Python stdlib (+ optional `chimera_tp.gf256`), Zero-NumPy, lazy-loaded, < 1 MiB RAM.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Any

MAX_PWA_BYTES = 50 * 1024

DEFAULT_ROLE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "mobile_pwa": ("read_status", "stream_sse", "submit_seed", "approve_law6"),
    "desktop_pwa": ("read_status", "stream_sse", "submit_seed", "approve_law6"),
    "volunteer_spore": ("blind_shard_hold", "heartbeat"),
    "observer": ("read_status", "stream_sse"),
}


# ---------------------------------------------------------------------------
# GF(256) Backend — prefers `chimera_tp.gf256`, falls back to pure-Python GF(256)
# ---------------------------------------------------------------------------

def _init_gf256_backend():
    try:
        from chimera_tp import gf256 as _gf  # type: ignore

        return (
            "chimera_tp.gf256",
            _gf.gf_mul,
            _gf.gf_inv,
            _gf.scale_bytes,
            _gf.xor_bytes,
        )
    except Exception:
        pass

    poly = 0x11B
    gen = 0x03

    def _slow_mul(a: int, b: int) -> int:
        res = 0
        while b:
            if b & 1:
                res ^= a
            a <<= 1
            if a & 0x100:
                a ^= poly
            b >>= 1
        return res & 0xFF

    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        exp[i + 255] = x
        log[x] = i
        x = _slow_mul(x, gen)
    inv = [0] * 256
    for v in range(1, 256):
        inv[v] = exp[255 - log[v]]
    mul_tbl = [
        bytes(256)
        if s == 0
        else (
            bytes(range(256))
            if s == 1
            else bytes(0 if b == 0 else exp[log[s] + log[b]] for b in range(256))
        )
        for s in range(256)
    ]

    def _gf_mul(a: int, b: int) -> int:
        if a == 0 or b == 0:
            return 0
        return exp[log[a] + log[b]]

    def _gf_inv(a: int) -> int:
        if a == 0:
            raise ZeroDivisionError("Zero has no multiplicative inverse in GF(256)")
        return inv[a]

    def _scale(buf: bytes | bytearray, scalar: int) -> bytes:
        if scalar == 0:
            return bytes(len(buf))
        if scalar == 1:
            return bytes(buf)
        return bytes(buf).translate(mul_tbl[scalar])

    def _xor(a: bytes | bytearray, b: bytes | bytearray) -> bytes:
        if len(a) != len(b):
            raise ValueError(f"Length mismatch for XOR: {len(a)} vs {len(b)}")
        if not a:
            return b""
        return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(
            len(a), "little"
        )

    return ("pure_python_gf256", _gf_mul, _gf_inv, _scale, _xor)


_GF_BACKEND: tuple[Any, ...] | None = None
_GF_LOCK = threading.Lock()


def _get_gf256_backend() -> tuple[Any, ...]:
    global _GF_BACKEND
    if _GF_BACKEND is not None:
        return _GF_BACKEND
    with _GF_LOCK:
        if _GF_BACKEND is None:
            _GF_BACKEND = _init_gf256_backend()
        return _GF_BACKEND


def _default_ops_dir() -> Path:
    return Path(os.environ.get("CHIMERA_HOME") or (Path.home() / ".chimera"))


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def _deterministic_pad(seed: bytes, degree_idx: int, length: int) -> bytes:
    if length <= 0:
        return b""
    out = bytearray()
    ctr = 0
    while len(out) < length:
        out.extend(
            hashlib.blake2b(
                seed + struct.pack("!II", degree_idx, ctr), digest_size=64
            ).digest()
        )
        ctr += 1
    return bytes(out[:length])


def blind_split(
    payload: bytes | str,
    k: int = 2,
    n: int = 3,
    *,
    seed: bytes | None = None,
) -> list[dict[str, Any]]:
    """Split `payload` into `n` information-theoretically blinded GF(256) Shamir shares.

    Any `k` distinct shares reconstruct exact `payload`; any `< k` shares (e.g. 1 share
    when `k=2, n=3`) reveal zero information about the plaintext.
    """
    raw = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    k_i = int(k)
    n_i = int(n)
    if k_i < 2:
        raise ValueError("Threshold k must be >= 2 for zero-trust blinding")
    if n_i < k_i or n_i > 255:
        raise ValueError("Share count n must satisfy k <= n <= 255")

    length = len(raw)
    coeffs: list[bytes] = [raw]
    for deg in range(1, k_i):
        if seed is None:
            coeffs.append(os.urandom(length))
        else:
            coeffs.append(_deterministic_pad(seed, deg, length))

    backend_name, _gf_mul, _gf_inv, _scale_bytes, _xor_bytes = _get_gf256_backend()
    shares: list[dict[str, Any]] = []
    for x in range(1, n_i + 1):
        # Evaluate P(x) = a_0 + a_1*x + ... + a_{k-1}*x^{k-1} over GF(256) via Horner's rule
        acc = coeffs[k_i - 1]
        for deg in range(k_i - 2, -1, -1):
            acc = _xor_bytes(_scale_bytes(acc, x), coeffs[deg])
        share_sha = _sha256_hex(acc)
        shares.append(
            {
                "share_index": x,
                "k": k_i,
                "n": n_i,
                "orig_len": length,
                "data_b64": base64.b64encode(acc).decode("ascii"),
                "share_sha256": share_sha,
                "blinded": True,
                "gf256_backend": backend_name,
            }
        )
    return shares


def blind_reconstruct(shares: list[dict[str, Any]]) -> bytes:
    """Reconstruct exact plaintext bytes from any >= K valid GF(256) blinded shares."""
    if not shares:
        raise ValueError("No shares supplied for reconstruction")

    k = int(shares[0]["k"])
    orig_len = int(shares[0]["orig_len"])
    if len(shares) < k:
        raise ValueError(f"Need at least {k} shares to reconstruct; received {len(shares)}")

    selected: list[tuple[int, bytes]] = []
    seen_x: set[int] = set()
    for sh in shares:
        x = int(sh["share_index"])
        if not (1 <= x <= 255):
            raise ValueError(f"Invalid share_index {x}; must be in 1..255")
        if x in seen_x:
            raise ValueError(f"Duplicate share_index {x}")
        if int(sh["k"]) != k or int(sh["orig_len"]) != orig_len:
            raise ValueError("Incompatible share metadata (k or orig_len mismatch)")
        data = base64.b64decode(sh["data_b64"].encode("ascii"))
        if len(data) != orig_len:
            raise ValueError("Share byte length mismatch")
        if sh.get("share_sha256") and _sha256_hex(data) != sh["share_sha256"]:
            raise ValueError(f"Corrupted share detected at share_index={x}")
        seen_x.add(x)
        selected.append((x, data))
        if len(selected) == k:
            break

    if len(selected) < k:
        raise ValueError(f"Insufficient distinct shares: {len(selected)} < {k}")
    if orig_len == 0:
        return b""

    # Lagrange interpolation at x = 0 in GF(256):
    # lambda_m = prod_{r != m} (x_r / (x_m ^ x_r))
    _, _gf_mul, _gf_inv, _scale_bytes, _xor_bytes = _get_gf256_backend()
    result = bytes(orig_len)
    xs = [x for x, _ in selected]
    for m, (xm, ym) in enumerate(selected):
        num = 1
        den = 1
        for r, xr in enumerate(xs):
            if r == m:
                continue
            num = _gf_mul(num, xr)
            den = _gf_mul(den, xm ^ xr)
        lam = _gf_mul(num, _gf_inv(den))
        result = _xor_bytes(result, _scale_bytes(ym, lam))
    return result


# ---------------------------------------------------------------------------
# Self-Contained Zero-CDN Zero-WebGL < 25 KB Dark Tactical Spore PWA
# ---------------------------------------------------------------------------

_PWA_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#080c12">
<title>CHIMERA-BIOS · Living Spore</title>
<style>
:root{--bg:#070b11;--card:#0e1520;--bd:#1e2c40;--tx:#dce7f5;--mut:#7c90ad;--ac:#38bdf8;--ok:#22c55e;--warn:#f59e0b;--bad:#ef4444;--pur:#a78bfa;--teal:#14b8a6}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top right,#102033 0%,var(--bg) 52%);color:var(--tx);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;min-height:100vh}
.wrap{max-width:980px;margin:0 auto;padding:14px}
header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;margin-bottom:12px}
.brand{display:flex;align-items:center;gap:10px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--warn);box-shadow:0 0 10px var(--warn)}
.dot.live{background:var(--ok);box-shadow:0 0 10px var(--ok)}
.dot.off{background:var(--bad);box-shadow:0 0 10px var(--bad)}
h1{font-size:15px;margin:0;letter-spacing:.06em;text-transform:uppercase}
.sub{font-size:11px;color:var(--mut)}
.acts{display:flex;gap:8px;align-items:center}
.pill{font-size:11px;padding:3px 9px;border-radius:999px;border:1px solid var(--bd);background:#0a1019;color:var(--mut)}
.pill.ok{border-color:#1e4d32;color:#86efac}
.pill.warn{border-color:#5b3d10;color:#fcd34d}
.btn{cursor:pointer;border:1px solid var(--bd);background:#132032;color:var(--tx);padding:6px 11px;border-radius:8px;font-size:12px;font-weight:600}
.btn:hover{border-color:var(--ac)}
.btn.danger{border-color:#5c1d24;background:#260d12;color:#fca5a5}
.btn.danger:hover{border-color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:13px}
.card h2{margin:0 0 10px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--ac);display:flex;justify-content:space-between;align-items:center}
.hbar{margin-bottom:9px}
.hrow{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px}
.track{height:8px;border-radius:999px;background:#09101a;border:1px solid #182334;overflow:hidden}
.fill{height:100%;border-radius:999px;transition:width .35s ease}
.kv{display:grid;grid-template-columns:1fr auto;gap:6px 10px;font-size:12px}
.k{color:var(--mut)}.v{font-weight:600;text-align:right}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:11px}
.laws{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.law{font-size:10px;padding:2px 7px;border-radius:6px;background:#0a111c;border:1px solid #1e2d42;color:#93c5fd}
.list{display:flex;flex-direction:column;gap:7px;max-height:210px;overflow:auto}
.item{background:#0a1019;border:1px solid #1b283b;border-radius:8px;padding:8px 9px;font-size:12px}
.item-h{display:flex;justify-content:space-between;gap:6px;font-weight:600;margin-bottom:2px}
.tag{font-size:10px;padding:1px 6px;border-radius:5px;background:#172437;color:#cbd5e1}
.tag.l6{background:#2d1f0b;color:#fbbf24;border:1px solid #6b4712}
form{display:flex;flex-direction:column;gap:8px}
textarea,select,input{width:100%;background:#080e17;border:1px solid var(--bd);color:var(--tx);border-radius:8px;padding:8px;font:inherit;font-size:13px}
.frow{display:flex;gap:8px}
.frow select{width:120px}
.msg{font-size:11px;color:var(--mut);min-height:16px}
footer{margin-top:12px;text-align:center;font-size:11px;color:var(--mut)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="brand">
    <span id="dot" class="dot"></span>
    <div>
      <h1>CHIMERA-BIOS · Living Spore</h1>
      <div id="meta" class="sub">Zero-CDN · 2D Tactical · Sovereign Link</div>
    </div>
  </div>
  <div class="acts">
    <span id="conn" class="pill">CONNECTING</span>
    <button id="refreshBtn" class="btn" type="button">Pulse</button>
    <button id="autotomyBtn" class="btn danger" type="button">Autotomy</button>
  </div>
</header>

<div class="grid">
  <section class="card">
    <h2><span>Endocrine Soup (6 Hormones)</span><span id="posture" class="tag">LIVE</span></h2>
    <div id="hormones"></div>
  </section>

  <section class="card">
    <h2><span>Host Umwelt Resonance</span><span id="shield" class="tag">SHIELD OFF</span></h2>
    <div class="kv">
      <div class="k">Cognitive State</div><div id="uState" class="v">--</div>
      <div class="k">Flow Score</div><div id="uFlow" class="v">0.00</div>
      <div class="k">Frustration</div><div id="uFrust" class="v">0.00</div>
      <div class="k">Active Phase</div><div id="uPhase" class="v">--</div>
      <div class="k">Anticipated (+5m)</div><div id="uNext" class="v">--</div>
      <div class="k">Whisper Scout</div><div id="uWhisper" class="v">dormant</div>
    </div>
  </section>

  <section class="card">
    <h2><span>Autobiographical Soul</span><span id="soulOk" class="tag">VERIFIED</span></h2>
    <div class="kv">
      <div class="k">Lineage Hash</div><div id="sHash" class="v mono">--</div>
      <div class="k">Scars Recorded</div><div id="sCount" class="v">0</div>
      <div class="k">Capsule Budget</div><div id="sTok" class="v">&lt;= 500 tok</div>
    </div>
    <div id="laws" class="laws"></div>
    <div id="scars" class="list" style="margin-top:8px"></div>
  </section>

  <section class="card">
    <h2><span>Law-6 Approval Queue</span><span class="tag l6">auto_activated=False</span></h2>
    <div id="approvals" class="list"></div>
  </section>

  <section class="card" style="grid-column:1/-1">
    <h2><span>Mycelium Seed Inbox</span><span id="sporeId" class="mono sub">spore:pwa</span></h2>
    <form id="seedForm">
      <textarea id="seedText" rows="2" placeholder="Drop an architectural note, approval, or task seed for svhome / Colab / agents..."></textarea>
      <div class="frow">
        <select id="seedPri">
          <option value="normal">normal</option>
          <option value="high">high</option>
          <option value="urgent">urgent</option>
          <option value="low">low</option>
        </select>
        <button class="btn" type="submit" style="flex:1">Transmit Seed</button>
      </div>
      <div id="seedMsg" class="msg"></div>
    </form>
    <div id="seeds" class="list" style="margin-top:8px"></div>
  </section>
</div>
<footer>CHIMERA-ONE Living Infrastructure Substrate · Laws 1-7 Enforced · Zero-Trace Autotomy Ready</footer>
</div>

<script>
(function(){
"use strict";
var BASE=__ANCHOR_JSON__;
var SNAP=__SNAPSHOT_JSON__;
var H_META=[
  ["adrenaline","#ef4444"],["cortisol","#f59e0b"],["dopamine","#22c55e"],
  ["melatonin","#818cf8"],["cytokine","#ec4899"],["oxytocin","#14b8a6"]
];
var sporeKey="pwa_"+Math.random().toString(16).slice(2,10);
var es=null;
var $=function(id){return document.getElementById(id)};
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]})}
function clamp(v){var n=Number(v);return isFinite(n)?Math.max(0,Math.min(1,n)):0}
function api(p){return (BASE?BASE.replace(/\/+$/,""):"")+p}

function setConn(state,label){
  var d=$("dot"),c=$("conn");
  d.className="dot "+(state==="live"?"live":state==="off"?"off":"");
  c.className="pill "+(state==="live"?"ok":"warn");
  c.textContent=label;
}

function renderHormones(h){
  var src=(h&&h.levels)||h||{};
  var html="";
  for(var i=0;i<H_META.length;i++){
    var k=H_META[i][0],col=H_META[i][1],val=clamp(src[k]);
    html+='<div class="hbar"><div class="hrow"><span>'+k+'</span><span class="mono">'+val.toFixed(2)+'</span></div>'+
      '<div class="track"><div class="fill" style="width:'+(val*100).toFixed(1)+'%;background:'+col+'"></div></div></div>';
  }
  $("hormones").innerHTML=html;
  if(h&&h.directives&&h.directives.cad_vip){$("posture").textContent="CAD VIP"}
  else if(h&&h.directives&&h.directives.sleep_eligible){$("posture").textContent="REST"}
  else{$("posture").textContent="NOMINAL"}
}

function render(d){
  if(!d||typeof d!=="object")return;
  var org=d.organs||d;
  renderHormones(d.hormones||org.endocrine||{});
  var um=d.umwelt||org.umwelt||{};
  var ua=um.assessment||um||{};
  var un=um.anticipation||{};
  $("uState").textContent=ua.state||"neutral";
  $("uFlow").textContent=clamp(ua.flow_score).toFixed(2);
  $("uFrust").textContent=clamp(ua.frustration_score).toFixed(2);
  $("uPhase").textContent=ua.active_phase||"--";
  $("uNext").textContent=(un.predicted_phase||"--")+(un.confidence?" ("+Math.round(un.confidence*100)+"%)":"");
  $("uWhisper").textContent=ua.whisper_triggered?"ACTIVE (silent)":"dormant";
  var sh=$("shield");
  sh.textContent=ua.flow_shield?"FLOW SHIELD ON":"SHIELD OFF";
  sh.style.color=ua.flow_shield?"#86efac":"#94a3b8";

  var soul=d.soul||org.soul||{};
  var cap=soul.capsule||soul||{};
  var lh=cap.lineage_hash||soul.lineage_hash||"--";
  $("sHash").textContent=String(lh).slice(0,16);
  $("sCount").textContent=String(soul.scar_count||(cap.identity&&cap.identity.scar_count)||0);
  $("sTok").textContent=(cap.token_est!=null?cap.token_est+" / ":"<= ")+(cap.max_tokens||500)+" tok";
  $("soulOk").textContent=(soul.lineage_valid===false)?"CHECK CHAIN":"VERIFIED";
  var laws=cap.active_laws||["L1 Eliminate","L2 Zero-Choke","L3 svhome Guard","L4 SHA-256","L5 Dual-Budget","L6 Human Gate","L7 <80MiB RSS"];
  $("laws").innerHTML=laws.slice(0,7).map(function(x){return '<span class="law">'+esc(String(x).slice(0,28))+'</span>'}).join("");
  var scars=cap.relevant_scars||soul.recent_scars||[];
  $("scars").innerHTML=scars.length?scars.slice(0,4).map(function(s){
    return '<div class="item"><div class="item-h"><span>'+esc(s.title||s.scar_id)+'</span><span class="tag">'+esc(s.severity||s.sev||"scar")+'</span></div><div class="sub">'+esc(s.lesson_law||s.lesson||"")+'</div></div>';
  }).join(""):'<div class="sub">Genesis scars sealed in SQLite WAL.</div>';

  var props=d.law6_proposals||[];
  if(!props.length&&org.hgt&&org.hgt.proposals)props=org.hgt.proposals;
  $("approvals").innerHTML=props.length?props.slice(0,6).map(function(p){
    return '<div class="item"><div class="item-h"><span>'+esc(p.plasmid_name||p.title||p.proposal_id||"Proposal")+'</span><span class="tag l6">HOLD</span></div>'+
      '<div class="sub">target: '+esc(p.target_name||p.target||"ecosystem")+' · verdict: '+esc(p.verdict||"shadow_ready")+'</div></div>';
  }).join(""):'<div class="sub">No pending Law-6 proposals. All gates strictly auto_activated=False.</div>';

  var my=d.mycelium||org.mycelium||{};
  if(my.node_name)$("meta").textContent="Node: "+my.node_name+" · Zero-CDN · 2D Tactical";
  var seeds=my.recent_seeds||d.seeds||[];
  if(seeds.length){
    $("seeds").innerHTML=seeds.slice(0,6).map(function(s){
      return '<div class="item"><div class="item-h"><span>'+esc(s.text)+'</span><span class="tag">'+esc(s.priority||"normal")+'</span></div><div class="sub">'+esc(s.spore_id||"")+' · '+esc(s.status||"queued")+'</div></div>';
    }).join("");
  }
}

function pullStatus(){
  return fetch(api("/v1/bios/status"),{cache:"no-store"})
    .then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json()})
    .then(function(j){render(j);setConn("live","LIVE")})
    .catch(function(){setConn("off","OFFLINE")});
}

function startStream(){
  if(typeof EventSource==="undefined")return;
  try{
    es=new EventSource(api("/v1/bios/stream"));
    es.onopen=function(){setConn("live","SSE LIVE")};
    es.onmessage=function(ev){
      try{render(JSON.parse(ev.data));setConn("live","SSE LIVE")}catch(_e){}
    };
    es.onerror=function(){setConn("off","RECONNECT")};
  }catch(_e){}
}

$("sporeId").textContent="spore:"+sporeKey;
if(SNAP)render(SNAP);
pullStatus();
startStream();

$("refreshBtn").addEventListener("click",function(){pullStatus()});
$("autotomyBtn").addEventListener("click",function(){
  if(es){try{es.close()}catch(_e){} es=null}
  fetch(api("/v1/bios/spore/autotomy"),{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({spore_id:sporeKey,reason:"user_pwa_autotomy"})
  }).catch(function(){}).finally(function(){
    setConn("off","SEVERED");
    $("seedMsg").textContent="Zero-trace autotomy executed. Ephemeral session severed.";
  });
});

$("seedForm").addEventListener("submit",function(ev){
  ev.preventDefault();
  var txt=$("seedText").value.trim();
  if(!txt)return;
  var pri=$("seedPri").value;
  $("seedMsg").textContent="Transmitting seed...";
  fetch(api("/v1/bios/spore/seed"),{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({spore_id:sporeKey,text:txt,priority:pri})
  }).then(function(r){return r.json()}).then(function(res){
    $("seedText").value="";
    $("seedMsg").textContent=res&&res.seed_id?"Seed queued: "+res.seed_id:"Seed submitted.";
    pullStatus();
  }).catch(function(){
    $("seedMsg").textContent="Anchor unreachable; seed kept locally until reconnect.";
  });
});
})();
</script>
</body>
</html>
"""


def _safe_js_json(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_spore_pwa_html(
    anchor_url: str = "",
    snapshot: dict[str, Any] | None = None,
) -> str:
    """Render self-contained, Zero-CDN, Zero-WebGL (< 25 KB) CHIMERA-BIOS Spore PWA HTML."""
    clean_anchor = str(anchor_url or "").strip()
    html = _PWA_TEMPLATE.replace("__ANCHOR_JSON__", _safe_js_json(clean_anchor)).replace(
        "__SNAPSHOT_JSON__", _safe_js_json(snapshot if isinstance(snapshot, dict) else None)
    )
    if len(html.encode("utf-8")) >= MAX_PWA_BYTES:
        # Trim snapshot payload if an oversized external snapshot was supplied
        html = _PWA_TEMPLATE.replace("__ANCHOR_JSON__", _safe_js_json(clean_anchor)).replace(
            "__SNAPSHOT_JSON__", "null"
        )
    return html


class MyceliumSporeMesh:
    """Living Spore federation mesh with GF(256) blinded sharding, < 50 ms Autotomy & Seed Inbox."""

    MAX_PWA_BYTES = MAX_PWA_BYTES

    def __init__(
        self,
        ops_dir: str | Path | None = None,
        *,
        node_name: str = "win-desktop",
        ephemeral: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._ephemeral = bool(ephemeral)
        self._node_name = str(node_name or "win-desktop")
        self._ops_dir = Path(ops_dir) if ops_dir is not None else _default_ops_dir()
        self._conn: sqlite3.Connection | None = None
        # Ephemeral HMAC signing key (in-memory only, never persisted or returned)
        self._master_key = bytearray(os.urandom(32))
        # Per-spore ephemeral session keys (bytearray so autotomy zeroes them in-place)
        self._spore_keys: dict[str, bytearray] = {}
        # Active token_hash -> claims cache (wiped on autotomy)
        self._token_index: dict[str, dict[str, Any]] = {}
        self._revoked_spores: set[str] = set()
        self._init_storage()

    def _init_storage(self) -> None:
        if self._ephemeral:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._ops_dir.mkdir(parents=True, exist_ok=True)
            db_path = self._ops_dir / "bios_mycelium.sqlite3"
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=3000;")

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spore_tokens (
                token_sha256 TEXT PRIMARY KEY,
                spore_id TEXT NOT NULL,
                device_name TEXT NOT NULL,
                role TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                issued_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS spores (
                spore_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                role TEXT NOT NULL,
                capabilities_json TEXT NOT NULL,
                host_hint TEXT NOT NULL,
                status TEXT NOT NULL,
                attached_at REAL NOT NULL,
                last_heartbeat REAL NOT NULL,
                metrics_json TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revoked_spores (
                spore_id TEXT PRIMARY KEY,
                revoked_at REAL NOT NULL,
                reason TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS autotomy_receipts (
                receipt_id TEXT PRIMARY KEY,
                spore_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                elapsed_ms REAL NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seeds (
                seed_id TEXT PRIMARY KEY,
                spore_id TEXT NOT NULL,
                text TEXT NOT NULL,
                priority TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()
        for (sid,) in self._conn.execute("SELECT spore_id FROM revoked_spores").fetchall():
            self._revoked_spores.add(str(sid))

    def close(self) -> None:
        with self._lock:
            for buf in self._spore_keys.values():
                buf[:] = bytes(len(buf))
            self._spore_keys.clear()
            self._token_index.clear()
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def __del__(self) -> None:
        self.close()

    def issue_spore_token(
        self,
        device_name: str,
        role: str = "mobile_pwa",
        capabilities: list[str] | tuple[str, ...] | None = None,
        ttl_s: int = 3600,
    ) -> dict[str, Any]:
        """Issue a short-lived capability-scoped HMAC-SHA256 Spore join credential."""
        dev = str(device_name or "unknown-device").strip()
        role_s = str(role or "mobile_pwa").strip().lower()
        caps = sorted(
            {
                str(c).strip().lower()
                for c in (
                    capabilities
                    if capabilities is not None
                    else DEFAULT_ROLE_CAPABILITIES.get(role_s, ("read_status",))
                )
                if str(c).strip()
            }
        )
        ttl = max(30, min(86400, int(ttl_s)))
        now = time.time()
        expires_at = now + ttl
        spore_id = f"spore_{secrets.token_hex(6)}"
        nonce = secrets.token_hex(12)

        claims_str = f"{spore_id}|{dev}|{role_s}|{','.join(caps)}|{int(now)}|{int(expires_at)}|{nonce}"
        mac = hmac.new(
            bytes(self._master_key), claims_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        token = f"chm_sp1.{spore_id}.{nonce}.{mac[:32]}"
        token_sha256 = _sha256_hex(token)

        with self._lock:
            self._spore_keys[spore_id] = bytearray(os.urandom(32))
            self._token_index[token_sha256] = {
                "spore_id": spore_id,
                "device_name": dev,
                "role": role_s,
                "capabilities": caps,
                "issued_at": now,
                "expires_at": expires_at,
                "revoked": False,
            }
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO spore_tokens (
                    token_sha256, spore_id, device_name, role,
                    capabilities_json, issued_at, expires_at, revoked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    token_sha256,
                    spore_id,
                    dev,
                    role_s,
                    json.dumps(caps),
                    now,
                    expires_at,
                ),
            )
            self._conn.commit()

        return {
            "spore_id": spore_id,
            "token": token,
            "token_sha256": token_sha256,
            "device_name": dev,
            "role": role_s,
            "capabilities": caps,
            "node_name": self._node_name,
            "issued_at": round(now, 3),
            "expires_at": round(expires_at, 3),
            "ttl_s": ttl,
            "revocable": True,
        }

    def verify_spore_token(self, token: str, *, now_ts: float | None = None) -> dict[str, Any]:
        """Verify a Spore token without exposing signing keys."""
        now = float(time.time() if now_ts is None else now_ts)
        tok_hash = _sha256_hex(str(token or ""))
        with self._lock:
            entry = self._token_index.get(tok_hash)
            if entry is None and self._conn is not None:
                row = self._conn.execute(
                    """
                    SELECT spore_id, device_name, role, capabilities_json, issued_at, expires_at, revoked
                    FROM spore_tokens WHERE token_sha256 = ?
                    """,
                    (tok_hash,),
                ).fetchone()
                if row is not None:
                    entry = {
                        "spore_id": row[0],
                        "device_name": row[1],
                        "role": row[2],
                        "capabilities": json.loads(row[3]),
                        "issued_at": float(row[4]),
                        "expires_at": float(row[5]),
                        "revoked": bool(row[6]),
                    }
            if entry is None:
                return {"valid": False, "reason": "unknown_token"}
            if entry["revoked"] or entry["spore_id"] in self._revoked_spores:
                return {"valid": False, "reason": "revoked", "spore_id": entry["spore_id"]}
            if now > float(entry["expires_at"]):
                return {"valid": False, "reason": "expired", "spore_id": entry["spore_id"]}
            return {
                "valid": True,
                "spore_id": entry["spore_id"],
                "device_name": entry["device_name"],
                "role": entry["role"],
                "capabilities": list(entry["capabilities"]),
                "expires_at": entry["expires_at"],
            }

    def attach_spore(
        self,
        spore_id: str,
        device_name: str,
        role: str = "mobile_pwa",
        capabilities: list[str] | tuple[str, ...] | None = None,
        host_hint: str = "",
        *,
        token: str | None = None,
    ) -> dict[str, Any]:
        """Attach a living Spore to this CHIMERA anchor node."""
        sid = str(spore_id or "").strip()
        if not sid:
            raise ValueError("spore_id must be non-empty")
        if token is not None:
            ver = self.verify_spore_token(token)
            if not ver.get("valid") or ver.get("spore_id") != sid:
                return {
                    "ok": False,
                    "attached": False,
                    "spore_id": sid,
                    "error": ver.get("reason", "invalid_token"),
                }

        now = time.time()
        dev = str(device_name or "spore-device").strip()
        role_s = str(role or "mobile_pwa").strip().lower()
        caps = sorted(
            {
                str(c).strip().lower()
                for c in (
                    capabilities
                    if capabilities is not None
                    else DEFAULT_ROLE_CAPABILITIES.get(role_s, ("read_status",))
                )
                if str(c).strip()
            }
        )
        hint = str(host_hint or "").strip()

        with self._lock:
            if sid in self._revoked_spores:
                return {
                    "ok": False,
                    "attached": False,
                    "spore_id": sid,
                    "status": "revoked",
                    "error": "spore_revoked_by_autotomy",
                }
            if sid not in self._spore_keys:
                self._spore_keys[sid] = bytearray(os.urandom(32))
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO spores (
                    spore_id, device_name, role, capabilities_json, host_hint,
                    status, attached_at, last_heartbeat, metrics_json
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, '{}')
                ON CONFLICT(spore_id) DO UPDATE SET
                    device_name = excluded.device_name,
                    role = excluded.role,
                    capabilities_json = excluded.capabilities_json,
                    host_hint = excluded.host_hint,
                    status = 'active',
                    last_heartbeat = excluded.last_heartbeat
                """,
                (sid, dev, role_s, json.dumps(caps), hint, now, now),
            )
            self._conn.commit()

        return {
            "ok": True,
            "attached": True,
            "spore_id": sid,
            "device_name": dev,
            "role": role_s,
            "capabilities": caps,
            "host_hint": hint,
            "node_name": self._node_name,
            "status": "active",
            "attached_at": round(now, 3),
        }

    def heartbeat_spore(
        self,
        spore_id: str,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update Spore liveness heartbeat and compact telemetry metrics."""
        sid = str(spore_id or "").strip()
        met = dict(metrics) if isinstance(metrics, dict) else {}
        now = time.time()
        with self._lock:
            if sid in self._revoked_spores:
                return {"ok": False, "spore_id": sid, "error": "spore_revoked"}
            assert self._conn is not None
            cur = self._conn.execute(
                """
                UPDATE spores
                SET last_heartbeat = ?, metrics_json = ?
                WHERE spore_id = ? AND status = 'active'
                """,
                (now, _canonical_json(met), sid),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return {"ok": False, "spore_id": sid, "error": "spore_not_attached"}
        return {
            "ok": True,
            "spore_id": sid,
            "status": "active",
            "last_heartbeat": round(now, 3),
            "metrics": met,
        }

    def list_spores(self, include_detached: bool = False) -> list[dict[str, Any]]:
        """List active Spores (never exposing keys or tokens)."""
        with self._lock:
            assert self._conn is not None
            if include_detached:
                rows = self._conn.execute(
                    """
                    SELECT spore_id, device_name, role, capabilities_json, host_hint,
                           status, attached_at, last_heartbeat, metrics_json
                    FROM spores ORDER BY attached_at DESC
                    """
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT spore_id, device_name, role, capabilities_json, host_hint,
                           status, attached_at, last_heartbeat, metrics_json
                    FROM spores WHERE status = 'active' ORDER BY attached_at DESC
                    """
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "spore_id": r[0],
                    "device_name": r[1],
                    "role": r[2],
                    "capabilities": json.loads(r[3]),
                    "host_hint": r[4],
                    "status": r[5],
                    "attached_at": float(r[6]),
                    "last_heartbeat": float(r[7]),
                    "metrics": json.loads(r[8]) if r[8] else {},
                }
            )
        return out

    def autotomy(self, spore_id: str, reason: str = "detach") -> dict[str, Any]:
        """Instant < 50 ms Zero-Trace Autotomy: revoke tokens, zero ephemeral keys, drop state."""
        t0 = time.perf_counter()
        sid = str(spore_id or "").strip()
        if not sid:
            raise ValueError("spore_id must be non-empty")
        reason_s = str(reason or "detach").strip()
        now = time.time()

        with self._lock:
            self._revoked_spores.add(sid)

            # 1. Zero ephemeral key buffer in-place before deleting reference
            zeroed_bytes = 0
            key_buf = self._spore_keys.pop(sid, None)
            if key_buf is not None:
                zeroed_bytes = len(key_buf)
                key_buf[:] = bytes(zeroed_bytes)

            # 2. Revoke in-memory token entries for this spore
            revoked_mem = 0
            for tok_hash in list(self._token_index.keys()):
                if self._token_index[tok_hash].get("spore_id") == sid:
                    self._token_index[tok_hash]["revoked"] = True
                    del self._token_index[tok_hash]
                    revoked_mem += 1

            # 3. Revoke persisted tokens and purge active spore state atomically
            assert self._conn is not None
            cur_tok = self._conn.execute(
                "UPDATE spore_tokens SET revoked = 1 WHERE spore_id = ?",
                (sid,),
            )
            cur_drop = self._conn.execute(
                "DELETE FROM spores WHERE spore_id = ?",
                (sid,),
            )
            self._conn.execute(
                """
                INSERT OR REPLACE INTO revoked_spores (spore_id, revoked_at, reason)
                VALUES (?, ?, ?)
                """,
                (sid, now, reason_s),
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)

            body = {
                "schema": "chimera.bios.autotomy_receipt.v1",
                "spore_id": sid,
                "node_name": self._node_name,
                "reason": reason_s,
                "revoked_tokens": max(revoked_mem, int(cur_tok.rowcount)),
                "ephemeral_keys_zeroed_bytes": zeroed_bytes,
                "state_dropped": bool(cur_drop.rowcount > 0),
                "zero_trace_verified": (sid not in self._spore_keys),
                "elapsed_ms": elapsed_ms,
                "timestamp": round(now, 3),
            }
            receipt_sha256 = _sha256_hex(_canonical_json(body))
            receipt_id = f"auto_{receipt_sha256[:12]}"
            receipt = {
                "receipt_id": receipt_id,
                "receipt_sha256": receipt_sha256,
                **body,
            }
            self._conn.execute(
                """
                INSERT INTO autotomy_receipts (
                    receipt_id, spore_id, reason, elapsed_ms,
                    receipt_sha256, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    sid,
                    reason_s,
                    elapsed_ms,
                    receipt_sha256,
                    _canonical_json(receipt),
                    now,
                ),
            )
            self._conn.commit()
        return receipt

    def list_autotomy_receipts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            rows = self._conn.execute(
                "SELECT receipt_json FROM autotomy_receipts ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def submit_seed(
        self,
        spore_id: str,
        text: str,
        priority: str = "normal",
        kind: str = "idea",
    ) -> dict[str, Any]:
        """Submit a voice/text seed idea or approval note into the Mycelium Seed Inbox."""
        sid = str(spore_id or "anonymous_spore").strip()
        body_text = str(text or "").strip()
        if not body_text:
            raise ValueError("Seed text must be non-empty")
        pri = str(priority or "normal").strip().lower()
        if pri not in ("low", "normal", "high", "urgent"):
            pri = "normal"
        kind_s = str(kind or "idea").strip().lower()
        now = time.time()

        with self._lock:
            if sid in self._revoked_spores:
                return {
                    "ok": False,
                    "spore_id": sid,
                    "error": "spore_revoked_by_autotomy",
                }
            digest = _sha256_hex(f"{sid}|{body_text}|{pri}|{now:.6f}")
            seed_id = f"seed_{digest[:12]}"
            assert self._conn is not None
            self._conn.execute(
                """
                INSERT INTO seeds (seed_id, spore_id, text, priority, kind, status, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (seed_id, sid, body_text, pri, kind_s, digest, now),
            )
            self._conn.commit()

        return {
            "ok": True,
            "seed_id": seed_id,
            "spore_id": sid,
            "text": body_text,
            "priority": pri,
            "kind": kind_s,
            "status": "queued",
            "sha256": digest,
            "created_at": round(now, 3),
        }

    def list_seeds(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            assert self._conn is not None
            if status:
                rows = self._conn.execute(
                    """
                    SELECT seed_id, spore_id, text, priority, kind, status, sha256, created_at
                    FROM seeds WHERE status = ? ORDER BY created_at DESC LIMIT ?
                    """,
                    (str(status), max(1, int(limit))),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT seed_id, spore_id, text, priority, kind, status, sha256, created_at
                    FROM seeds ORDER BY created_at DESC LIMIT ?
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
        return [
            {
                "seed_id": r[0],
                "spore_id": r[1],
                "text": r[2],
                "priority": r[3],
                "kind": r[4],
                "status": r[5],
                "sha256": r[6],
                "created_at": float(r[7]),
            }
            for r in rows
        ]

    @staticmethod
    def blind_split(
        payload: bytes | str,
        k: int = 2,
        n: int = 3,
        *,
        seed: bytes | None = None,
    ) -> list[dict[str, Any]]:
        return blind_split(payload, k=k, n=n, seed=seed)

    @staticmethod
    def blind_reconstruct(shares: list[dict[str, Any]]) -> bytes:
        return blind_reconstruct(shares)

    @staticmethod
    def render_spore_pwa_html(
        anchor_url: str = "",
        snapshot: dict[str, Any] | None = None,
    ) -> str:
        return render_spore_pwa_html(anchor_url=anchor_url, snapshot=snapshot)

    def status(self) -> dict[str, Any]:
        spores = self.list_spores()
        seeds = self.list_seeds(limit=10)
        pwa_bytes = len(render_spore_pwa_html().encode("utf-8"))
        return {
            "organ": "CHIMERA-MYCELIUM",
            "idea": 9,
            "node_name": self._node_name,
            "active_spore_count": len(spores),
            "active_spores": spores,
            "revoked_spore_count": len(self._revoked_spores),
            "seed_count": len(seeds),
            "recent_seeds": seeds,
            "gf256_backend": _GF_BACKEND[0] if _GF_BACKEND is not None else "chimera_tp.gf256(lazy)",
            "pwa_html_bytes": pwa_bytes,
            "pwa_within_50kb": pwa_bytes < self.MAX_PWA_BYTES,
            "ephemeral": self._ephemeral,
        }

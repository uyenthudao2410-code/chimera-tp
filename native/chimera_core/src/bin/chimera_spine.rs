//! CHIMERA-MICRONUCLEUS (Rust Zero-Dependency Native Spine)
//!
//! 24/7 resident micro-spine (~3-6 MiB RSS, <15 ms cold boot, 0 GC pauses, 0 external crates):
//!   - Serves hot-path routes natively with 0 B Python loaded:
//!       GET  /healthz
//!       GET  /.well-known/chimera.json
//!       GET  /v1/spine/status
//!       GET  /v1/nixl/hormones       (direct 64-byte NIXL ring reader: bytes 32..63 ENDO)
//!       GET  /v1/peer/telemetry      (zero-subprocess kernel memory/uptime readout)
//!       GET  /v1/ghost/get?path=...  (<=16 MiB mtime-validated native Ghost Read-Ring)
//!       POST /v1/ghost/put           (populate native Ghost Read-Ring)
//!       POST /v1/spine/sleep-organ   (explicitly sleep ephemeral Python organ -> 0 B RSS)
//!   - Any complex route (/v1/bios/*, /v1/mnemosyne/*, /v1/prometheus/*, /mcp, etc.):
//!       Wakes the Ephemeral Python Organ worker on --organ-port, proxies HTTP transparently,
//!       and reaps it back to 0.00 MiB RSS after --idle-secs of organ inactivity.

use std::collections::{HashMap, VecDeque};
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, UNIX_EPOCH};

const MAX_GHOST_BYTES: usize = 16 * 1024 * 1024;
const MAX_SINGLE_FILE: usize = 2 * 1024 * 1024;

#[cfg(windows)]
mod win_mem {
    #[repr(C)]
    struct ProcessMemoryCounters {
        cb: u32,
        page_fault_count: u32,
        peak_working_set_size: usize,
        working_set_size: usize,
        quota_peak_paged_pool_usage: usize,
        quota_paged_pool_usage: usize,
        quota_peak_non_paged_pool_usage: usize,
        quota_non_paged_pool_usage: usize,
        pagefile_usage: usize,
        peak_pagefile_usage: usize,
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> isize;
    }

    #[link(name = "psapi")]
    extern "system" {
        fn K32GetProcessMemoryInfo(
            process: isize,
            ppsmem_counters: *mut ProcessMemoryCounters,
            cb: u32,
        ) -> i32;
    }

    pub fn self_rss_and_commit_mib() -> (f64, f64) {
        unsafe {
            let mut pmc: ProcessMemoryCounters = std::mem::zeroed();
            pmc.cb = std::mem::size_of::<ProcessMemoryCounters>() as u32;
            let h = GetCurrentProcess();
            if K32GetProcessMemoryInfo(h, &mut pmc, pmc.cb) != 0 {
                return (
                    (pmc.working_set_size as f64) / 1048576.0,
                    (pmc.pagefile_usage as f64) / 1048576.0,
                );
            }
        }
        (0.0, 0.0)
    }
}

#[cfg(not(windows))]
mod win_mem {
    use std::fs;
    pub fn self_rss_and_commit_mib() -> (f64, f64) {
        let mut rss_kb: f64 = 0.0;
        let mut hwm_kb: f64 = 0.0;
        if let Ok(txt) = fs::read_to_string("/proc/self/status") {
            for line in txt.lines() {
                if let Some(rest) = line.strip_prefix("VmRSS:") {
                    if let Some(tok) = rest.split_whitespace().next() {
                        rss_kb = tok.parse::<f64>().unwrap_or(0.0);
                    }
                } else if let Some(rest) = line.strip_prefix("VmHWM:") {
                    if let Some(tok) = rest.split_whitespace().next() {
                        hwm_kb = tok.parse::<f64>().unwrap_or(0.0);
                    }
                }
            }
        }
        (rss_kb / 1024.0, hwm_kb / 1024.0)
    }
}

struct GhostEntry {
    mtime_ns: u128,
    size: u64,
    data: Vec<u8>,
}

struct GhostRing {
    entries: HashMap<String, GhostEntry>,
    order: VecDeque<String>,
    total_bytes: usize,
    hits: u64,
    misses: u64,
    puts: u64,
    bytes_saved: u64,
}

impl GhostRing {
    fn new() -> Self {
        Self {
            entries: HashMap::new(),
            order: VecDeque::new(),
            total_bytes: 0,
            hits: 0,
            misses: 0,
            puts: 0,
            bytes_saved: 0,
        }
    }

    fn file_meta(path: &str) -> Option<(u128, u64)> {
        let md = fs::metadata(path).ok()?;
        if !md.is_file() || (md.len() as usize) > MAX_SINGLE_FILE {
            return None;
        }
        let mtime = md
            .modified()
            .ok()?
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_nanos();
        Some((mtime, md.len()))
    }

    fn get_or_load(&mut self, path: &str) -> Option<(Vec<u8>, bool)> {
        let (mtime_ns, size) = Self::file_meta(path)?;
        if let Some(ent) = self.entries.get(path) {
            if ent.mtime_ns == mtime_ns && ent.size == size {
                self.hits += 1;
                self.bytes_saved += size;
                return Some((ent.data.clone(), true));
            }
        }
        self.misses += 1;
        let data = fs::read(path).ok()?;
        self.insert_internal(path.to_string(), mtime_ns, size, data.clone());
        Some((data, false))
    }

    fn put_path(&mut self, path: &str) -> bool {
        let Some((mtime_ns, size)) = Self::file_meta(path) else {
            return false;
        };
        let Ok(data) = fs::read(path) else {
            return false;
        };
        self.insert_internal(path.to_string(), mtime_ns, size, data);
        true
    }

    fn insert_internal(&mut self, key: String, mtime_ns: u128, size: u64, data: Vec<u8>) {
        if let Some(old) = self.entries.remove(&key) {
            self.total_bytes = self.total_bytes.saturating_sub(old.data.len());
        }
        self.total_bytes += data.len();
        self.entries.insert(
            key.clone(),
            GhostEntry {
                mtime_ns,
                size,
                data,
            },
        );
        self.order.push_back(key);
        self.puts += 1;
        while self.total_bytes > MAX_GHOST_BYTES {
            if let Some(evict_key) = self.order.pop_front() {
                if let Some(ent) = self.entries.remove(&evict_key) {
                    self.total_bytes = self.total_bytes.saturating_sub(ent.data.len());
                }
            } else {
                break;
            }
        }
    }
}

struct OrganManager {
    organ_port: u16,
    organ_cmd: Vec<String>,
    idle_secs: u64,
    child: Option<Child>,
    last_used: Instant,
    wakes: u64,
    sleeps: u64,
    last_wake_ms: f64,
}

impl OrganManager {
    fn new(organ_port: u16, organ_cmd: Vec<String>, idle_secs: u64) -> Self {
        Self {
            organ_port,
            organ_cmd,
            idle_secs,
            child: None,
            last_used: Instant::now(),
            wakes: 0,
            sleeps: 0,
            last_wake_ms: 0.0,
        }
    }

    fn is_awake(&mut self) -> bool {
        if let Some(ref mut ch) = self.child {
            match ch.try_wait() {
                Ok(Some(_)) => {
                    self.child = None;
                    false
                }
                Ok(None) => true,
                Err(_) => {
                    self.child = None;
                    false
                }
            }
        } else {
            false
        }
    }

    fn ensure_awake(&mut self) -> bool {
        self.last_used = Instant::now();
        if self.is_awake() {
            return true;
        }
        if self.organ_cmd.is_empty() || self.organ_port == 0 {
            return false;
        }
        let t0 = Instant::now();
        let mut cmd = Command::new(&self.organ_cmd[0]);
        if self.organ_cmd.len() > 1 {
            cmd.args(&self.organ_cmd[1..]);
        }
        cmd.stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let Ok(child) = cmd.spawn() else {
            return false;
        };
        self.child = Some(child);
        let addr = SocketAddr::from(([127, 0, 0, 1], self.organ_port));
        let deadline = Instant::now() + Duration::from_secs(8);
        while Instant::now() < deadline {
            if TcpStream::connect_timeout(&addr, Duration::from_millis(120)).is_ok() {
                self.wakes += 1;
                self.last_wake_ms = t0.elapsed().as_secs_f64() * 1000.0;
                self.last_used = Instant::now();
                return true;
            }
            thread::sleep(Duration::from_millis(35));
        }
        self.sleep_now();
        false
    }

    fn sleep_now(&mut self) -> bool {
        if let Some(mut ch) = self.child.take() {
            let _ = ch.kill();
            let _ = ch.wait();
            self.sleeps += 1;
            return true;
        }
        false
    }

    fn maybe_reap_idle(&mut self) {
        if self.is_awake() && self.last_used.elapsed() >= Duration::from_secs(self.idle_secs) {
            self.sleep_now();
        }
    }
}

struct SpineState {
    port: u16,
    nixl_path: String,
    started_at: Instant,
    requests_native: AtomicU64,
    requests_proxied: AtomicU64,
    ghost: Mutex<GhostRing>,
    organ: Mutex<OrganManager>,
    shutdown: AtomicBool,
}

fn json_escape(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push(' '),
            c => out.push(c),
        }
    }
    out
}

fn url_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(hex_str) = std::str::from_utf8(&bytes[i + 1..i + 3]) {
                if let Ok(val) = u8::from_str_radix(hex_str, 16) {
                    out.push(val);
                    i += 3;
                    continue;
                }
            }
        } else if bytes[i] == b'+' {
            out.push(b' ');
            i += 1;
            continue;
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn read_nixl_hormones_json(nixl_path: &str) -> String {
    let Ok(bytes) = fs::read(nixl_path) else {
        return format!(
            "{{\"ok\":false,\"error\":\"nixl_ring_not_found\",\"path\":\"{}\"}}",
            json_escape(nixl_path)
        );
    };
    if bytes.len() < 64 {
        return format!(
            "{{\"ok\":false,\"error\":\"nixl_ring_too_short\",\"len\":{}}}",
            bytes.len()
        );
    }
    let slice = &bytes[32..64];
    let magic = String::from_utf8_lossy(&slice[0..4]).into_owned();
    let seq = u16::from_le_bytes([slice[4], slice[5]]);
    let crc = u16::from_le_bytes([slice[6], slice[7]]);
    let mut vals = [0.0f32; 6];
    for (idx, slot) in vals.iter_mut().enumerate() {
        let off = 8 + idx * 4;
        *slot = f32::from_le_bytes([slice[off], slice[off + 1], slice[off + 2], slice[off + 3]]);
    }
    format!(
        "{{\"ok\":true,\"source\":\"native_rust_64b_ring\",\"magic\":\"{}\",\"seq\":{},\"crc16\":{},\"hormones\":{{\"adrenaline\":{:.4},\"cortisol\":{:.4},\"dopamine\":{:.4},\"melatonin\":{:.4},\"cytokine\":{:.4},\"oxytocin\":{:.4}}}}}",
        json_escape(&magic),
        seq,
        crc,
        vals[0],
        vals[1],
        vals[2],
        vals[3],
        vals[4],
        vals[5]
    )
}

fn send_http(stream: &mut TcpStream, status: u16, reason: &str, content_type: &str, body: &[u8]) {
    let header = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\nX-Chimera-Engine: micronucleus-rs\r\n\r\n",
        status,
        reason,
        content_type,
        body.len()
    );
    let _ = stream.write_all(header.as_bytes());
    let _ = stream.write_all(body);
    let _ = stream.flush();
}

fn extract_json_string_field(body: &str, key: &str) -> Option<String> {
    let needle = format!("\"{}\"", key);
    let pos = body.find(&needle)?;
    let rest = &body[pos + needle.len()..];
    let colon = rest.find(':')?;
    let after = rest[colon + 1..].trim_start();
    if !after.starts_with('"') {
        return None;
    }
    let mut out = String::new();
    let mut chars = after[1..].chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(esc) = chars.next() {
                match esc {
                    'n' => out.push('\n'),
                    'r' => out.push('\r'),
                    't' => out.push('\t'),
                    '\\' => out.push('\\'),
                    '"' => out.push('"'),
                    other => out.push(other),
                }
            }
        } else if c == '"' {
            return Some(out);
        } else {
            out.push(c);
        }
    }
    None
}

fn proxy_to_organ(
    client: &mut TcpStream,
    raw_request: &[u8],
    state: &Arc<SpineState>,
) -> bool {
    let organ_port = {
        let mut mgr = state.organ.lock().unwrap();
        if !mgr.ensure_awake() {
            return false;
        }
        mgr.organ_port
    };
    let addr = SocketAddr::from(([127, 0, 0, 1], organ_port));
    let Ok(mut upstream) = TcpStream::connect_timeout(&addr, Duration::from_secs(3)) else {
        return false;
    };
    let _ = upstream.set_read_timeout(Some(Duration::from_secs(10)));
    let _ = upstream.set_write_timeout(Some(Duration::from_secs(5)));
    if upstream.write_all(raw_request).is_err() {
        return false;
    }
    let _ = upstream.shutdown(Shutdown::Write);
    let mut resp = Vec::new();
    let _ = upstream.read_to_end(&mut resp);
    if resp.is_empty() {
        return false;
    }
    state.requests_proxied.fetch_add(1, Ordering::Relaxed);
    let _ = client.write_all(&resp);
    let _ = client.flush();
    true
}

fn handle_client(mut stream: TcpStream, state: Arc<SpineState>) {
    let _ = stream.set_nonblocking(false);
    let _ = stream.set_read_timeout(Some(Duration::from_secs(4)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(4)));
    let mut buf = vec![0u8; 65536];
    let n = match stream.read(&mut buf) {
        Ok(n) if n > 0 => n,
        _ => return,
    };
    buf.truncate(n);
    let req_str = String::from_utf8_lossy(&buf);
    let first_line = req_str.lines().next().unwrap_or("");
    let mut parts = first_line.split_whitespace();
    let method = parts.next().unwrap_or("GET");
    let target = parts.next().unwrap_or("/");
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p, q),
        None => (target, ""),
    };
    let body_str = req_str
        .split_once("\r\n\r\n")
        .map(|(_, b)| b)
        .unwrap_or("");

    let pid = std::process::id();
    let uptime = state.started_at.elapsed().as_secs_f64();

    if method == "GET" && (path == "/healthz" || path == "/v1/spine/status") {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let (rss_mib, commit_mib) = win_mem::self_rss_and_commit_mib();
        let (organ_awake, wakes, sleeps, last_wake_ms, organ_port) = {
            let mut o = state.organ.lock().unwrap();
            let aw = o.is_awake();
            (aw, o.wakes, o.sleeps, o.last_wake_ms, o.organ_port)
        };
        let (g_entries, g_hits, g_misses, g_saved) = {
            let g = state.ghost.lock().unwrap();
            (g.entries.len(), g.hits, g.misses, g.bytes_saved)
        };
        let organ_state = if organ_awake {
            "awake"
        } else {
            "sleeping_0_bytes"
        };
        let json = format!(
            "{{\"ok\":true,\"engine\":\"chimera-micronucleus-rs\",\"pid\":{},\"port\":{},\"rss_mib\":{:.3},\"commit_mib\":{:.3},\"uptime_s\":{:.2},\"python_organ_state\":\"{}\",\"python_organ_port\":{},\"python_organ_rss_when_sleeping_mib\":0.0,\"organ_wakes\":{},\"organ_sleeps\":{},\"last_wake_ms\":{:.2},\"requests_native\":{},\"requests_proxied\":{},\"ghost_ring\":{{\"entries\":{},\"hits\":{},\"misses\":{},\"bytes_saved\":{}}}}}",
            pid,
            state.port,
            rss_mib,
            commit_mib,
            uptime,
            organ_state,
            organ_port,
            wakes,
            sleeps,
            last_wake_ms,
            state.requests_native.load(Ordering::Relaxed),
            state.requests_proxied.load(Ordering::Relaxed),
            g_entries,
            g_hits,
            g_misses,
            g_saved
        );
        send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
        return;
    }

    if method == "GET" && path == "/.well-known/chimera.json" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let (rss_mib, _) = win_mem::self_rss_and_commit_mib();
        let json = format!(
            "{{\"ok\":true,\"schema\":\"chimera.capabilities.v1\",\"engine\":\"chimera-micronucleus-rs\",\"pid\":{},\"rss_mib\":{:.3},\"port\":{},\"hot_path_python_loaded\":false}}",
            pid, rss_mib, state.port
        );
        send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
        return;
    }

    if method == "GET" && path == "/v1/nixl/hormones" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let json = read_nixl_hormones_json(&state.nixl_path);
        send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
        return;
    }

    if method == "GET" && path == "/v1/peer/telemetry" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let (rss_mib, commit_mib) = win_mem::self_rss_and_commit_mib();
        let json = format!(
            "{{\"ok\":true,\"engine\":\"chimera-micronucleus-rs\",\"pid\":{},\"rss_mib\":{:.3},\"commit_mib\":{:.3},\"uptime_s\":{:.2},\"zero_python_hot_path\":true}}",
            pid, rss_mib, commit_mib, uptime
        );
        send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
        return;
    }

    if method == "GET" && path == "/v1/ghost/get" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let target_path = query
            .split('&')
            .find_map(|kv| kv.strip_prefix("path="))
            .map(url_decode)
            .unwrap_or_default();
        if target_path.is_empty() {
            send_http(&mut stream, 400, "Bad Request", "application/json", b"{\"ok\":false,\"error\":\"path_required\"}");
            return;
        }
        let res = {
            let mut g = state.ghost.lock().unwrap();
            g.get_or_load(&target_path)
        };
        match res {
            Some((data, hit)) => {
                let preview = String::from_utf8_lossy(&data[..data.len().min(512)]);
                let json = format!(
                    "{{\"ok\":true,\"hit\":{},\"bytes\":{},\"preview\":\"{}\"}}",
                    hit,
                    data.len(),
                    json_escape(&preview)
                );
                send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
            }
            None => {
                send_http(&mut stream, 404, "Not Found", "application/json", b"{\"ok\":false,\"error\":\"file_not_found\"}");
            }
        }
        return;
    }

    if method == "POST" && path == "/v1/ghost/put" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let target_path = extract_json_string_field(body_str, "path").unwrap_or_default();
        let ok = if target_path.is_empty() {
            false
        } else {
            let mut g = state.ghost.lock().unwrap();
            g.put_path(&target_path)
        };
        let json = format!("{{\"ok\":{},\"path\":\"{}\"}}", ok, json_escape(&target_path));
        send_http(
            &mut stream,
            if ok { 200 } else { 400 },
            if ok { "OK" } else { "Bad Request" },
            "application/json",
            json.as_bytes(),
        );
        return;
    }

    if method == "POST" && path == "/v1/spine/sleep-organ" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        let slept = {
            let mut o = state.organ.lock().unwrap();
            o.sleep_now()
        };
        let json = format!(
            "{{\"ok\":true,\"slept\":{},\"python_organ_state\":\"sleeping_0_bytes\"}}",
            slept
        );
        send_http(&mut stream, 200, "OK", "application/json", json.as_bytes());
        return;
    }

    if method == "POST" && path == "/v1/spine/shutdown" {
        state.requests_native.fetch_add(1, Ordering::Relaxed);
        {
            let mut o = state.organ.lock().unwrap();
            o.sleep_now();
        }
        state.shutdown.store(true, Ordering::SeqCst);
        send_http(&mut stream, 200, "OK", "application/json", b"{\"ok\":true,\"shutting_down\":true}");
        return;
    }

    // Complex route -> wake ephemeral Python organ on demand and proxy transparently
    if proxy_to_organ(&mut stream, &buf, &state) {
        return;
    }
    send_http(
        &mut stream,
        503,
        "Service Unavailable",
        "application/json",
        b"{\"ok\":false,\"error\":\"ephemeral_organ_not_configured_or_unavailable\"}",
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mut port: u16 = 9795;
    let mut organ_port: u16 = 0;
    let mut idle_secs: u64 = 60;
    let mut nixl_path = if cfg!(windows) {
        String::from(r"V:\nixl\chimera_nixl_ring.bin")
    } else {
        String::from("/dev/shm/chimera_nixl_ring.bin")
    };
    let mut organ_cmd: Vec<String> = Vec::new();

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--port" if i + 1 < args.len() => {
                port = args[i + 1].parse().unwrap_or(port);
                i += 2;
            }
            "--organ-port" if i + 1 < args.len() => {
                organ_port = args[i + 1].parse().unwrap_or(0);
                i += 2;
            }
            "--idle-secs" if i + 1 < args.len() => {
                idle_secs = args[i + 1].parse().unwrap_or(60).max(1);
                i += 2;
            }
            "--nixl-path" if i + 1 < args.len() => {
                nixl_path = args[i + 1].clone();
                i += 2;
            }
            "--organ-cmd" => {
                i += 1;
                while i < args.len() {
                    organ_cmd.push(args[i].clone());
                    i += 1;
                }
            }
            _ => {
                i += 1;
            }
        }
    }

    let listener = TcpListener::bind(("127.0.0.1", port)).expect("failed to bind chimera_spine");
    let bound_port = listener.local_addr().unwrap().port();
    let _ = listener.set_nonblocking(true);

    let state = Arc::new(SpineState {
        port: bound_port,
        nixl_path,
        started_at: Instant::now(),
        requests_native: AtomicU64::new(0),
        requests_proxied: AtomicU64::new(0),
        ghost: Mutex::new(GhostRing::new()),
        organ: Mutex::new(OrganManager::new(organ_port, organ_cmd, idle_secs)),
        shutdown: AtomicBool::new(false),
    });

    // Background idle reaper for ephemeral Python organ -> returns Python RSS to 0.00 MiB
    let reap_state = Arc::clone(&state);
    thread::spawn(move || {
        while !reap_state.shutdown.load(Ordering::Relaxed) {
            thread::sleep(Duration::from_millis(500));
            let mut o = reap_state.organ.lock().unwrap();
            o.maybe_reap_idle();
        }
    });

    let (rss_mib, _) = win_mem::self_rss_and_commit_mib();
    println!(
        "{{\"ok\":true,\"event\":\"chimera_spine_ready\",\"engine\":\"chimera-micronucleus-rs\",\"pid\":{},\"port\":{},\"boot_rss_mib\":{:.3}}}",
        std::process::id(),
        bound_port,
        rss_mib
    );

    while !state.shutdown.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                let st = Arc::clone(&state);
                thread::spawn(move || handle_client(stream, st));
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(8));
            }
            Err(_) => {
                thread::sleep(Duration::from_millis(20));
            }
        }
    }

    let mut o = state.organ.lock().unwrap();
    o.sleep_now();
}

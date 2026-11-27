#![windows_subsystem = "console"]
//! Ultra-fast (< 2 ms warm) native Antigravity 2.0 lifecycle hook forwarder for Chimera Omega-Spine.
//! Zero external crates: pure Rust `std::net::TcpStream` with strict fail-open guarantees.
//!
//! Usage: chimera-hook.exe <event_name>
//! Env:   CHIMERA_HOOK_URL (default: http://127.0.0.1:9780)

use std::env;
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::{Duration, Instant};

const DEFAULT_URL: &str = "http://127.0.0.1:9780";
const MAX_STDIN_BYTES: usize = 2 * 1024 * 1024;
const MAX_RESPONSE_BYTES: usize = 4 * 1024 * 1024;
const DEFAULT_CONNECT_TIMEOUT_MS: u64 = 200;
const DEFAULT_IO_TIMEOUT_MS: u64 = 600;

struct Endpoint {
    host: String,
    port: u16,
    host_header: String,
    base_path: String,
}

fn env_timeout_ms(name: &str, default_ms: u64, min_ms: u64, max_ms: u64) -> Duration {
    let val = env::var(name)
        .ok()
        .and_then(|s| s.trim().parse::<u64>().ok())
        .map(|v| v.clamp(min_ms, max_ms))
        .unwrap_or(default_ms);
    Duration::from_millis(val)
}

fn sanitize_event(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len().min(64));
    for b in raw.bytes() {
        if out.len() >= 64 {
            break;
        }
        if b.is_ascii_alphanumeric() || b == b'_' || b == b'-' {
            out.push((b as char).to_ascii_lowercase());
        }
    }
    if out.is_empty() {
        "unknown".to_string()
    } else {
        out
    }
}

fn parse_endpoint(raw_url: &str) -> Option<Endpoint> {
    let trimmed = raw_url.trim();
    if trimmed.is_empty() {
        return None;
    }
    let rest = if let Some(r) = trimmed.strip_prefix("http://") {
        r
    } else if trimmed.starts_with("https://") {
        // Pure std loopback HTTP client does not speak TLS; fail open.
        return None;
    } else if trimmed.contains("://") {
        return None;
    } else {
        trimmed
    };

    let (authority, path_part) = match rest.find('/') {
        Some(idx) => (&rest[..idx], &rest[idx..]),
        None => (rest, ""),
    };
    if authority.is_empty() {
        return None;
    }
    let base_path = path_part.trim_end_matches('/').to_string();

    let (host, port, host_header) = if let Some(after_open) = authority.strip_prefix('[') {
        let close = after_open.find(']')?;
        let ipv6 = &after_open[..close];
        let tail = &after_open[close + 1..];
        let port = if let Some(p_str) = tail.strip_prefix(':') {
            p_str.parse::<u16>().ok()?
        } else if tail.is_empty() {
            80
        } else {
            return None;
        };
        (ipv6.to_string(), port, authority.to_string())
    } else if let Some(colon) = authority.rfind(':') {
        let h = &authority[..colon];
        let p_str = &authority[colon + 1..];
        if h.is_empty() {
            return None;
        }
        let port = p_str.parse::<u16>().ok()?;
        (h.to_string(), port, authority.to_string())
    } else {
        (authority.to_string(), 80, authority.to_string())
    };

    if host.is_empty() || port == 0 {
        return None;
    }
    Some(Endpoint {
        host,
        port,
        host_header,
        base_path,
    })
}

fn resolve_addr(ep: &Endpoint) -> Option<SocketAddr> {
    // Fast path: direct numeric IP:port parse avoids DNS syscalls on loopback.
    let direct = if ep.host.contains(':') {
        format!("[{}]:{}", ep.host, ep.port)
    } else {
        format!("{}:{}", ep.host, ep.port)
    };
    if let Ok(addr) = direct.parse::<SocketAddr>() {
        return Some(addr);
    }
    (ep.host.as_str(), ep.port).to_socket_addrs().ok()?.next()
}

fn find_header_end(buf: &[u8]) -> Option<(usize, usize)> {
    for i in 0..buf.len().saturating_sub(3) {
        if &buf[i..i + 4] == b"\r\n\r\n" {
            return Some((i, i + 4));
        }
    }
    for i in 0..buf.len().saturating_sub(1) {
        if &buf[i..i + 2] == b"\n\n" {
            return Some((i, i + 2));
        }
    }
    None
}

fn parse_status_code(header_bytes: &[u8]) -> Option<u16> {
    let line_end = header_bytes
        .iter()
        .position(|&b| b == b'\r' || b == b'\n')
        .unwrap_or(header_bytes.len());
    let line = std::str::from_utf8(&header_bytes[..line_end]).ok()?;
    let mut parts = line.split_ascii_whitespace();
    let proto = parts.next()?;
    if !proto.starts_with("HTTP/1.") {
        return None;
    }
    parts.next()?.parse::<u16>().ok()
}

fn parse_headers(header_bytes: &[u8]) -> (Option<usize>, bool) {
    let mut content_length: Option<usize> = None;
    let mut chunked = false;
    let Ok(text) = std::str::from_utf8(header_bytes) else {
        return (None, false);
    };
    for line in text.lines().skip(1) {
        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim();
            let val = v.trim();
            if key.eq_ignore_ascii_case("content-length") {
                if let Ok(n) = val.parse::<usize>() {
                    content_length = Some(n);
                }
            } else if key.eq_ignore_ascii_case("transfer-encoding")
                && val.to_ascii_lowercase().contains("chunked")
            {
                chunked = true;
            }
        }
    }
    (content_length, chunked)
}

fn decode_chunked(raw: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::with_capacity(raw.len());
    let mut pos = 0usize;
    while pos < raw.len() {
        let mut line_end = pos;
        while line_end + 1 < raw.len() && !(raw[line_end] == b'\r' && raw[line_end + 1] == b'\n') {
            line_end += 1;
        }
        if line_end + 1 >= raw.len() {
            return None;
        }
        let size_str = std::str::from_utf8(&raw[pos..line_end]).ok()?;
        let hex_part = size_str.split(';').next()?.trim();
        let chunk_size = usize::from_str_radix(hex_part, 16).ok()?;
        pos = line_end + 2;
        if chunk_size == 0 {
            return Some(out);
        }
        if pos + chunk_size + 2 > raw.len() {
            return None;
        }
        if out.len() + chunk_size > MAX_RESPONSE_BYTES {
            return None;
        }
        out.extend_from_slice(&raw[pos..pos + chunk_size]);
        pos += chunk_size;
        if &raw[pos..pos + 2] != b"\r\n" {
            return None;
        }
        pos += 2;
    }
    None
}

/// Minimal strict JSON syntax checker requiring a top-level JSON object `{ ... }`.
struct JsonCheck<'a> {
    b: &'a [u8],
    i: usize,
}

impl<'a> JsonCheck<'a> {
    fn skip_ws(&mut self) {
        while self.i < self.b.len() && matches!(self.b[self.i], b' ' | b'\t' | b'\r' | b'\n') {
            self.i += 1;
        }
    }

    fn parse_string(&mut self) -> bool {
        if self.i >= self.b.len() || self.b[self.i] != b'"' {
            return false;
        }
        self.i += 1;
        while self.i < self.b.len() {
            let c = self.b[self.i];
            self.i += 1;
            if c == b'"' {
                return true;
            }
            if c < 0x20 {
                return false;
            }
            if c == b'\\' {
                if self.i >= self.b.len() {
                    return false;
                }
                let esc = self.b[self.i];
                self.i += 1;
                match esc {
                    b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't' => {}
                    b'u' => {
                        if self.i + 4 > self.b.len() {
                            return false;
                        }
                        for k in 0..4 {
                            if !self.b[self.i + k].is_ascii_hexdigit() {
                                return false;
                            }
                        }
                        self.i += 4;
                    }
                    _ => return false,
                }
            }
        }
        false
    }

    fn parse_number(&mut self) -> bool {
        if self.i < self.b.len() && self.b[self.i] == b'-' {
            self.i += 1;
        }
        if self.i >= self.b.len() {
            return false;
        }
        if self.b[self.i] == b'0' {
            self.i += 1;
        } else if self.b[self.i].is_ascii_digit() {
            while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        } else {
            return false;
        }
        if self.i < self.b.len() && self.b[self.i] == b'.' {
            self.i += 1;
            if self.i >= self.b.len() || !self.b[self.i].is_ascii_digit() {
                return false;
            }
            while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        }
        if self.i < self.b.len() && matches!(self.b[self.i], b'e' | b'E') {
            self.i += 1;
            if self.i < self.b.len() && matches!(self.b[self.i], b'+' | b'-') {
                self.i += 1;
            }
            if self.i >= self.b.len() || !self.b[self.i].is_ascii_digit() {
                return false;
            }
            while self.i < self.b.len() && self.b[self.i].is_ascii_digit() {
                self.i += 1;
            }
        }
        true
    }

    fn parse_value(&mut self, depth: u16) -> bool {
        if depth > 64 {
            return false;
        }
        self.skip_ws();
        if self.i >= self.b.len() {
            return false;
        }
        match self.b[self.i] {
            b'{' => self.parse_object(depth + 1),
            b'[' => self.parse_array(depth + 1),
            b'"' => self.parse_string(),
            b't' => self.consume_literal(b"true"),
            b'f' => self.consume_literal(b"false"),
            b'n' => self.consume_literal(b"null"),
            b'-' | b'0'..=b'9' => self.parse_number(),
            _ => false,
        }
    }

    fn consume_literal(&mut self, lit: &[u8]) -> bool {
        if self.b[self.i..].starts_with(lit) {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn parse_array(&mut self, depth: u16) -> bool {
        if self.i >= self.b.len() || self.b[self.i] != b'[' {
            return false;
        }
        self.i += 1;
        self.skip_ws();
        if self.i < self.b.len() && self.b[self.i] == b']' {
            self.i += 1;
            return true;
        }
        loop {
            if !self.parse_value(depth) {
                return false;
            }
            self.skip_ws();
            if self.i >= self.b.len() {
                return false;
            }
            match self.b[self.i] {
                b',' => self.i += 1,
                b']' => {
                    self.i += 1;
                    return true;
                }
                _ => return false,
            }
        }
    }

    fn parse_object(&mut self, depth: u16) -> bool {
        if self.i >= self.b.len() || self.b[self.i] != b'{' {
            return false;
        }
        self.i += 1;
        self.skip_ws();
        if self.i < self.b.len() && self.b[self.i] == b'}' {
            self.i += 1;
            return true;
        }
        loop {
            self.skip_ws();
            if !self.parse_string() {
                return false;
            }
            self.skip_ws();
            if self.i >= self.b.len() || self.b[self.i] != b':' {
                return false;
            }
            self.i += 1;
            if !self.parse_value(depth) {
                return false;
            }
            self.skip_ws();
            if self.i >= self.b.len() {
                return false;
            }
            match self.b[self.i] {
                b',' => self.i += 1,
                b'}' => {
                    self.i += 1;
                    return true;
                }
                _ => return false,
            }
        }
    }
}

fn is_valid_json_object(bytes: &[u8]) -> bool {
    if std::str::from_utf8(bytes).is_err() {
        return false;
    }
    let mut checker = JsonCheck { b: bytes, i: 0 };
    checker.skip_ws();
    if !checker.parse_object(0) {
        return false;
    }
    checker.skip_ws();
    checker.i == bytes.len()
}

fn trim_ascii_ws(mut s: &[u8]) -> &[u8] {
    while let Some(&first) = s.first() {
        if matches!(first, b' ' | b'\t' | b'\r' | b'\n') {
            s = &s[1..];
        } else {
            break;
        }
    }
    while let Some(&last) = s.last() {
        if matches!(last, b' ' | b'\t' | b'\r' | b'\n') {
            s = &s[..s.len() - 1];
        } else {
            break;
        }
    }
    s
}

fn forward_hook(event: &str, body: &[u8]) -> Option<Vec<u8>> {
    let url = env::var("CHIMERA_HOOK_URL").unwrap_or_else(|_| DEFAULT_URL.to_string());
    let ep = parse_endpoint(&url)?;
    let addr = resolve_addr(&ep)?;

    let connect_timeout = env_timeout_ms(
        "CHIMERA_HOOK_CONNECT_TIMEOUT_MS",
        DEFAULT_CONNECT_TIMEOUT_MS,
        20,
        5000,
    );
    let io_timeout = env_timeout_ms(
        "CHIMERA_HOOK_IO_TIMEOUT_MS",
        DEFAULT_IO_TIMEOUT_MS,
        50,
        5000,
    );

    let mut stream = TcpStream::connect_timeout(&addr, connect_timeout).ok()?;
    let _ = stream.set_nodelay(true);
    let _ = stream.set_write_timeout(Some(io_timeout));
    let _ = stream.set_read_timeout(Some(io_timeout));

    let payload: &[u8] = if body.is_empty() { b"{}" } else { body };
    let header = format!(
        "POST {}/v1/hook/{} HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\nUser-Agent: chimera-hook/1.0\r\n\r\n",
        ep.base_path,
        event,
        ep.host_header,
        payload.len()
    );

    let mut req = Vec::with_capacity(header.len() + payload.len());
    req.extend_from_slice(header.as_bytes());
    req.extend_from_slice(payload);
    stream.write_all(&req).ok()?;

    let deadline = Instant::now() + io_timeout;
    let mut resp = Vec::with_capacity(2048);
    let mut chunk = [0u8; 4096];
    let mut header_info: Option<(usize, Option<usize>, bool)> = None;

    loop {
        if Instant::now() >= deadline {
            return None;
        }
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => {
                if resp.len() + n > MAX_RESPONSE_BYTES {
                    return None;
                }
                resp.extend_from_slice(&chunk[..n]);
                if header_info.is_none() {
                    if let Some((hdr_end, body_start)) = find_header_end(&resp) {
                        let hdr_bytes = &resp[..hdr_end];
                        let status = parse_status_code(hdr_bytes)?;
                        if status != 200 {
                            return None;
                        }
                        let (cl, is_chunked) = parse_headers(hdr_bytes);
                        header_info = Some((body_start, cl, is_chunked));
                    }
                }
                if let Some((body_start, Some(cl), false)) = header_info {
                    if resp.len() >= body_start + cl {
                        break;
                    }
                }
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => return None,
        }
    }

    let (body_start, cl, is_chunked) = header_info?;
    let raw_body = &resp[body_start..];
    let decoded: Vec<u8> = if is_chunked {
        decode_chunked(raw_body)?
    } else if let Some(expected) = cl {
        if raw_body.len() < expected {
            return None;
        }
        raw_body[..expected].to_vec()
    } else {
        raw_body.to_vec()
    };

    let trimmed = trim_ascii_ws(&decoded);
    if trimmed.is_empty() || !is_valid_json_object(trimmed) {
        return None;
    }
    Some(trimmed.to_vec())
}

fn fail_open_payload(event: &str) -> &'static [u8] {
    if event == "pre_tool_use" {
        b"{\"decision\":\"allow\"}\n"
    } else {
        b"{}\n"
    }
}

fn main() {
    let raw_event = env::args().nth(1).unwrap_or_else(|| "unknown".to_string());
    let event = sanitize_event(&raw_event);

    let mut stdin_buf = Vec::with_capacity(1024);
    let _ = io::stdin()
        .take(MAX_STDIN_BYTES as u64)
        .read_to_end(&mut stdin_buf);

    let mut out = io::stdout().lock();
    match forward_hook(&event, &stdin_buf) {
        Some(resp_json) => {
            let _ = out.write_all(&resp_json);
            let _ = out.write_all(b"\n");
        }
        None => {
            let _ = out.write_all(fail_open_payload(&event));
        }
    }
    let _ = out.flush();
}

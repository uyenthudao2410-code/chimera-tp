//! Bounded, loopback-only TCP relay; upstreams must also be on loopback.
//! Use an authenticated SSH local forward as the upstream for a remote service.
use std::env;
use std::io::{self, Read, Write};
use std::net::{IpAddr, Shutdown, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

const MAX_CONNECTIONS: usize = 24;

fn endpoint(value: &str) -> io::Result<SocketAddr> {
    let address: SocketAddr = value.parse().map_err(|_| {
        io::Error::new(io::ErrorKind::InvalidInput, "expected a numeric loopback IP:port")
    })?;
    if !IpAddr::is_loopback(&address.ip()) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "loopback required"));
    }
    Ok(address)
}

fn pump(mut reader: TcpStream, mut writer: TcpStream) -> io::Result<()> {
    let mut buffer = [0u8; 16 * 1024];
    let result = loop {
        match reader.read(&mut buffer) {
            Ok(0) => break Ok(()),
            Ok(size) => {
                if let Err(error) = writer.write_all(&buffer[..size]) {
                    break Err(error);
                }
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => break Err(error),
        }
    };
    let _ = writer.shutdown(Shutdown::Write);
    if result.is_err() {
        let _ = reader.shutdown(Shutdown::Both);
        let _ = writer.shutdown(Shutdown::Both);
    }
    result
}

fn forward(client: TcpStream, upstream: SocketAddr) -> io::Result<()> {
    let server = TcpStream::connect_timeout(&upstream, Duration::from_secs(3))?;
    for socket in [&client, &server] {
        socket.set_nodelay(true)?;
        socket.set_read_timeout(Some(Duration::from_secs(120)))?;
        socket.set_write_timeout(Some(Duration::from_secs(120)))?;
    }
    let request = client.try_clone()?;
    let output = server.try_clone()?;
    let outgoing = thread::Builder::new().stack_size(128 * 1024)
        .spawn(move || pump(request, output))?;
    let response = pump(server, client);
    let sent = outgoing.join().map_err(|_| io::Error::other("relay thread failed"))?;
    response.and(sent)
}

fn main() -> io::Result<()> {
    let args: Vec<String> = env::args().skip(1).collect();
    let [listen, forward_to] = args.as_slice() else {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "usage: loopback_relay LISTEN UPSTREAM"));
    };
    let listener = TcpListener::bind(endpoint(listen)?)?;
    let upstream = endpoint(forward_to)?;
    if upstream.port() == 0 || listener.local_addr()? == upstream {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid upstream"));
    }
    println!("{}", listener.local_addr()?);
    io::stdout().flush()?;
    let count = Arc::new(AtomicUsize::new(0));
    for connection in listener.incoming() {
        let client = connection?;
        if count.load(Ordering::Relaxed) >= MAX_CONNECTIONS {
            drop(client);
            continue;
        }
        count.fetch_add(1, Ordering::Relaxed);
        let active = Arc::clone(&count);
        let worker = thread::Builder::new().stack_size(128 * 1024).spawn(move || {
            let _ = forward(client, upstream);
            active.fetch_sub(1, Ordering::Relaxed);
        });
        if worker.is_err() {
            count.fetch_sub(1, Ordering::Relaxed);
        }
    }
    Ok(())
}

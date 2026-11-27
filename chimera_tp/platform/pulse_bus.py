"""CHIMERA-PULSE: Zero-Redis (<3 MB RAM) Event Bus, Shared KV & Cross-Host Peer Relay."""

from __future__ import annotations

import collections
import fnmatch
import json
import threading
import time
import urllib.request
from datetime import datetime
from typing import Any, Callable


class PulseBus:
    """Bounded in-memory Pub/Sub event stream + TTL KV store with async cross-host relay."""

    def __init__(
        self,
        node_name: str = "local",
        max_events: int = 2000,
        max_kv_entries: int = 1024,
        peer_base_resolver: Callable[[], str] | None = None,
        fallback_peer_resolver: Callable[[], str] | None = None,
        on_flow: Callable[..., Any] | None = None,
        on_activity: Callable[[str, bool, int], None] | None = None,
        authorize_peer_request: Callable[[urllib.request.Request], None] | None = None,
    ) -> None:
        self.node_name = node_name
        self.max_events = int(max_events)
        self.max_kv_entries = int(max_kv_entries)
        self.peer_base_resolver = peer_base_resolver
        self.fallback_peer_resolver = fallback_peer_resolver
        self.on_flow = on_flow
        self.on_activity = on_activity
        self.authorize_peer_request = authorize_peer_request

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._seq: int = 0
        self._events: collections.deque[dict[str, Any]] = collections.deque(maxlen=self.max_events)
        self._kv: collections.OrderedDict[str, dict[str, Any]] = collections.OrderedDict()
        self._relayed_count: int = 0
        self._received_remote_count: int = 0
        self._activity_lock = threading.Lock()
        self._latest_relay_observed = 0

    def _observe(self, operation: str, success: bool, sequence: int) -> None:
        if self.on_activity is not None:
            try:
                # Relay threads can finish in a different order from publication.
                # An old peer acknowledgement cannot overwrite a newer refusal.
                if operation == "pulse.relay":
                    with self._activity_lock:
                        if sequence <= self._latest_relay_observed:
                            return
                        self._latest_relay_observed = sequence
                        self.on_activity(operation, success, sequence)
                else:
                    self.on_activity(operation, success, sequence)
            except Exception:
                # A telemetry failure cannot undo an already published event.
                pass

    def publish(
        self,
        topic: str,
        payload: Any,
        app: str = "system",
        relay: bool = True,
        origin_node: str | None = None,
    ) -> dict[str, Any]:
        orig = origin_node or self.node_name
        with self._cond:
            self._seq += 1
            ev = {
                "seq": self._seq,
                "ts_ms": int(time.time() * 1000),
                "ts": datetime.now().astimezone().strftime("%H:%M:%S"),
                "topic": str(topic).strip() or "default",
                "app": str(app or "system"),
                "origin": orig,
                "payload": payload,
            }
            self._events.append(ev)
            if origin_node and origin_node != self.node_name:
                self._received_remote_count += 1
            self._cond.notify_all()

        self._observe("pulse.publish", True, ev["seq"])
        if relay and orig == self.node_name and self.peer_base_resolver is not None:
            threading.Thread(target=self._relay_event_to_peer, args=(ev,), daemon=True).start()

        if self.on_flow is not None:
            try:
                self.on_flow(
                    "pulse",
                    app,
                    ev["topic"],
                    "PULSE_PUB",
                    wire_bytes=len(json.dumps(payload, default=str)),
                    elapsed_ms=0.05,
                    detail=f"seq={ev['seq']} origin={orig}",
                    ok=True,
                )
            except Exception:
                pass
        return ev

    def _relay_event_to_peer(self, ev: dict[str, Any]) -> None:
        candidates: list[str] = []
        for res_fn in (self.peer_base_resolver, self.fallback_peer_resolver):
            if res_fn is None:
                continue
            try:
                u = (res_fn() or "").rstrip("/")
                if u and u not in candidates:
                    candidates.append(u)
            except Exception:
                continue
        if not candidates:
            self._observe("pulse.relay", False, ev["seq"])
            return
        body = json.dumps(
            {
                "topic": ev["topic"],
                "payload": ev["payload"],
                "app": ev["app"],
                "origin_node": ev["origin"],
                "relay": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        expected = json.loads(body)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for peer_base in candidates:
            try:
                req = urllib.request.Request(
                    f"{peer_base}/v1/pulse/publish",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                if self.authorize_peer_request:
                    self.authorize_peer_request(req)
                with opener.open(req, timeout=3.0) as r:
                    # The peer's publish API echoes the committed event. A bare 200 does
                    # not confirm delivery and must not trigger another publish attempt.
                    limit = len(body) * 8 + 16 * 1024
                    reply = r.read(limit + 1)
                    try:
                        result = json.loads(reply) if len(reply) <= limit else None
                    except (ValueError, UnicodeError):
                        result = None
                    received = result.get("event") if isinstance(result, dict) else None
                    confirmed = (isinstance(received, dict) and result.get("ok") is True
                                 and type(received.get("seq")) is int and received["seq"] > 0
                                 and received.get("origin") == expected["origin_node"]
                                 and all(k in received and received[k] == expected[k]
                                         for k in ("topic", "payload", "app")))
                if not confirmed:
                    self._observe("pulse.relay", False, ev["seq"])
                    return
                with self._lock:
                    self._relayed_count += 1
                self._observe("pulse.relay", True, ev["seq"])
                return
            except Exception:
                continue
        self._observe("pulse.relay", False, ev["seq"])

    def poll(
        self,
        topic: str = "*",
        since: int = 0,
        limit: int = 50,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        pat = (topic or "*").strip()
        lim = max(1, min(500, int(limit)))
        deadline = time.monotonic() + min(15.0, max(0.0, float(wait_ms) / 1000.0))

        with self._cond:
            while True:
                matched = [
                    e
                    for e in self._events
                    if int(e["seq"]) > int(since)
                    and (pat == "*" or fnmatch.fnmatchcase(e["topic"], pat))
                ]
                if matched or time.monotonic() >= deadline:
                    return {
                        "ok": True,
                        "node": self.node_name,
                        "latest_seq": self._seq,
                        "events": matched[-lim:],
                    }
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(timeout=min(0.5, rem))
            return {
                "ok": True,
                "node": self.node_name,
                "latest_seq": self._seq,
                "events": [],
            }

    def kv_set(self, key: str, value: Any, ttl_s: float = 0.0, app: str = "system") -> dict[str, Any]:
        k = str(key).strip()
        exp = (time.monotonic() + float(ttl_s)) if float(ttl_s) > 0 else 0.0
        with self._lock:
            self._kv[k] = {
                "key": k,
                "value": value,
                "app": app,
                "expires_at": exp,
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._kv.move_to_end(k)
            while len(self._kv) > self.max_kv_entries:
                self._kv.popitem(last=False)
            return {"ok": True, "key": k, "ttl_s": float(ttl_s)}

    def kv_get(self, key: str) -> dict[str, Any]:
        k = str(key).strip()
        now = time.monotonic()
        with self._lock:
            entry = self._kv.get(k)
            if entry is None:
                return {"ok": True, "found": False, "key": k, "value": None}
            if entry["expires_at"] > 0 and now >= entry["expires_at"]:
                self._kv.pop(k, None)
                return {"ok": True, "found": False, "key": k, "value": None}
            self._kv.move_to_end(k)
            return {
                "ok": True,
                "found": True,
                "key": k,
                "value": entry["value"],
                "app": entry["app"],
                "updated_at": entry["updated_at"],
            }

    def stats(self) -> dict[str, Any]:
        with self._lock:
            topics = sorted({e["topic"] for e in self._events})
            return {
                "latest_seq": self._seq,
                "buffered_events": len(self._events),
                "kv_entries": len(self._kv),
                "active_topics": topics[:32],
                "relayed_to_peer": self._relayed_count,
                "received_from_peer": self._received_remote_count,
            }

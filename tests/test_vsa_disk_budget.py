"""Compatibility, rollback and streaming invariants for the persisted VSA ledger."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from chimera_tp.vsa_memory_service import SharedVsaMemoryService, VSA_BYTES


class DiskLedgerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "existing.db"
        self.vec = bytes(range(250)) * 5

    def service(self):
        service = SharedVsaMemoryService(self.db)
        self.addCleanup(service.close)
        return service

    def test_text_vectors_match_persisted_format_for_every_vote_count(self):
        import hashlib
        from chimera_tp.vsa_memory_service import encode_text_10k

        def legacy_atom(word):
            block = hashlib.blake2b(word.encode("utf-8"), digest_size=32).digest()
            raw = bytearray()
            while len(raw) < VSA_BYTES:
                block = hashlib.sha256(block).digest()
                raw.extend(block)
            return bytes(raw[:VSA_BYTES])

        # Check each 1,250-byte result against independent scalar bit counts.
        # Non-power-of-two lengths exercise comparison, repeated words exercise carries.
        words = (["alpha", "beta", "beta", "alpha", "field_43", "unit", "09"] * 7)[:48]
        atoms = {word: legacy_atom(word) for word in words}
        counts = [0] * (8 * VSA_BYTES)
        for n, word in enumerate(words, start=1):
            expected = bytearray(VSA_BYTES)
            for pos, byte in enumerate(atoms[word]):
                for bit in range(8):
                    k = 8 * pos + bit
                    counts[k] += (byte >> bit) & 1
                    if counts[k] * 2 >= n:
                        expected[pos] |= 1 << bit
            with self.subTest(token_count=n):
                self.assertEqual(encode_text_10k(" ".join(words[:n])), expected)
        self.assertEqual(encode_text_10k(" ".join(words) + " ignored suffix"), expected)
        self.assertEqual(encode_text_10k("x / !"), legacy_atom("empty"))
        self.assertEqual(encode_text_10k(" A / \u212AELVIN "), legacy_atom("kelvin"))
        self.assertEqual(encode_text_10k("repeat " * 48), legacy_atom("repeat"))

    def test_legacy_rows_order_domain_and_exact_payload(self):
        service = self.service()
        service.close()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for iid, domain, payload, vec in [
                ("z", "left", '"first"', self.vec),
                ("a", "left", 'legacy text', self.vec + b"padding"),
                ("m", "right", '{"tag":true}', self.vec),
                ("invalid", "left", 'null', self.vec[:-1]),
            ]:
                connection.execute("INSERT INTO vsa_items VALUES (?,?,?,?,?,?,?)",
                                   (iid, domain, iid, payload, vec, 1, "2024-05-03"))
        reopened = self.service()
        self.assertEqual(reopened.stats()["item_count"], 3)
        self.assertEqual(reopened._items, {})
        hits = reopened.recall(query_vsa_hex=self.vec.hex(), domain="left", top_k=2)
        self.assertEqual((hits["total_items"], hits["scanned"]), (3, 2))
        self.assertEqual([(m["item_id"], m["payload"]) for m in hits["matches"]],
                         [("z", "first"), ("a", "legacy text")])
        self.assertEqual([row["item_id"] for row in reopened.iter_export()], ["z", "a", "m"])
        self.assertEqual(len(bytes.fromhex(reopened.export_items()[1]["vsa_hex"])), VSA_BYTES)

    def test_export_keeps_its_snapshot_while_another_instance_commits(self):
        reader = self.service()
        writer = self.service()
        reader.store_batch([{"item_id": iid, "text": iid, "vsa_hex": self.vec.hex()}
                            for iid in ("first", "second")])
        with closing(reader.iter_export()) as entries:
            self.assertEqual(next(entries)["item_id"], "first")
            writer.store("second", text="changed", vsa_hex=self.vec.hex())
            writer.store("new", text="new entry", vsa_hex=self.vec.hex())
            self.assertEqual([(row["item_id"], row["text"]) for row in entries], [("second", "second")])
        self.assertEqual(reader.stats()["item_count"], 3)
        self.assertEqual({row["text"] for row in reader.export_items()}, {"first", "changed", "new entry"})

    def test_failed_batch_rolls_back_and_feedback_survives_repeated_updates(self):
        store = self.service()
        store.store("keep", text="original", vsa_hex=self.vec.hex())
        with self.assertRaises(TypeError):
            store.store_batch([{"item_id": "keep", "text": "should roll back"},
                               {"item_id": "bad", "payload": {"value": object()}}])
        self.assertEqual(store.export_items()[0]["text"], "original")
        store.record_causal_feedback(["keep", "keep"], success=True)
        store.store_batch([{"item_id": "keep", "payload": {"pass": i}} for i in (1, 2)])
        store.close()
        persisted = self.service().export_items()
        self.assertEqual(len(persisted), 1)
        payload = persisted[0]["payload"]
        self.assertEqual(payload["pass"], 2)
        self.assertEqual(payload["_midbrain"]["uses"], 2)
        self.assertTrue(payload["_midbrain"]["immune_pinned"])

    def test_memory_mode_preserves_the_same_ranking_and_pin_rules(self):
        memory = SharedVsaMemoryService()
        self.addCleanup(memory.close)
        disk = self.service()
        for backend in (memory, disk):
            backend.store_batch([{"item_id": str(i), "vsa_hex": self.vec.hex(), "reward": i + 1,
                                  "domain": "test", "payload": {"n": i}} for i in range(12)])
            backend.record_causal_feedback(["0"], success=True)
            backend.prune_low_value(max_items=6)
        def output(store):
            return [(m["item_id"], m["reward"], m["similarity"]) for m in
                    store.recall(domain="test", query_vsa_hex=self.vec.hex(), top_k=12)["matches"]]
        self.assertEqual(output(disk), output(memory))
        self.assertEqual(disk.immune_vault_summary(), memory.immune_vault_summary())

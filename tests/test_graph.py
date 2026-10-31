import copy
import tempfile
import unittest
from pathlib import Path
from research import Graph, validate


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "graph.db"
        self.graph = Graph(self.path)
        self.body = "Résumé 🎯: blue=12; red=8.\nSynthetic example only."
        self.source = self.graph.source("Café trial", "https://example.invalid/trial", self.body)
        self.claim = self.graph.claim("Blue lasted longer")
        self.other = self.graph.claim("Red lasted longer")

    def link(self):
        return self.graph.link(self.claim, self.source, 0, 24, relation="supports", note="Synthetic measurements")

    def test_exact_unicode_evidence_and_provenance(self):
        self.link()
        edge = self.graph.inspect(self.claim)["evidence"][0]
        self.assertEqual(edge["quote"], self.body[:24])
        self.assertEqual(edge["source_url"], "https://example.invalid/trial")
        self.assertEqual(len(edge["source_sha256"]), 64)

    def test_broken_references_and_invalid_spans(self):
        for claim, source, start, end in [("0"*32,self.source,0,2),(self.claim,"0"*32,0,2),(self.claim,self.source,-1,2),(self.claim,self.source,0,999),(self.claim,self.source,2,2),(self.claim,self.source,True,2)]:
            with self.assertRaises(ValueError):
                self.graph.link(claim,source,start,end,relation="supports",note="test")
        self.assertEqual(self.graph.export()["evidence"], [])

    def test_unsupported_relation_and_duplicate_evidence(self):
        import sqlite3
        with self.assertRaises(ValueError):
            self.graph.link(self.claim,self.source,0,2,relation="proves",note="invalid")
        self.link()
        with self.assertRaises(sqlite3.IntegrityError):
            self.link()
        self.assertEqual(len(self.graph.export()["evidence"]), 1)

    def test_conflict_is_symmetric_and_canonical(self):
        self.graph.conflict(self.other,self.claim,"Opposite measurements")
        self.assertEqual(self.graph.inspect(self.claim)["conflicts"][0]["claim"]["id"], self.other)
        self.assertEqual(self.graph.inspect(self.other)["conflicts"][0]["claim"]["id"], self.claim)
        pair = self.graph.export()["conflicts"][0]
        self.assertLess(pair["a"], pair["b"])
        with self.assertRaises(ValueError):
            self.graph.conflict(self.claim,self.claim,"Self conflict")
        with self.assertRaises(ValueError):
            self.graph.conflict(self.claim,"0"*32,"Unknown")

    def test_export_import_roundtrip(self):
        self.link()
        self.graph.conflict(self.claim,self.other,"Conflict")
        packet = self.graph.export()
        restored = Graph(Path(self.temp.name) / "restored.db")
        restored.import_packet(packet)
        self.assertEqual(restored.export(), packet)
        self.assertEqual(restored.inspect(self.claim), self.graph.inspect(self.claim))

    def test_import_rejects_quote_hash_and_reference_tampering(self):
        self.link()
        original = self.graph.export()
        altered = []
        bad = copy.deepcopy(original);bad["sources"][0]["body"] += "changed";altered.append(bad)
        bad = copy.deepcopy(original);bad["evidence"][0]["quote"] = "invented";altered.append(bad)
        bad = copy.deepcopy(original);bad["evidence"][0]["source"] = "0"*32;altered.append(bad)
        target = Graph(Path(self.temp.name) / "empty.db")
        for packet in altered:
            with self.assertRaises(ValueError):
                target.import_packet(packet)
            self.assertEqual(target.export()["claims"], [])

    def test_existing_graph_is_not_overwritten(self):
        before = self.graph.export()
        with self.assertRaises(ValueError):
            self.graph.import_packet(before)
        self.assertEqual(self.graph.export(), before)

    def test_duplicate_ids_and_conflicts_rejected(self):
        packet = self.graph.export()
        packet["claims"].append(packet["claims"][0].copy())
        with self.assertRaises(ValueError):
            validate(packet)
        self.graph.conflict(self.claim,self.other,"Conflict")
        packet = self.graph.export()
        packet["conflicts"].append(packet["conflicts"][0].copy())
        with self.assertRaises(ValueError):
            validate(packet)

    def test_search_sources_quotes_unicode_and_pagination(self):
        self.link()
        self.assertEqual(self.graph.search("CAFÉ")[0]["id"], self.claim)
        self.assertEqual(self.graph.search("blue=12")[0]["id"], self.claim)
        self.assertEqual(self.graph.search("%"), [])
        first = self.graph.search("longer",limit=1)
        second = self.graph.search("longer",limit=1,offset=1)
        self.assertNotEqual(first[0]["id"],second[0]["id"])

    def test_restart_and_source_integrity(self):
        self.link()
        self.assertEqual(Graph(self.path).export(),self.graph.export())
        with self.graph.db(True) as db:
            db.execute("UPDATE sources SET body='tampered' WHERE id=?",(self.source,))
        with self.assertRaises(ValueError):
            self.graph.export()

    def test_html_output_escapes_content_and_rejects_unsafe_urls(self):
        for reference in ["javascript:alert(1)","file:///tmp/file","https://user:password@example.invalid/x","https://example.invalid/has space"]:
            with self.assertRaises(ValueError):
                self.graph.source("Title",reference,"Body")
        self.graph.claim('<script>alert("x")</script>')
        page = self.graph.html_report()
        self.assertNotIn("<script>",page)
        self.assertIn("&lt;script&gt;",page)

    def test_empty_graph_and_input_limits(self):
        graph = Graph(Path(self.temp.name)/"blank.db")
        self.assertEqual(graph.export(),{"version":1,"sources":[],"claims":[],"evidence":[],"conflicts":[]})
        self.assertEqual(graph.search(""),[])
        with self.assertRaises(KeyError):
            graph.inspect("0"*32)
        for statement in ["", "x"*2001, "\x00"]:
            with self.assertRaises(ValueError):
                graph.claim(statement)
        with self.assertRaises(ValueError):
            graph.search("x",limit=True)


if __name__ == "__main__":
    unittest.main()

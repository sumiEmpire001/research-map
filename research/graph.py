import hashlib
import html
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from urllib.parse import urlsplit


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"Use nonempty text up to {limit} characters")
    return value


def url(value):
    text(value, 2000)
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Use a public-style HTTP(S) reference URL without credentials")
    return value


def sha(body):
    return hashlib.sha256(body.encode()).hexdigest()


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid graph ID")


def validate(packet):
    if not isinstance(packet, dict) or set(packet) != {"version", "sources", "claims", "evidence", "conflicts"} or type(packet["version"]) is not int or packet["version"] != 1:
        raise ValueError("Unsupported graph packet")
    expected = {"sources":{"id","title","url","body","sha256"}, "claims":{"id","text"},
                "evidence":{"id","claim","source","start","end","quote","relation","note"}, "conflicts":{"a","b","note"}}
    for kind, fields in expected.items():
        if not isinstance(packet[kind], list) or len(packet[kind]) > 10000 or any(not isinstance(row, dict) or set(row) != fields for row in packet[kind]):
            raise ValueError("Invalid or oversized graph collection: "+kind)
    sources, claims, evidence_ids, edge_keys, pairs = {}, {}, set(), set(), set()
    for source in packet["sources"]:
        ident(source["id"])
        text(source["title"], 200)
        text(source["body"], 1000000)
        url(source["url"])
        if source["id"] in sources or sha(source["body"]) != source["sha256"]:
            raise ValueError("Duplicate source or source checksum mismatch")
        sources[source["id"]] = source
    for claim in packet["claims"]:
        ident(claim["id"])
        text(claim["text"], 2000)
        if claim["id"] in claims:
            raise ValueError("Duplicate claim")
        claims[claim["id"]] = claim
    for edge in packet["evidence"]:
        ident(edge["id"])
        ident(edge["source"])
        ident(edge["claim"])
        text(edge["note"], 1000)
        source = sources.get(edge["source"])
        if edge["id"] in evidence_ids or source is None or edge["claim"] not in claims or edge["relation"] not in ("supports", "refutes", "context"):
            raise ValueError("Broken or duplicate evidence reference")
        a, b = edge["start"], edge["end"]
        if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(source["body"]) or source["body"][a:b] != edge["quote"]:
            raise ValueError("Evidence quote does not match source span")
        key = (edge["claim"],edge["source"],a,b,edge["relation"])
        if key in edge_keys:
            raise ValueError("Duplicate evidence span")
        evidence_ids.add(edge["id"])
        edge_keys.add(key)
    for pair in packet["conflicts"]:
        text(pair["note"], 1000)
        a, b = pair["a"], pair["b"]
        ident(a); ident(b)
        if a not in claims or b not in claims or a >= b or (a,b) in pairs:
            raise ValueError("Broken, repeated or noncanonical conflict")
        pairs.add((a,b))
    if len(json.dumps(packet, ensure_ascii=False).encode()) > 16*1024*1024:
        raise ValueError("Graph export exceeds 16 MiB")
    return packet


class Graph:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS sources(
                id TEXT PRIMARY KEY,title TEXT NOT NULL,url TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence(
                id TEXT PRIMARY KEY,claim TEXT NOT NULL REFERENCES claims(id),source TEXT NOT NULL REFERENCES sources(id),
                start INTEGER NOT NULL,end INTEGER NOT NULL,quote TEXT NOT NULL,relation TEXT NOT NULL,note TEXT NOT NULL,
                UNIQUE(claim,source,start,end,relation));
                CREATE TABLE IF NOT EXISTS conflicts(a TEXT NOT NULL REFERENCES claims(id),b TEXT NOT NULL REFERENCES claims(id),note TEXT NOT NULL,PRIMARY KEY(a,b));""")

    @contextmanager
    def db(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def source(self, title, reference_url, body):
        text(title,200); url(reference_url); text(body,1000000)
        key = uuid.uuid4().hex
        with self.db(True) as db:
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?)", (key,title,reference_url,body,sha(body)))
        return key

    def claim(self, statement):
        text(statement,2000)
        key = uuid.uuid4().hex
        with self.db(True) as db:
            db.execute("INSERT INTO claims VALUES(?,?)", (key,statement))
        return key

    def link(self, claim, source, start, end, *, relation, note):
        text(note,1000)
        if relation not in ("supports", "refutes", "context") or type(start) is not int or type(end) is not int:
            raise ValueError("Invalid relation or span")
        with self.db(True) as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (source,)).fetchone()
            if not row or not db.execute("SELECT id FROM claims WHERE id=?", (claim,)).fetchone():
                raise ValueError("Unknown claim or source")
            if sha(row["body"]) != row["sha256"] or not 0 <= start < end <= len(row["body"]):
                raise ValueError("Source integrity mismatch or span out of range")
            key = uuid.uuid4().hex
            db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?)", (key,claim,source,start,end,row["body"][start:end],relation,note))
            return key

    def conflict(self, a, b, note):
        text(note,1000)
        if a == b:
            raise ValueError("A claim cannot conflict with itself")
        a, b = sorted((a,b))
        with self.db(True) as db:
            if db.execute("SELECT COUNT(*) FROM claims WHERE id IN (?,?)", (a,b)).fetchone()[0] != 2:
                raise ValueError("Unknown conflict claim")
            db.execute("INSERT INTO conflicts VALUES(?,?,?)", (a,b,note))

    def export(self):
        with self.db() as db:
            packet = {"version":1}
            for table in ("sources", "claims", "evidence", "conflicts"):
                order = "a,b" if table == "conflicts" else "id"
                packet[table] = [dict(row) for row in db.execute("SELECT * FROM "+table+" ORDER BY "+order)]
        return validate(packet)

    def import_packet(self, packet):
        # Detached, validated data only; imports never overwrite an existing graph.
        packet = json.loads(json.dumps(packet, allow_nan=False))
        validate(packet)
        with self.db(True) as db:
            if any(db.execute("SELECT 1 FROM "+table+" LIMIT 1").fetchone() for table in ("sources", "claims", "evidence", "conflicts")):
                raise ValueError("Import requires an empty graph")
            for table, fields in (("sources",("id","title","url","body","sha256")), ("claims",("id","text")), ("evidence",("id","claim","source","start","end","quote","relation","note")), ("conflicts",("a","b","note"))):
                db.executemany("INSERT INTO "+table+" VALUES("+",".join("?" for _ in fields)+")", [tuple(row[field] for field in fields) for row in packet[table]])

    def inspect(self, claim):
        packet = self.export()
        row = next((c for c in packet["claims"] if c["id"] == claim), None)
        if row is None:
            raise KeyError(claim)
        sources = {s["id"]:s for s in packet["sources"]}
        claims = {c["id"]:c for c in packet["claims"]}
        evidence = [{**edge,"source_title":sources[edge["source"]]["title"], "source_url":sources[edge["source"]]["url"], "source_sha256":sources[edge["source"]]["sha256"]} for edge in packet["evidence"] if edge["claim"] == claim]
        conflicts = [{"claim":claims[pair["b"] if pair["a"] == claim else pair["a"]],"note":pair["note"]} for pair in packet["conflicts"] if claim in (pair["a"],pair["b"])]
        return {**row,"evidence":evidence,"conflicts":conflicts}

    def search(self, query, *, limit=50, offset=0):
        if not isinstance(query,str) or len(query)>200 or type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
            raise ValueError("Invalid search")
        packet = self.export()
        needle = query.casefold()
        sources = {s["id"]:s for s in packet["sources"]}
        related = {}
        for edge in packet["evidence"]:
            related.setdefault(edge["claim"],[]).extend([edge["quote"],sources[edge["source"]]["title"]])
        matches = [claim for claim in packet["claims"] if needle in (claim["text"]+" "+" ".join(related.get(claim["id"],[]))).casefold()]
        return matches[offset:offset+limit]

    def html_report(self):
        packet = self.export()
        esc = lambda value: html.escape(str(value),quote=True)
        sections = []
        for claim in packet["claims"]:
            detail = self.inspect(claim["id"])
            citations = "".join('<li><strong>'+esc(edge["relation"])+':</strong> <q>'+esc(edge["quote"])+'</q> — <a rel="noreferrer" href="'+esc(edge["source_url"])+'">'+esc(edge["source_title"])+'</a><p>'+esc(edge["note"])+'</p><small>Source '+esc(edge["source"])+', characters '+str(edge["start"])+':'+str(edge["end"])+', SHA-256 '+esc(edge["source_sha256"])+'</small></li>' for edge in detail["evidence"])
            conflicts = ''.join('<li>'+esc(pair["claim"]["text"])+' — '+esc(pair["note"])+'</li>' for pair in detail["conflicts"])
            sections.append('<article><h2>'+esc(claim["text"])+'</h2><h3>Evidence annotations</h3><ul>'+citations+'</ul><h3>Conflicting claims</h3><ul>'+conflicts+'</ul></article>')
        return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Research map</title><style>body{font:1rem system-ui;line-height:1.6;max-width:65rem;margin:2rem auto;padding:1rem;color:#20332e;background:#f6f5ed}article{background:white;border:1px solid #b0bdb6;border-radius:1rem;padding:1.5rem;margin:1rem 0}li{margin-bottom:1rem}small{overflow-wrap:anywhere}a{color:#12513d}</style><main><h1>Research map</h1><p>Human-entered claims and evidence annotations. A matching quote does not prove a claim true.</p>'+''.join(sections)+'</main></html>'

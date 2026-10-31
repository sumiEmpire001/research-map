# Research Map

Local source collection and claim-to-evidence graph with exact source spans, conflicting-claim annotations and provenance-preserving exports. Python 3.10+, SQLite and standard library only.

```sh
python -m unittest discover -s tests -v
python demo.py
python demo.py --html report.html
```

Open report.html for the self-contained synthetic research report. GitHub Actions uploads research-map-python-* artifacts on every successful run; download, extract and open report.html. The demo's trial data, sources and claims are fictional, and no source URL is fetched.

```python
from research import Graph
map = Graph('research.db')
body = 'Synthetic measurement: blue=12; red=8.'
source = map.source('Synthetic trial', 'https://example.invalid/trial', body)
claim = map.claim('Blue lasted longer in this sample')
map.link(claim, source, 0, len(body), relation='supports', note='Human interpretation of the supplied trial')
print(map.inspect(claim))
packet = map.export()
restored = Graph('empty-research.db')
restored.import_packet(packet)
```

Sources are immutable through this API. Each stores its title, reference URL, complete supplied text and SHA-256. Links select exact Python Unicode character offsets and capture the matching quote automatically. Relations are supports, refutes or context, with a required explanation. A quotation match verifies provenance only; it does not establish that the source is credible or that the annotation is logically correct.

Conflict annotations connect two distinct existing claims. They are stored in canonical order and shown from both claims. Evidence inspection includes source title, URL, checksum, offsets and quote. Search uses Unicode casefold and literal substring matching across claims, linked quotes and source titles; pagination uses stable ID order.

export() validates all hashes, spans, identities and references. import_packet() requires an empty target, validates the detached packet, and inserts all collections atomically. It preserves IDs and rejects duplicate evidence/conflicts, broken references, fabricated quotes, checksum mismatches and unsupported formats. Existing graphs are never overwritten. This graph models human research annotations, not a general RDF ontology, causal graph or automated fact checker.

12 local tests cover exact Unicode spans, broken links, relation constraints, duplicate evidence, symmetric conflicts, import/export round trips, tampering, transactional rejection, literal search/pagination, restart and HTML escaping. GitHub Actions runs tests and the synthetic report on Python 3.10/3.12/3.13. Actions → Tests and demo → Run workflow repeats them.

Limits: trusted local library without authentication, encryption, collaborative edits, automated scraping or an AI provider. Text and claims are stored in plaintext. URLs are validated HTTP(S) references without credentials and are never requested automatically; clicking exported links opens external sites. Source bodies up to1 million characters; claims up to2000, notes1000; export packets up to16MiB and10000 records per collection. Exports include full source text, so respect source licences and privacy before sharing. Hashes detect accidental changes rather than malicious rewriting of both content and hashes. Large reports validate the graph repeatedly and are intended for small local research collections.

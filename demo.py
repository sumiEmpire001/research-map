import argparse
import json
import tempfile
from pathlib import Path
from research import Graph

parser = argparse.ArgumentParser(description="Synthetic local research-map demonstration")
parser.add_argument("--html", type=Path)
args = parser.parse_args()
with tempfile.TemporaryDirectory() as folder:
    graph = Graph(Path(folder) / "graph.db")
    body = "Synthetic trial: the blue sample lasted 12 hours. The red sample lasted 8 hours."
    source = graph.source("Synthetic trial notes", "https://example.invalid/synthetic-trial", body)
    claim = graph.claim("In this synthetic trial, the blue sample lasted longer.")
    other = graph.claim("The red sample lasted longer in the same synthetic trial.")
    graph.link(claim, source, 0, len(body), relation="supports", note="Human-entered interpretation of the supplied synthetic measurements.")
    graph.link(other, source, 0, len(body), relation="refutes", note="The supplied trial values contradict this claim.")
    graph.conflict(claim, other, "Opposite interpretations of the same synthetic trial.")
    packet = graph.export()
    restored = Graph(Path(folder) / "restored.db")
    restored.import_packet(packet)
    assert restored.export() == packet
    print(json.dumps(graph.inspect(claim), indent=2))
    if args.html:
        args.html.write_text(graph.html_report(), encoding="utf-8")
        print("Offline HTML report:", args.html)

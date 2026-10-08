"""Refresh the local review UI while preserving frozen packets and saved labels."""
import argparse
import json
from pathlib import Path

from arbiter.eval.review_packets import render_review_html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packets", nargs="+", help="Paths to existing packet.json files")
    args = parser.parse_args()
    pages = []
    for name in args.packets:
        path = Path(name)
        packet = json.loads(path.read_text(encoding="utf-8"))
        draft = None
        if packet.get("provenance", {}).get("annotation_method") == "ai_assisted":
            draft = json.loads(path.with_name("ai-preannotations.json").read_text(encoding="utf-8"))
        pages.append((path.with_name("review.html"), render_review_html(packet, ai_draft=draft)))
    for path, rendered in pages:
        path.write_text(rendered, encoding="utf-8")
    print(f"Rendered {len(pages)} pages; frozen packets and labels unchanged.")


if __name__ == "__main__":
    main()

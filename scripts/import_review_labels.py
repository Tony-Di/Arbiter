"""Validate an attested human export without changing production data or old labels."""
import argparse
import json
from pathlib import Path

from arbiter.eval.review_packets import validate_review_export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    export = json.loads(Path(args.reviewed).read_text(encoding="utf-8-sig"))
    labels = validate_review_export(packet, export, require_complete=args.require_complete)
    with Path(args.output).open("x", encoding="utf-8") as handle:
        for row in labels:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"accepted": len(labels), "total": len(packet["cases"]), "policy_version": packet["policy_version"]}))


if __name__ == "__main__":
    main()

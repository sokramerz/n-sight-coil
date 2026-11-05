import argparse
import html
import json
import os
import re
import sys
from collections import defaultdict

from neo4j import GraphDatabase

from dotenv import load_dotenv


MIN_LEN = 4


def norm(s):
    return " ".join(s.lower().split())


def clean(text):
    """Only transformation applied to graph text: strip HTML tags/entities."""
    text = re.sub(r"</p>|<br\s*/?>", "\n\n", text or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in text.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="faq_data/summaries.json")
    args = ap.parse_args()

    load_dotenv()
    PASSWORD = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        rows = s.run("MATCH (n:FilteredHealthTopic) RETURN n.id AS id, n.title AS title, "
                     "n.also_called AS aliases, n.summary AS summary").data()
    driver.close()

    topics, surfaces = {}, defaultdict(set)
    for r in rows:
        summary = clean(r["summary"])
        if not summary:
            continue
        topic_id = str(r["id"])
        topics[topic_id] = {"title": r["title"], "summary": summary}
        for name in {norm(n) for n in [r["title"], *(r["aliases"] or [])]
                     if n and len(n) >= MIN_LEN}:
            surfaces[name].add(topic_id)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            {"topics": topics},
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )

    size_mb = os.path.getsize(args.out) / 1e6
    print(
        f"Wrote {args.out}: {len(topics)} drugs ({size_mb:.1f} MB)",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()

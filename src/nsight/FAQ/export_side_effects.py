"""
Export every MedlinePlus topic from Neo4j into one static JSON file that a
web page can load. Run this on your own machine whenever the graph changes.

Output (site/summaries.json):
{
  "terms":  { "hypertension": "6171", "high blood pressure": "6171", ... },
  "topics": { "6171": { "title": "High Blood Pressure", "summary": "..." }, ... }
}

`terms` maps every title/alias (lowercase) to a topic id, and `topics` stores
each summary once. (A flat term -> summary map would repeat the same long
summary for every alias and make the file several times bigger.)

Rules, same as the earlier scripts:
  - titles/aliases shorter than MIN_LEN are skipped (false-match risk)
  - a name that belongs to more than one topic is skipped (ambiguous)
  - summaries are copied unchanged except that HTML tags are stripped

Setup:
  pip install neo4j
  export NEO4J_PASSWORD=...   (optional: NEO4J_URI, NEO4J_USER)

Run:
  python export_summaries.py            # writes site/summaries.json
"""
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


def clean(items):
    if not items:
        return ""
    return ", ".join(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="faq_data/side_effects.json")
    args = ap.parse_args()

    load_dotenv()
    PASSWORD = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        rows = s.run("MATCH (n:Drug) "
                        "WHERE n.id STARTS WITH 'D' "
                        "RETURN n.id AS id, n.name AS name, "
                        "n.side_effects AS side_effects").data()
    driver.close()

    drugs = []

    for r in rows:
        drugs.append({
            "id": str(r["id"]),
            "name": r["name"],
            "side_effects": r["side_effects"]
        })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(drugs, f, ensure_ascii=False, indent=2)

   

    size_mb = os.path.getsize(args.out) / 1e6
    print(
        f"Wrote {args.out}: {len(drugs)} drugs ({size_mb:.1f} MB)",
        file=sys.stderr
    )


if __name__ == "__main__":
    main()

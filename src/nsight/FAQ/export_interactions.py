import argparse
import json
import os
import sys

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
    ap.add_argument("-o", "--out", default="faq_data/interactions.json")
    args = ap.parse_args()

    load_dotenv()
    PASSWORD = os.environ["NEO4J_PASSWORD"]

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        rows = s.run("""
                        MATCH (d:Drug)
                        OPTIONAL MATCH (d)-[:INTERACTS_WITH]->(other:Drug)
                        RETURN
                            d.id AS id,
                            d.name AS name,
                            collect(other.name) AS interacting_drugs
                        """).data()
    driver.close()

    drugs = []

    for r in rows:
        drugs.append({
            "id": str(r["id"]),
            "name": r["name"],
            "interacting_drugs": r["interacting_drugs"]
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

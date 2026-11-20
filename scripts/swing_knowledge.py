"""Retrieve attributed research notes for a candlestick chart review."""
import argparse
import json
from pathlib import Path
import re
import sqlite3

LESSONS = Path(__file__).resolve().parents[1] / "knowledge" / "swing-lessons.json"
COMMON_WORDS = frozenset(
    "a an and are as at be by can did do does for from how i in is it me my of on or "
    "should that the this to use what when which with work works would you".split()
)


def attributed(row):
    url = f"https://www.youtube.com/watch?v={row['video']}"
    if row["start"] is not None:
        url += f"&t={row['start']}s"
    return {**row, "source_url": url}


def ranked(query, lessons):
    words = sorted(set(re.findall(r"\w+", query.casefold())) - COMMON_WORDS)
    if not words:
        return []
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE VIRTUAL TABLE notes USING fts5(topic, lesson, hypothesis, requires_data, tokenize='porter unicode61')")
        db.executemany(
            "INSERT INTO notes VALUES (?, ?, ?, ?)",
            [(row["topic"], row["lesson"], row["hypothesis"], row["requires"]) for row in lessons],
        )
        expression = " AND ".join(f'"{word}"' for word in words)
        matches = db.execute(
            "SELECT rowid FROM notes WHERE notes MATCH ? ORDER BY bm25(notes, 6, 3, 1, 1), rowid LIMIT 3",
            (expression,),
        )
        return [attributed(lessons[rowid - 1]) for (rowid,) in matches]
    finally:
        db.close()


def search(query):
    return ranked(query, json.loads(LESSONS.read_text()))


def review_packet(query):
    lessons = json.loads(LESSONS.read_text())
    by_id = {row["id"]: row for row in lessons}
    return {
        "status": "research_only",
        "query": query,
        "topic_matches": ranked(query, lessons),
        "always_review": [attributed(by_id[key]) for key in ("horizon", "range", "gap", "limit", "shortcost")],
        "review_instructions": [
            "Cite observed candle times, horizon, and chart region supporting or contradicting each candidate. Distinguish observations from overlay readings and hypotheses.",
            "Give both the continuation and reversal interpretation. State what would falsify each. If the horizon, scale, source time, bar completion or required evidence is unknown, mark the affected conclusion indeterminate.",
            "A closing-price rule needs a completed bar. Treat unreadable numbers, truncated history, missing volume, external events, tape and account data as unknown. Do not infer exact values from pixels.",
            "Record chart bias as long candidate, short candidate, or wait. If opposing theses both pass or neither has a confirmed trigger, use wait. An empty topic match means the corpus has no retrieved support for the query.",
            "Keep sizing and execution independent of chart bias. This packet cannot authorize a trade. Research thresholds, retrieved ranks and video outcomes have no calibrated probability attached.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Topic keywords, e.g. overnight gap")
    parser.add_argument("--review", action="store_true", help="Include the chart review instructions and risk lessons")
    args = parser.parse_args()
    result = review_packet(args.query) if args.review else search(args.query)
    print(json.dumps(result, indent=2))

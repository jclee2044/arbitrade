"""Offline regression tests for the chart-review research corpus."""
import json
import unittest

from scripts.swing_knowledge import LESSONS, attributed, review_packet, search


class KnowledgeTests(unittest.TestCase):
    def test_provenance_and_coverage(self):
        rows = json.loads(LESSONS.read_text())
        self.assertGreaterEqual(len({r["video"] for r in rows}), 20)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        for r in rows:
            with self.subTest(lesson=r["id"]):
                self.assertRegex(r["video"], r"^[A-Za-z0-9_-]{11}$")
                self.assertEqual(r["status"], "research_only")
                self.assertEqual(r["source"]["author"], "TheOneLanceB")
                self.assertTrue(r["source"]["evidence_url"].startswith("https://"))
                for field in ("topic", "lesson", "hypothesis", "requires", "evidence"):
                    self.assertTrue(r[field].strip())
                if r["start"] is None:
                    self.assertIsNone(r["end"])
                    self.assertEqual(r["locator"], "video-level")
                    self.assertNotIn("&t=", attributed(r)["source_url"])
                else:
                    self.assertGreaterEqual(r["start"], 0)
                    self.assertEqual(r["locator"], "chapter")
                    self.assertTrue(attributed(r)["source_url"].endswith(f"&t={r['start']}s"))
                    if r["end"] is not None:
                        self.assertGreater(r["end"], r["start"])

    def test_topic_ranking(self):
        for query, expected in {
            "overnight gap": "gap", "weekly regime": "alignment",
            "short breakdown": "continuation", "buying power": "capacity",
            "relative volume": "features", "anchored VWAP": "avwap",
            "chop": "range", "drawdown protocol": "drawdown",
            "squeeze": "shortcost", "order flow": "tape",
            "moving average crossover": "averages", "stop fill": "stopfill",
            "daily loss limit": "limit", "right side of the V": "turn",
            "exhaustion gap": "exhaustiongap", "adding position": "scaling",
        }.items():
            with self.subTest(query=query):
                self.assertEqual(search(query)[0]["id"], expected)
        self.assertIn("reversal", [row["id"] for row in search("capitulation")])

    def test_unsupported_queries(self):
        for query in ("?!", "", "does Ichimoku work?", "Ichimoku breakout", "how should I"):
            with self.subTest(query=query):
                self.assertEqual(search(query), [])

    def test_review_keeps_risk_separate_from_matches(self):
        for query in ("short breakdown", "unsupportedword"):
            packet = review_packet(query)
            self.assertEqual(packet["topic_matches"], search(query))
            self.assertEqual(packet["status"], "research_only")
            self.assertEqual({r["id"] for r in packet["always_review"]},
                             {"horizon", "range", "gap", "limit", "shortcost"})
            self.assertTrue(packet["review_instructions"])


if __name__ == "__main__":
    unittest.main()

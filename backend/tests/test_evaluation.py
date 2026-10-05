import csv
import tempfile
import unittest
from pathlib import Path

from app import evaluation as E
from tests.helpers import SYN, build_db


class MetricTests(unittest.TestCase):
    def test_classification_report_known_values(self):
        r = E.classification_report(["a", "a", "b", "b"], ["a", "b", "b", "b"], ["a", "b"])
        self.assertEqual(r["accuracy"], 0.75)
        self.assertEqual(r["per_class"]["a"], {"precision": 1.0, "recall": 0.5, "f1": 0.667, "support": 2})
        self.assertAlmostEqual(r["macro_f1"], 0.733, places=2)
        self.assertEqual(r["confusion"]["a"], {"a": 1, "b": 1})

    def test_perfect_and_empty(self):
        self.assertEqual(E.classification_report(["a", "b"], ["a", "b"], ["a", "b"])["macro_f1"], 1.0)
        self.assertEqual(E.classification_report([], [], ["a"])["accuracy"], 0.0)

    def test_spearman(self):
        self.assertEqual(E.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertEqual(E.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(E.spearman([1, 2], [1, 2]))

    def test_purity(self):
        self.assertEqual(E.purity([0, 0, 1, 1], ["x", "x", "y", "x"]), 0.75)

    def test_coherence_prefers_cooccurring_words(self):
        docs = ["fast pace lecture", "fast pace class", "boring slides notes", "boring slides deck"] * 5
        good = E.npmi_coherence([["fast", "pace"], ["boring", "slides"]], docs)
        bad = E.npmi_coherence([["fast", "slides"], ["boring", "pace"]], docs)
        self.assertGreater(good, bad)


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.conn = build_db()
        cls.gold = E.gold_from_synthetic(cls.conn, SYN / "ground_truth.csv")

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_alignment_covers_nearly_all_clauses(self):
        total = self.conn.execute("SELECT COUNT(*) c FROM clauses").fetchone()["c"]
        self.assertGreater(len(self.gold) / total, 0.95)

    def test_evaluate_all_and_markdown(self):
        ev = E.evaluate_all(self.conn, self.gold, "synthetic ground truth")
        self.assertGreater(ev["theme_runs"][0]["accuracy"], 0.9)
        self.assertGreater(ev["sentiment_runs"][0]["accuracy"], 0.9)
        self.assertGreater(ev["sentiment_runs"][0]["rating_spearman"], 0.1)
        md = E.render_markdown(ev)
        for part in ("# Evaluation report", "Read this first", "## 1. Theme classification",
                     "## 2. Sentiment analysis", "Confusion matrix", "## 3. Limitations"):
            self.assertIn(part, md)

    def test_annotation_sample_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sample.csv"
            n = E.export_annotation_sample(self.conn, path, n=40)
            self.assertEqual(n, 40)
            with open(path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertTrue(all(r["gold_theme"] == "" and r["gold_sentiment"] == "" for r in rows))
            self.assertEqual(len({r["text"].lower() for r in rows}), 40)       # no duplicate texts
            for r in rows:                                                     # "label" them as predicted
                r["gold_theme"], r["gold_sentiment"] = r["predicted_theme"], r["predicted_sentiment"]
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            gold = E.gold_from_labels(path)
            ev = E.evaluate_all(self.conn, gold, "hand labels")
            self.assertEqual(ev["theme_runs"][0]["accuracy"], 1.0)
            self.assertEqual(ev["sentiment_runs"][0]["accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()

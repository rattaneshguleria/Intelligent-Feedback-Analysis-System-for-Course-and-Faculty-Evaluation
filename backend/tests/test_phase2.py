import csv
import json
import tempfile
import unittest
from pathlib import Path

from app import db, ingest, topic_pipeline as tp
from app.segmenter import segment
from app.themes import lexicon_scores
from app.topic_models import keyword_model

SYN = Path(__file__).resolve().parents[2] / "data" / "synthetic"
SALT = b"test-salt"


class SegmenterTests(unittest.TestCase):
    def test_sentences(self):
        self.assertEqual(len(segment("The pace was good. Too many assignments.")), 2)

    def test_contrast_split(self):
        out = segment("The lectures were clear, but the pace was too fast.")
        self.assertEqual(out, ["The lectures were clear", "The pace was too fast."])

    def test_drops_tiny_fragments_and_tag_only(self):
        self.assertEqual(segment("ok. [FACULTY]"), [])


class KeywordTests(unittest.TestCase):
    CASES = {
        "The syllabus was covered way too fast.": "pace",
        "Explanations were confusing and hard to follow.": "clarity",
        "Doubts were often ignored or brushed aside.": "support",
        "Too many assignments with very tight deadlines.": "workload",
        "Grading felt unfair and marks were not explained.": "assessment",
        "Classes were boring and monotonous.": "engagement",
        "Study material was outdated.": "resources",
        "Overall a great course.": "overall",
        "Thanks to [FACULTY].": "other",
    }

    def test_known_sentences(self):
        res = keyword_model(list(self.CASES))
        got = {t: a[1] for t, a in zip(self.CASES, res.assignments)}
        self.assertEqual(got, self.CASES)

    def test_scores_nonnegative(self):
        self.assertTrue(all(v >= 0 for v in lexicon_scores("anything at all").values()))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SYN / "feedback_raw.csv").exists():
            raise unittest.SkipTest("run scripts/generate_synthetic.py first")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.conn = db.connect(Path(cls.tmp.name) / "t.db")
        db.init_db(cls.conn)
        ingest.load_reference_data(cls.conn, SYN)
        anon = ingest.build_anonymizer(cls.conn, use_ner=False)
        ingest.ingest_csv(cls.conn, SYN / "feedback_raw.csv", "raw.csv", anon, SALT)
        cls.seg = tp.segment_all(cls.conn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_segmentation_is_idempotent(self):
        again = tp.segment_all(self.conn)
        self.assertEqual(again["clauses_created"], 0)
        self.assertGreater(self.seg["clauses_created"], self.seg["comments_segmented"])

    def test_runs_store_one_theme_per_clause(self):
        run = tp.run_topic_model(self.conn, "keyword")
        n_clauses = self.conn.execute("SELECT COUNT(*) c FROM clauses").fetchone()["c"]
        n_rows = self.conn.execute("SELECT COUNT(*) c FROM clause_themes WHERE run_id=?", (run,)).fetchone()["c"]
        self.assertEqual(n_clauses, n_rows)
        dist = {d["theme"]: d["share"] for d in tp.theme_distribution(self.conn, run)}
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=2)

    def test_keyword_agrees_with_ground_truth(self):
        """Sanity check only. The generator and lexicon share vocabulary, so this is
        optimistic; the real evaluation is Phase 6."""
        run = tp.run_topic_model(self.conn, "keyword")
        pred = {}
        for r in self.conn.execute(
                "SELECT f.response_ref ref, ct.theme FROM clause_themes ct "
                "JOIN clauses c ON c.id=ct.clause_id JOIN feedback f ON f.id=c.feedback_id "
                "WHERE ct.run_id=? ORDER BY f.id, c.position", (run,)):
            pred.setdefault(r["ref"], []).append(r["theme"])
        right = total = 0
        with open(SYN / "ground_truth.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gold = [p["theme"] if p["theme"] != "none" else "other" for p in json.loads(row["clauses_json"])]
                got = pred.get(row["response_ref"], [])
                if len(got) == len(gold):          # skip rows whose clause counts differ
                    right += sum(g == p for g, p in zip(gold, got))
                    total += len(gold)
        self.assertGreater(total, 1500)
        acc = right / total
        print(f"\n    keyword theme accuracy vs ground truth: {acc:.3f} on {total} clauses")
        self.assertGreater(acc, 0.85)

    def test_lda_runs_and_labels_topics(self):
        run = tp.run_topic_model(self.conn, "lda", n_topics=10)
        topics = tp.topic_summary(self.conn, run)
        self.assertEqual(len(topics), 10)
        self.assertTrue(any(t["theme"] != "other" for t in topics))


if __name__ == "__main__":
    unittest.main()

import unittest

from app import sentiment_pipeline as sp
from app.sentiment_models import lexicon_score, run_sentiment
from tests.helpers import build_db

CASES = {
    "Concepts were explained very clearly.": "positive",
    "Explanations were confusing and hard to follow.": "negative",
    "The syllabus was covered way too fast.": "negative",
    "Lectures moved at a comfortable speed and we never felt rushed.": "positive",
    "Emails were never answered.": "negative",
    "Doubts were often ignored or brushed aside.": "negative",
    "Very supportive and encouraging towards students.": "positive",
    "There was no support for students who were struggling.": "negative",
    "Would not recommend it.": "negative",
    "Overall a great course.": "positive",
    "Speed of teaching was average.": "neutral",
    "The pace was okay, neither fast nor slow.": "neutral",
}


class LexiconTests(unittest.TestCase):
    def test_known_clauses(self):
        for text, expected in CASES.items():
            self.assertEqual(lexicon_score(text)[0], expected, text)

    def test_negation_flips_polarity(self):
        self.assertEqual(lexicon_score("The course was good")[0], "positive")
        self.assertEqual(lexicon_score("The course was not good")[0], "negative")
        self.assertEqual(lexicon_score("The course was not bad")[0], "positive")

    def test_scores_are_bounded(self):
        for text in list(CASES) + ["", "excellent excellent excellent excellent"]:
            self.assertTrue(-1 <= lexicon_score(text)[1] <= 1)

    def test_unknown_method(self):
        with self.assertRaises(ValueError):
            run_sentiment("magic", ["x"])


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.conn = build_db()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_one_label_per_clause(self):
        run = self.conn.execute("SELECT MAX(id) i FROM sentiment_runs").fetchone()["i"]
        n = self.conn.execute("SELECT COUNT(*) c FROM clauses").fetchone()["c"]
        m = self.conn.execute("SELECT COUNT(*) c FROM clause_sentiment WHERE run_id=?", (run,)).fetchone()["c"]
        self.assertEqual(n, m)
        self.assertAlmostEqual(sum(sp.sentiment_distribution(self.conn, run).values()), 1.0, places=2)

    def test_second_run_is_stored_separately(self):
        a = sp.run_sentiment_model(self.conn, "lexicon")
        b = sp.run_sentiment_model(self.conn, "lexicon")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()

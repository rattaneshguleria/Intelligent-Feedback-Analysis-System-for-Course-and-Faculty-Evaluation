import unittest

from app import config, reports as R, report_render, topic_pipeline as tp
from tests.helpers import build_db


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.conn = build_db()
        cls.ctx = R.Context(cls.conn)
        cls.small = next(o for o in cls.ctx.offerings if not o["reportable"])

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    # --- privacy -----------------------------------------------------------
    def test_small_offering_returns_no_data(self):
        r = R.build_report(self.conn, "offering", self.small["offering_id"], ctx=self.ctx)
        self.assertTrue(r["suppressed"])
        for leaked in ("themes", "overall", "strengths", "quotes", "summary", "avg_rating"):
            self.assertNotIn(leaked, r)

    def test_aggregates_exclude_small_offering(self):
        r = R.build_report(self.conn, "faculty", self.small["faculty_id"], ctx=self.ctx)
        expected = sum(o["responses"] for o in self.ctx.offerings
                       if o["faculty_id"] == self.small["faculty_id"] and o["reportable"])
        self.assertEqual(r["responses"], expected)
        self.assertEqual(r["offerings_suppressed"], 1)
        self.assertNotIn(self.small["offering_id"], [x["offering_id"] for x in r["offerings"]])

    def test_course_scope_excludes_small_semester(self):
        r = R.build_report(self.conn, "course", self.small["course_code"], ctx=self.ctx)
        self.assertNotIn(self.small["semester"], [x["semester"] for x in r["offerings"]])

    def test_every_reported_theme_meets_minimum(self):
        for o in self.ctx.offerings:
            if not o["reportable"]:
                continue
            r = R.build_report(self.conn, "offering", o["offering_id"], ctx=self.ctx)
            self.assertTrue(all(t["comments"] >= self.ctx.k for t in r["themes"]), o)

    def test_scope_with_only_small_data_is_suppressed(self):
        r = R.build_report(self.conn, "offering", self.small["offering_id"], k=1000)
        self.assertTrue(r["suppressed"])

    # --- content -----------------------------------------------------------
    def test_strengths_and_concerns_are_consistent(self):
        for o in self.ctx.offerings:
            if not o["reportable"]:
                continue
            r = R.build_report(self.conn, "offering", o["offering_id"], ctx=self.ctx)
            self.assertFalse(set(r["strengths"]) & set(r["improvement_areas"]))
            self.assertFalse({"other", "overall"} & set(r["strengths"] + r["improvement_areas"]))
            by = {t["theme"]: t for t in r["themes"]}
            self.assertTrue(all(by[t]["net"] >= config.STRENGTH_THRESHOLD for t in r["strengths"]))
            self.assertTrue(all(by[t]["net"] <= config.CONCERN_THRESHOLD for t in r["improvement_areas"]))

    def test_quotes_are_clean_and_unique(self):
        r = R.build_report(self.conn, "faculty", "F01", ctx=self.ctx)
        quotes = [q for v in r["quotes"].values() for qs in v.values() for q in qs]
        self.assertTrue(quotes)
        self.assertEqual(len(quotes), len(set(q.lower() for q in quotes)))
        for q in quotes:
            self.assertNotIn("[", q)
        for name in ("Sharma", "Kulkarni", "Iyer", "Sandhu", "Malhotra", "Bedi"):
            self.assertFalse(any(name in q for q in quotes))

    def test_flagged_comments_never_quoted(self):
        oid = next(o["offering_id"] for o in self.ctx.offerings if o["reportable"])
        self.conn.execute("UPDATE feedback SET needs_review=1 WHERE offering_id=?", (oid,))
        self.conn.commit()
        try:
            r = R.build_report(self.conn, "offering", oid)
            for v in r["quotes"].values():
                for qs in v.values():
                    self.assertEqual(qs, [])
        finally:
            self.conn.execute("UPDATE feedback SET needs_review=0")
            self.conn.commit()

    def test_markdown_render(self):
        md = report_render.render_report(R.build_report(self.conn, "faculty", "F02", ctx=self.ctx))
        for heading in ("## At a glance", "## Themes", "## Strengths", "## Improvement areas"):
            self.assertIn(heading, md)

    def test_unknown_key_raises(self):
        with self.assertRaises(R.ReportError):
            R.build_report(self.conn, "faculty", "F99", ctx=self.ctx)
        with self.assertRaises(R.ReportError):
            R.build_report(self.conn, "galaxy", "x", ctx=self.ctx)

    # --- trends ------------------------------------------------------------
    def test_trends_are_chronological(self):
        t = R.build_trends(self.conn, "all", ctx=self.ctx)
        self.assertEqual(t["semesters"], ["2024-Autumn", "2025-Spring", "2025-Autumn", "2026-Spring"])

    def test_planted_improvement_is_detected(self):
        t = R.build_trends(self.conn, "faculty", "F02", ctx=self.ctx)
        ch = next(c for c in t["changes"] if c["series"] == "pace" and c["kind"] == "first_to_last")
        self.assertEqual(ch["direction"], "improved")
        self.assertGreater(ch["delta"], 0.5)

    def test_planted_decline_is_detected(self):
        t = R.build_trends(self.conn, "faculty", "F03", ctx=self.ctx)
        ch = next(c for c in t["changes"] if c["series"] == "workload" and c["kind"] == "first_to_last")
        self.assertEqual(ch["direction"], "declined")
        self.assertLess(ch["delta"], -0.5)

    def test_suppressed_semester_shows_as_unavailable(self):
        t = R.build_trends(self.conn, "course", self.small["course_code"], ctx=self.ctx)
        last = t["series"]["overall_tone"][-1]
        self.assertEqual((last["semester"], last["available"]), (self.small["semester"], False))
        self.assertEqual(last["reason"], "no_reportable_offerings")

    def test_compare_means(self):
        self.assertEqual(R.compare_means([0, 1, 0, 1, 0, 1], [0, 1, 0, 1, 0, 1])["direction"], "stable")
        self.assertEqual(R.compare_means([-1] * 8 + [0], [1] * 8 + [0])["direction"], "improved")
        self.assertEqual(R.compare_means([1] * 8 + [0], [-1] * 8 + [0])["direction"], "declined")

    # --- comparison --------------------------------------------------------
    def test_comparison(self):
        c = R.build_comparison(self.conn, "faculty", ctx=self.ctx)
        self.assertEqual(len(c["groups"]), 6)
        nets = [g["overall_net"] for g in c["groups"] if not g["suppressed"]]
        self.assertEqual(nets, sorted(nets, reverse=True))
        self.assertIsNotNone(c["baseline"])
        d = R.build_comparison(self.conn, "course", semester="2026-Spring", department="MATH", ctx=self.ctx)
        sup = {g["key"]: g["suppressed"] for g in d["groups"]}
        self.assertTrue(sup[self.small["course_code"]])

    # --- run selection -----------------------------------------------------
    def test_prefers_keyword_over_lda_and_allows_override(self):
        lda = tp.run_topic_model(self.conn, "lda", n_topics=10)
        self.assertEqual(R.resolve_runs(self.conn)["theme_run"]["method"], "keyword")
        self.assertEqual(R.resolve_runs(self.conn, theme_run=lda)["theme_run"]["method"], "lda")

    def test_no_runs_gives_clear_error(self):
        from app import db
        conn = db.connect(":memory:")
        db.init_db(conn)
        with self.assertRaises(R.ReportError):
            R.resolve_runs(conn)


if __name__ == "__main__":
    unittest.main()

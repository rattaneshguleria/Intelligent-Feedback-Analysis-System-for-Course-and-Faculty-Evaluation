"""One call that runs segmentation, a topic model and a sentiment model."""
from . import sentiment_pipeline as sp
from . import topic_pipeline as tp


def analyze(conn, topic_method: str = "keyword", sentiment_method: str = "lexicon",
            topic_params: dict | None = None) -> dict:
    seg = tp.segment_all(conn)
    topic_run = tp.run_topic_model(conn, topic_method, **(topic_params or {}))
    sent_run = sp.run_sentiment_model(conn, sentiment_method)
    return {"segmentation": seg,
            "topic_run": {"id": topic_run, "method": topic_method,
                          "themes": tp.theme_distribution(conn, topic_run)},
            "sentiment_run": {"id": sent_run, "method": sentiment_method,
                              "distribution": sp.sentiment_distribution(conn, sent_run)}}

"""Three ways to group clauses into themes. All return the same TopicResult.

  keyword  - transparent lexicon baseline, no ML libraries needed
  lda      - classic probabilistic topic model (scikit-learn); the comparison baseline
  bertopic - sentence embeddings + UMAP + HDBSCAN + c-TF-IDF; the main method

Topic models find clusters; `themes.py` names them. Several discovered topics can map
to the same theme (e.g. "too fast" and "too slow" are separate clusters, both "pace"),
and a topic that matches no theme is labelled "other" instead of being forced.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .themes import OTHER, THEME_NAMES, THEMES, lexicon_scores, tokenize

MIN_LEXICON_SCORE = 0.5


@dataclass
class TopicResult:
    method: str
    assignments: list[tuple[int, str, float]]   # per input text: (topic_idx, theme, score)
    topics: list[dict] = field(default_factory=list)  # topic_idx, theme, theme_score, keywords, size
    params: dict = field(default_factory=dict)


def _best_theme(scores: dict[str, float], minimum: float = MIN_LEXICON_SCORE):
    best = max(THEME_NAMES, key=lambda t: scores[t])   # ties -> earlier theme in THEME_NAMES
    return (best, scores[best]) if scores[best] >= minimum else (OTHER, scores[best])


# --------------------------------------------------------------------------- keyword
def keyword_model(texts: list[str]) -> TopicResult:
    """Each theme is one 'topic' (idx = position in THEME_NAMES, -1 = other)."""
    assignments, sizes = [], {}
    for text in texts:
        theme, score = _best_theme(lexicon_scores(text))
        idx = THEME_NAMES.index(theme) if theme != OTHER else -1
        assignments.append((idx, theme, round(score, 3)))
        sizes[idx] = sizes.get(idx, 0) + 1
    topics = [{"topic_idx": i, "theme": (THEME_NAMES[i] if i >= 0 else OTHER),
               "theme_score": 1.0, "size": n,
               "keywords": (list(THEMES[THEME_NAMES[i]]["lexicon"])[:8] if i >= 0 else [])}
              for i, n in sorted(sizes.items())]
    return TopicResult("keyword", assignments, topics)


# --------------------------------------------------------------------------- LDA
def lda_model(texts: list[str], n_topics: int = 10, seed: int = 42) -> TopicResult:
    import numpy as np
    from sklearn.decomposition import LatentDirichletAllocation
    from sklearn.feature_extraction.text import CountVectorizer

    vec = CountVectorizer(stop_words="english", min_df=3, token_pattern=r"[A-Za-z]{3,}")
    X = vec.fit_transform(texts)
    lda = LatentDirichletAllocation(n_components=n_topics, learning_method="batch",
                                    max_iter=40, random_state=seed)
    doc_topic = lda.fit_transform(X)
    vocab = np.array(vec.get_feature_names_out())

    topic_info = {}
    for k, comp in enumerate(lda.components_):
        top = vocab[comp.argsort()[::-1][:10]]
        theme, score = _best_theme(lexicon_scores(" ".join(top)), minimum=1.0)
        topic_info[k] = {"theme": theme, "theme_score": round(float(score), 3),
                         "keywords": [str(w) for w in top]}

    assignments, sizes = [], {}
    for row in doc_topic:
        k = int(row.argmax())
        assignments.append((k, topic_info[k]["theme"], round(float(row[k]), 3)))
        sizes[k] = sizes.get(k, 0) + 1
    topics = [{"topic_idx": k, "size": sizes.get(k, 0), **info} for k, info in topic_info.items()]
    return TopicResult("lda", assignments, topics, {"n_topics": n_topics, "seed": seed})


# --------------------------------------------------------------------------- BERTopic
def bertopic_model(texts: list[str], min_cluster_size: int | None = None,
                   nr_topics: int | None = None, min_similarity: float = 0.30,
                   embedding_model: str = "all-MiniLM-L6-v2", seed: int = 42) -> TopicResult:
    import numpy as np
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sentence_transformers import SentenceTransformer
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    embedder = SentenceTransformer(embedding_model)
    emb = embedder.encode(texts, normalize_embeddings=True, show_progress_bar=True)

    min_cluster_size = min_cluster_size or max(10, len(texts) // 150)
    model = BERTopic(
        embedding_model=embedder,
        umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine",
                        random_state=seed),
        hdbscan_model=HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean",
                              cluster_selection_method="eom", prediction_data=True),
        vectorizer_model=CountVectorizer(stop_words="english", ngram_range=(1, 2)),
        nr_topics=nr_topics, calculate_probabilities=False, verbose=False,
    )
    topics, _ = model.fit_transform(texts, emb)
    if any(t == -1 for t in topics) and len(set(topics)) > 1:
        topics = model.reduce_outliers(texts, topics, strategy="embeddings", embeddings=emb)
        model.update_topics(texts, topics=topics)

    # name each topic: cosine(topic centroid, theme anchor sentences)
    anchors = {}
    for name, spec in THEMES.items():
        v = embedder.encode(spec["anchors"], normalize_embeddings=True).mean(axis=0)
        anchors[name] = v / np.linalg.norm(v)
    topics_arr = np.array(topics)

    topic_info = {}
    for t in sorted(set(topics)):
        centroid = emb[topics_arr == t].mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        sims = {name: float(centroid @ v) for name, v in anchors.items()}
        best = max(sims, key=sims.get)
        theme, score = (best, sims[best]) if sims[best] >= min_similarity else (OTHER, sims[best])
        words = [w for w, _ in (model.get_topic(t) or [])][:8]
        topic_info[t] = {"theme": theme, "theme_score": round(score, 3), "keywords": words}

    assignments, sizes = [], {}
    for t in topics:
        assignments.append((int(t), topic_info[t]["theme"], topic_info[t]["theme_score"]))
        sizes[t] = sizes.get(t, 0) + 1
    out = [{"topic_idx": int(t), "size": sizes[t], **info} for t, info in topic_info.items()]
    return TopicResult("bertopic", assignments, out,
                       {"min_cluster_size": min_cluster_size, "nr_topics": nr_topics,
                        "min_similarity": min_similarity, "embedding_model": embedding_model,
                        "seed": seed})


def run_method(method: str, texts: list[str], **kw) -> TopicResult:
    if method == "keyword":
        return keyword_model(texts)
    if method == "lda":
        return lda_model(texts, **kw)
    if method == "bertopic":
        return bertopic_model(texts, **kw)
    raise ValueError(f"Unknown method '{method}' (use keyword, lda or bertopic)")

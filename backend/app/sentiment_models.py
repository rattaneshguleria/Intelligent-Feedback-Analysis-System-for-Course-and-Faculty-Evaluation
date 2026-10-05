"""Clause-level sentiment. Every method returns a list of (label, score) pairs where
label is positive|neutral|negative and score is in [-1, 1].

  lexicon     - rule-based scorer written for course feedback (no dependencies, explainable)
  vader       - general-purpose VADER baseline (pip install vaderSentiment)
  transformer - RoBERTa sentiment model (pip install transformers torch); the main method

Scoring clauses rather than whole comments matters: "clear lectures but too fast" is
positive about clarity and negative about pace, and averaging the two would hide both.
"""
from __future__ import annotations

import math
import re

POS, NEU, NEG = "positive", "neutral", "negative"

LEXICON = {
    # positive
    "good": 2, "great": 3, "excellent": 3, "amazing": 3, "awesome": 3, "best": 3, "fantastic": 3,
    "wonderful": 3, "helpful": 2, "useful": 2, "clear": 2, "clearly": 2, "clarity": 2, "easy": 1.5,
    "simple": 1, "interesting": 2, "interested": 2, "interactive": 2, "engaging": 2.5, "lively": 2,
    "comfortable": 2, "fair": 2, "transparent": 2, "timely": 2, "supportive": 2.5, "support": 1.5,
    "approachable": 2.5, "encouraging": 2.5, "quick": 1.5, "enjoyed": 2.5, "enjoy": 2, "recommend": 2,
    "manageable": 2, "reasonable": 1.5, "balanced": 2, "balance": 1.5, "structured": 2, "well": 1,
    "satisfied": 2, "love": 3, "loved": 3, "appreciate": 2, "informative": 2, "practical": 1.5,
    "relevant": 1.5, "available": 1.5, "proper": 1, "properly": 1, "thorough": 2, "detailed": 1.5,
    "organized": 2, "patient": 2, "friendly": 2, "answered": 1.5, "cleared": 2, "helped": 2,
    "improved": 1.5, "shared": 1, "provided": 0.5, "understand": 1.5, "understanding": 1.5,
    "discussion": 1, "activity": 1, "interaction": 1.5, "feedback": 0.5, "adequate": 0.3,
    "guidance": 1.5, "important": 1, "useful.": 2, "follow": 0.5, "explained": 1, "explanation": 1,
    "explanations": 1, "examples": 1, "matched": 1, "progress": 1, "fun": 2, "motivating": 2.5,
    # negative
    "bad": -2, "poor": -2.5, "boring": -2.5, "monotonous": -2.5, "confusing": -2.5, "confused": -2,
    "unclear": -2.5, "hard": -1, "difficult": -1, "rushed": -2, "rushing": -2, "unfair": -2.5,
    "outdated": -2, "insufficient": -2, "lacking": -2, "lacked": -2, "lack": -2, "ignored": -2.5,
    "ignore": -2, "overwhelming": -2.5, "tight": -1.5, "delayed": -2, "delay": -1.5, "late": -1.5,
    "worst": -3, "terrible": -3, "horrible": -3, "useless": -3, "waste": -3, "disappointing": -2.5,
    "disappointed": -2, "dragged": -2, "drag": -1.5, "hurry": -1.5, "skipped": -1.5, "brushed": -1.5,
    "struggling": -1.5, "piled": -1.5, "improvement": -1.5, "unsatisfied": -2.5, "stressful": -2.5,
    "irrelevant": -2, "messy": -2, "unorganized": -2, "rude": -3, "never": 0,
}
NEGATORS = {"not", "no", "never", "without", "hardly", "barely", "nothing", "cannot",
            "lack", "lacked", "lacking", "lacks"}
HARD_TO = {"hard", "difficult", "unable"}
INTENSIFIERS = {"very": 1.3, "really": 1.3, "extremely": 1.5, "so": 1.2, "highly": 1.3,
               "quite": 1.1, "super": 1.4, "absolutely": 1.5, "always": 1.2, "way": 1.3}
DAMPENERS = {"sometimes": 0.2, "occasionally": 0.3, "rarely": 0.3}
NEUTRALIZERS = {"average", "okay", "ok", "moderate", "standard", "normal"}
PHRASES = {"out of syllabus": -2.0, "just right": 2.5, "out of date": -2.0}

NEGATION_FACTOR = -0.74
NEG_WINDOW = 3
LABEL_THRESHOLD = 0.1
_TOKEN = re.compile(r"[a-z']+")


def _is_negator(tok: str) -> bool:
    return tok in NEGATORS or tok.endswith("n't")


def lexicon_score(text: str) -> tuple[str, float]:
    low = text.lower()
    toks = _TOKEN.findall(low)
    pos_sum = neg_sum = 0.0
    neg_left = 0
    skip = False
    for i, tok in enumerate(toks):
        if skip:
            skip = False
            neg_left = max(0, neg_left - 1)
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        val = LEXICON.get(tok, 0.0)
        if tok == "too" and nxt:  # "too fast", "too many", "too tight"
            neg_sum += -2.0
            skip = True
            continue
        if i > 0 and toks[i - 1] in INTENSIFIERS:
            val *= INTENSIFIERS[toks[i - 1]]
        if neg_left > 0 and val != 0:
            val *= NEGATION_FACTOR
        if val > 0:
            pos_sum += val
        else:
            neg_sum += val
        if _is_negator(tok) or (tok in HARD_TO and nxt == "to"):
            neg_left = NEG_WINDOW + 1  # +1 because this token also decrements
        neg_left = max(0, neg_left - 1)

    for phrase, v in PHRASES.items():
        if phrase in low:
            if v > 0:
                pos_sum += v
            else:
                neg_sum += v

    if re.search(r"\bsome\b.*\bsome\b", low):  # "some were clear and some were not"
        return NEU, 0.0
    total = pos_sum + neg_sum
    if pos_sum > 0 and neg_sum < 0 and min(pos_sum, -neg_sum) / max(pos_sum, -neg_sum) >= 0.6:
        total *= 0.3  # genuinely mixed clause
    damp = [DAMPENERS[t] for t in toks if t in DAMPENERS]
    if damp:
        total *= min(damp)
    if any(t in NEUTRALIZERS for t in toks) and neg_sum > -3:
        total *= 0.15
    score = total / math.sqrt(total * total + 15)
    label = POS if score > LABEL_THRESHOLD else NEG if score < -LABEL_THRESHOLD else NEU
    return label, round(score, 4)


def lexicon_model(texts: list[str]) -> list[tuple[str, float]]:
    return [lexicon_score(t) for t in texts]


def vader_model(texts: list[str]) -> list[tuple[str, float]]:
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    except ImportError as e:
        raise RuntimeError("Install VADER first: pip install vaderSentiment") from e
    an = SentimentIntensityAnalyzer()
    out = []
    for t in texts:
        c = an.polarity_scores(t)["compound"]
        out.append((POS if c >= 0.05 else NEG if c <= -0.05 else NEU, round(c, 4)))
    return out


def transformer_model(texts: list[str],
                      model_name: str = "cardiffnlp/twitter-roberta-base-sentiment-latest",
                      batch_size: int = 32) -> list[tuple[str, float]]:
    try:
        from transformers import pipeline
    except ImportError as e:
        raise RuntimeError("Install transformers first: pip install transformers torch") from e
    clf = pipeline("sentiment-analysis", model=model_name, top_k=None, truncation=True)
    out = []
    for i in range(0, len(texts), batch_size):
        for probs in clf(texts[i:i + batch_size]):
            p = {d["label"].lower(): d["score"] for d in probs}
            label = max(p, key=p.get)
            label = {"positive": POS, "negative": NEG, "neutral": NEU}.get(label, NEU)
            out.append((label, round(p.get("positive", 0.0) - p.get("negative", 0.0), 4)))
    return out


def run_sentiment(method: str, texts: list[str], **kw) -> list[tuple[str, float]]:
    if method == "lexicon":
        return lexicon_model(texts)
    if method == "vader":
        return vader_model(texts)
    if method == "transformer":
        return transformer_model(texts, **kw)
    raise ValueError(f"Unknown sentiment method '{method}' (lexicon, vader or transformer)")

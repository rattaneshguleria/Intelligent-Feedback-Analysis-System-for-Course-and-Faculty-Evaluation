"""Theme definitions shared by every topic-modeling method.

Topic models discover groups of similar comments without knowing their meaning.
This file is what turns an anonymous "topic 7" into a named theme such as "pace":
  - `anchors` (example sentences) are embedded and compared to topic centroids (BERTopic)
  - `lexicon` (word -> weight) is matched against topic keywords (LDA) and is also the
    transparent keyword baseline.
"""
import re

OTHER = "other"

THEMES = {
    "pace": {
        "description": "speed of teaching and how fast the syllabus is covered",
        "anchors": ["The course moved too fast.", "The pace was too slow.",
                    "Lectures were rushed and hard to keep up with."],
        "lexicon": {"pace": 1, "speed": 1, "fast": 1, "slow": 1, "rushed": 1, "rush": 1,
                    "hurry": 1, "dragged": 1, "drag": 1, "keep up": 1, "skipped": 0.5},
    },
    "clarity": {
        "description": "how clearly concepts are explained",
        "anchors": ["The concepts were explained clearly.", "The explanations were confusing.",
                    "Examples helped me understand difficult topics."],
        "lexicon": {"clear": 1, "clarity": 1, "explain": 1, "explanation": 1, "understand": 1,
                    "confusing": 1, "confuse": 1, "derivation": 1, "simple": 1, "follow": 0.5,
                    "structured": 1, "examples": 0.5, "concepts": 0.5},
    },
    "support": {
        "description": "faculty availability and help with doubts",
        "anchors": ["The faculty was approachable and answered my doubts.",
                    "Doubts were ignored and there was no support.",
                    "Quick replies to queries and helpful guidance."],
        "lexicon": {"support": 1, "supportive": 1, "approachable": 1, "doubt": 1, "available": 1,
                    "query": 1, "reply": 1, "email": 1, "guidance": 1, "encouraging": 1,
                    "ignored": 1, "struggling": 1, "office": 0.5, "answered": 1},
    },
    "workload": {
        "description": "amount of assignments, projects and deadlines",
        "anchors": ["There were too many assignments and tight deadlines.",
                    "The workload was manageable.",
                    "Projects took too much time."],
        "lexicon": {"workload": 1, "assignment": 1, "deadline": 1, "project": 1,
                    "overwhelming": 1, "load": 1, "piled": 1},
    },
    "assessment": {
        "description": "exams, grading, quizzes and evaluation fairness",
        "anchors": ["The exam questions were unfair.", "Grading was transparent and timely.",
                    "Quizzes helped track progress."],
        "lexicon": {"exam": 1, "grading": 1, "grade": 1, "mark": 1, "quiz": 1, "evaluation": 1,
                    "result": 1, "criteria": 1, "unfair": 1, "fair": 1, "syllabus": 0.5,
                    "feedback": 0.5},
    },
    "engagement": {
        "description": "how interactive and interesting classes are",
        "anchors": ["The classes were interactive and interesting.",
                    "Lectures were boring and monotonous.",
                    "There was no discussion in class."],
        "lexicon": {"interactive": 1, "interesting": 1, "interest": 1, "engaging": 1,
                    "discussion": 1, "lively": 1, "boring": 1, "monotonous": 1,
                    "interaction": 1, "activity": 1, "session": 0.5},
    },
    "resources": {
        "description": "notes, slides, books, labs and study material",
        "anchors": ["The notes and slides were useful.", "The study material was outdated.",
                    "Lab resources were insufficient."],
        "lexicon": {"note": 1, "slide": 0.5, "material": 1, "reference": 1, "resource": 1,
                    "lab": 1, "recorded": 1, "book": 1, "study": 0.5, "outdated": 1, "system": 0.5},
    },
    "overall": {
        "description": "overall opinion of the course",
        "anchors": ["Overall a great course.", "I would recommend this course.",
                    "Overall I was not satisfied."],
        "lexicon": {"overall": 2, "recommend": 1.5, "enjoyed": 1, "satisfied": 1,
                    "improvement": 1, "average": 0.5},
    },
}

THEME_NAMES = list(THEMES)


def stem(word: str) -> str:
    """Very small suffix stripper, applied to both the lexicon and the text so they agree."""
    w = word.lower()
    for suf in ("ing", "ed", "es", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in re.findall(r"[a-z']+", text.lower())]


def _build_index():
    idx: dict[str, list[tuple[str, float]]] = {}
    phrases: list[tuple[str, str, float]] = []
    for theme, spec in THEMES.items():
        for word, weight in spec["lexicon"].items():
            if " " in word:
                phrases.append((theme, " ".join(stem(w) for w in word.split()), weight))
            else:
                idx.setdefault(stem(word), []).append((theme, weight))
    return idx, phrases


_INDEX, _PHRASES = _build_index()


def lexicon_scores(text: str) -> dict[str, float]:
    """Sum of lexicon weights per theme for a piece of text."""
    toks = tokenize(text)
    scores = {t: 0.0 for t in THEME_NAMES}
    for tok in toks:
        for theme, weight in _INDEX.get(tok, ()):
            scores[theme] += weight
    joined = " ".join(toks)
    for theme, phrase, weight in _PHRASES:
        if phrase in joined:
            scores[theme] += weight
    return scores

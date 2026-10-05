"""Split a comment into clauses so each clause carries one theme and one sentiment.

"Great lectures but way too fast." is positive about clarity and negative about pace.
Modeling the whole comment would blur that, so Phases 2 and 3 work on clauses.
"""
import re

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT = re.compile(r",?\s+(?:but|however|although|though|yet)\s+|;\s+", re.I)
_TAG_RE = re.compile(r"\[[A-Z]+\]")


def _word_count(s: str) -> int:
    return len(re.findall(r"[A-Za-z']+", _TAG_RE.sub(" ", s)))


def segment(comment: str, min_words: int = 3) -> list[str]:
    clauses: list[str] = []
    for sent in _SENT_SPLIT.split(comment.strip()):
        for part in _CLAUSE_SPLIT.split(sent):
            part = part.strip(" ,;-")
            if part and _word_count(part) >= min_words:
                clauses.append(part[0].upper() + part[1:])
    return clauses

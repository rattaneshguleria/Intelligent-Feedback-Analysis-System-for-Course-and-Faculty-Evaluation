"""Comment scrubbing: remove personal identifiers from free text.

Layers (applied in order):
  1. Faculty names from the reference data      -> [FACULTY]
  2. Emails, URLs, phone numbers, roll/reg ids   -> [EMAIL] [URL] [PHONE] [ID]
  3. Titled names and self-introductions/peers   -> [PERSON]
  4. Optional spaCy NER (PERSON entities)        -> [PERSON]
  5. Re-identification risk flags (not removed, only flagged for review)

Regex layers are recall-oriented: they may over-redact a little, which is the safe
direction for an anonymity requirement. Install spaCy + en_core_web_sm to add layer 4.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

TITLES = r"(?:Dr|Prof|Professor|Mr|Mrs|Ms|Er)"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
LONG_NUM_RE = re.compile(r"(?<![\w])\d{6,}(?![\w])")           # reg / roll numbers
ALNUM_ID_RE = re.compile(r"\b[A-Za-z]{1,4}\d{2,}[A-Za-z0-9]*\b")  # K22AB, 12A345
TITLED_NAME_RE = re.compile(rf"\b{TITLES}\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?")
INTRO_RE = re.compile(
    r"(?i:\b(?:my name is|i am|i'm|this is|myself|regards,?|thanks,?|thank you,?"
    r"|friend|classmate|roommate|batchmate|groupmate|teammate))\s+"
    r"([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+){0,2})"
)
# Words that look like names after "I am ..." but are not.
NOT_NAMES = {
    "very", "not", "the", "good", "bad", "great", "happy", "satisfied", "thankful",
    "grateful", "disappointed", "glad", "sorry", "really", "quite", "also", "sure",
    "totally", "extremely", "overall", "honestly", "so", "too", "just", "still",
}

RISK_PATTERNS = {
    "unique_attribute": re.compile(r"\bonly (?:one|girl|boy|female|male|student|person)\b", re.I),
    "seating": re.compile(r"\b(?:sit|sat|sitting|seated)\b.{0,25}\b(?:row|bench|corner|front|back|last)\b", re.I),
    "hostel_room": re.compile(r"\b(?:hostel|block|room)\s*(?:no\.?\s*)?[A-Za-z]?\d+\b", re.I),
    "self_status": re.compile(r"\bi (?:was|am|got) (?:absent|detained|debarred|failed|on backlog)\b", re.I),
}


@dataclass
class AnonResult:
    text: str
    redactions: Counter = field(default_factory=Counter)
    risk_flags: list[str] = field(default_factory=list)

    @property
    def redaction_count(self) -> int:
        return sum(self.redactions.values())

    @property
    def needs_review(self) -> bool:
        return bool(self.risk_flags)


def _faculty_regex(names: list[str]) -> re.Pattern | None:
    alts: set[str] = set()
    for n in names:
        clean = re.sub(rf"^{TITLES}\.?\s+", "", n.strip(), flags=re.I)
        if not clean:
            continue
        alts.add(re.escape(clean))
        alts.update(re.escape(p) for p in clean.split() if len(p) >= 3)
    if not alts:
        return None
    body = "|".join(sorted(alts, key=len, reverse=True))
    return re.compile(rf"(?:{TITLES}\.?\s+)?\b(?:{body})\b", re.I)


class Anonymizer:
    def __init__(self, faculty_names=(), keep_tokens=(), use_ner: bool = True):
        self._faculty_re = _faculty_regex(list(faculty_names))
        self._keep = {t.upper() for t in keep_tokens}   # e.g. course codes
        self._nlp = self._load_ner() if use_ner else None

    @property
    def ner_enabled(self) -> bool:
        return self._nlp is not None

    @staticmethod
    def _load_ner():
        try:
            import spacy
            return spacy.load("en_core_web_sm", disable=["lemmatizer"])
        except Exception:
            return None

    # -- helpers ---------------------------------------------------------
    def _sub(self, pattern, repl, text, res: Counter, key: str):
        def _r(m):
            res[key] += 1
            return repl
        return pattern.sub(_r, text)

    def _sub_alnum_ids(self, text, res):
        def _r(m):
            if m.group(0).upper() in self._keep:
                return m.group(0)
            res["ID"] += 1
            return "[ID]"
        return ALNUM_ID_RE.sub(_r, text)

    def _sub_intro(self, text, res):
        def _r(m):
            first = m.group(1).split()[0].lower()
            if first in NOT_NAMES:
                return m.group(0)
            res["PERSON"] += 1
            return m.group(0)[: m.start(1) - m.start(0)] + "[PERSON]"
        return INTRO_RE.sub(_r, text)

    def _ner(self, text, res):
        if not self._nlp:
            return text
        doc = self._nlp(text)
        for ent in reversed(doc.ents):
            if ent.label_ == "PERSON" and "[" not in ent.text:
                text = text[: ent.start_char] + "[PERSON]" + text[ent.end_char:]
                res["PERSON"] += 1
        return text

    # -- public ----------------------------------------------------------
    def clean(self, raw: str) -> AnonResult:
        res: Counter = Counter()
        text = unicodedata.normalize("NFKC", raw or "")
        text = re.sub(r"\s+", " ", text).strip()

        if self._faculty_re:
            text = self._sub(self._faculty_re, "[FACULTY]", text, res, "FACULTY")
        text = self._sub(EMAIL_RE, "[EMAIL]", text, res, "EMAIL")
        text = self._sub(URL_RE, "[URL]", text, res, "URL")
        text = self._sub(PHONE_RE, "[PHONE]", text, res, "PHONE")
        text = self._sub(LONG_NUM_RE, "[ID]", text, res, "ID")
        text = self._sub_alnum_ids(text, res)
        text = self._sub(TITLED_NAME_RE, "[PERSON]", text, res, "PERSON")
        text = self._sub_intro(text, res)
        text = self._ner(text, res)

        flags = [name for name, pat in RISK_PATTERNS.items() if pat.search(text)]
        return AnonResult(text=text, redactions=res, risk_flags=flags)

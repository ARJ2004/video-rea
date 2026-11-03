"""Prepare Hindi script text for a grapheme-input TTS (IndicF5, Indic Parler-TTS, Indic-Speak).

These models read Devanagari text directly, with no phoneme input, so pronunciation is
steered by changing what they read:
  1. normalize punctuation the models read badly (em dashes, quotes, ellipses)
  2. apply the pronunciation lexicon (respellings; see lexicon.tsv)
  3. flag remaining words that match known Hindi TTS risk patterns, so a human or qa.py checks them

Captions must use the ORIGINAL text; only the TTS sees the respelled text.

CLI:  python -m vrea.pronounce.normalize stories/srishti-ep1/storyboard.json
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

LEXICON_PATH = Path(__file__).with_name("lexicon.tsv")

# A "word" is a run of Devanagari letters/marks or Latin letters. Danda, digits and punctuation split words.
WORD_RE = re.compile(r"[ऀ-ॣॱ-ॿ‌‍A-Za-z]+")

HALANT = "्"
NUKTA = "़"
RISK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ri-vowel ऋ/ृ", re.compile("[ऋृ]")),
    ("retroflex ष", re.compile("ष")),
    ("ज्ञ cluster", re.compile("ज्ञ")),
    ("visarga ः", re.compile("ः")),
    ("nukta", re.compile(NUKTA)),
    ("3+ consonant cluster", re.compile(f"(?:[क-ह]{HALANT}){{2,}}[क-ह]")),
    ("ह-cluster", re.compile(f"ह{HALANT}[मनयवलर]")),
    ("Latin script", re.compile("[A-Za-z]")),
]


@dataclass
class LexEntry:
    word: str
    variants: list[str]
    rule: str
    status: str
    note: str = ""


@dataclass
class Result:
    original: str
    tts_text: str
    applied: list[tuple[str, str, str]] = field(default_factory=list)  # (word, respelling, rule)
    risks: list[tuple[str, str]] = field(default_factory=list)  # (word, reason)


def load_lexicon(path: Path = LEXICON_PATH) -> dict[str, LexEntry]:
    lex: dict[str, LexEntry] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 4:
            raise ValueError(f"bad lexicon line (need ≥4 tab-separated columns): {line!r}")
        word, spelling, rule, status = (c.strip() for c in cols[:4])
        note = cols[4].strip() if len(cols) > 4 else ""
        if status == "rejected":
            continue
        variants = [v.strip() for v in spelling.split("|") if v.strip()]
        lex[unicodedata.normalize("NFC", word)] = LexEntry(word, variants, rule, status, note)
    return lex


def normalize_punctuation(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s*[—–]\s*", ", ", text)           # dashes -> short pause
    text = re.sub(r"\.{3,}|…", "...", text)             # one ellipsis form
    text = re.sub(r"[\"'‘’“”]", "", text)               # quotes are read aloud or cause glitches
    text = re.sub(r"\s*:\s*", ", ", text)               # colon -> pause
    text = re.sub(r",\s*,", ",", text)
    return re.sub(r"\s+", " ", text).strip()


def _apply_phrases(text: str, lex: dict[str, LexEntry], variant: int, res: Result) -> str:
    """Multi-word and Latin entries (e.g. 'Big Bang') are replaced as phrases first."""
    for key, e in lex.items():
        if " " in key or re.search("[A-Za-z]", key):
            pat = re.compile(rf"(?<![\wऀ-ॿ]){re.escape(key)}(?![\wऀ-ॿ])", re.IGNORECASE)
            if pat.search(text):
                rep = e.variants[min(variant, len(e.variants) - 1)]
                text = pat.sub(rep, text)
                res.applied.append((key, rep, e.rule))
    return text


def prepare(text: str, lex: dict[str, LexEntry] | None = None, variant: int = 0) -> Result:
    """Return the TTS-ready text. variant=i picks the i-th alternative spelling where one exists."""
    lex = load_lexicon() if lex is None else lex
    res = Result(original=text, tts_text="")
    t = _apply_phrases(normalize_punctuation(text), lex, variant, res)

    # Single-letter A-U-M tokens: only when the letter stands alone ("अ, उ, और म").
    def word_sub(m: re.Match[str]) -> str:
        w = m.group(0)
        e = lex.get(w)
        if e is None:
            # punctuation-carrying keys such as "अ," are matched separately below
            for reason, pat in RISK_PATTERNS:
                if pat.search(w):
                    res.risks.append((w, reason))
                    break
            return w
        rep = e.variants[min(variant, len(e.variants) - 1)]
        if rep != w:
            res.applied.append((w, rep, e.rule))
        elif e.rule == "watch":
            res.risks.append((w, f"watch: {e.note}" if e.note else "watch"))
        return rep

    t = WORD_RE.sub(word_sub, t)
    for key, e in lex.items():  # keys that include punctuation, e.g. "अ,"
        if not WORD_RE.fullmatch(key) and " " not in key and not re.search("[A-Za-z]", key):
            pat = re.compile(rf"(?<![ऀ-ॿ]){re.escape(key)}")
            if pat.search(t):
                rep = e.variants[min(variant, len(e.variants) - 1)]
                t = pat.sub(rep, t)
                res.applied.append((key, rep, e.rule))
    res.tts_text = re.sub(r"\s+", " ", t).strip()
    return res


def variant_count(text: str, lex: dict[str, LexEntry] | None = None) -> int:
    """How many spelling variants are worth trying for this text (max alternatives of any word used)."""
    lex = load_lexicon() if lex is None else lex
    words = set(WORD_RE.findall(normalize_punctuation(text)))
    return max([len(lex[w].variants) for w in words if w in lex] + [1])


def _main(storyboard: str) -> None:
    lex = load_lexicon()
    sb = json.loads(Path(storyboard).read_text(encoding="utf-8"))
    for clip in sb["clips"]:
        for line in clip.get("lines", []):
            r = prepare(line["tts"], lex)
            print(f"\n[{line['id']}] {line['speaker']}")
            print(f"  script : {r.original}")
            print(f"  tts    : {r.tts_text}")
            for w, rep, rule in dict.fromkeys(r.applied):
                print(f"  fixed  : {w} -> {rep}  ({rule})")
            for w, why in r.risks:
                print(f"  CHECK  : {w}  ({why})")
            n = variant_count(line["tts"], lex)
            if n > 1:
                print(f"  variants to try: {n}")


if __name__ == "__main__":
    _main(sys.argv[1] if len(sys.argv) > 1 else "stories/srishti-ep1/storyboard.json")

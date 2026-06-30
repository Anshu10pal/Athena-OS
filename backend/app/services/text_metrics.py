"""Local, dependency-free text analysis for the Writing modality.

Everything here is *measured* deterministically on-device — no LLM, no network.
Grammar/structure/tone are judged by the LLM elsewhere; these are the objective signals.
"""
import re

HEDGES = {"maybe", "perhaps", "possibly", "sort", "kind", "somewhat", "probably", "i think", "i guess", "i feel", "just", "actually", "basically"}
WEAK_INTENSIFIERS = {"very", "really", "quite", "rather", "extremely", "totally", "literally", "definitely"}
FILLER = {"thing", "things", "stuff", "etc"}


def _syllables(word: str) -> int:
    word = word.lower().strip(".,;:!?'\"")
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def analyze(text: str) -> dict:
    text = (text or "").strip()
    words = re.findall(r"[A-Za-z']+", text)
    wc = len(words)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    sc = max(1, len(sentences))

    if wc == 0:
        return {"word_count": 0, "empty": True}

    lower = [w.lower() for w in words]
    unique = len(set(lower))
    # length-adjusted lexical diversity (root TTR keeps it fair across lengths)
    root_ttr = unique / (wc ** 0.5)
    avg_word_len = sum(len(w) for w in words) / wc
    avg_sentence_len = wc / sc

    syl = sum(_syllables(w) for w in words)
    # Flesch Reading Ease
    flesch = 206.835 - 1.015 * (wc / sc) - 84.6 * (syl / wc)

    text_l = " " + text.lower() + " "
    hedge_hits = sum(text_l.count(" " + h + " ") for h in HEDGES)
    weak_hits = sum(1 for w in lower if w in WEAK_INTENSIFIERS)
    filler_hits = sum(1 for w in lower if w in FILLER)
    # crude passive-voice detector: be-verb + past participle (word ending -ed/-en)
    passive = len(re.findall(r"\b(?:is|are|was|were|be|been|being)\b\s+\w+(?:ed|en)\b", text.lower()))

    # ---- derive 0..100 sub-scores for the locally-measured dimensions ----
    # Vocabulary range: reward diversity + word length
    vocab = max(0, min(100, 45 + (root_ttr - 4.5) * 16 + (avg_word_len - 4.2) * 9))

    # Clarity from readability, ideal band 50-75 (clear but not childish)
    if flesch >= 75:
        clarity = 100 - (flesch - 75) * 0.8
    elif flesch >= 50:
        clarity = 100
    else:
        clarity = max(0, 100 - (50 - flesch) * 1.3)
    clarity = max(0, min(100, clarity))

    # Precision: penalize hedges, weak intensifiers, filler, passive, very long sentences
    density = (hedge_hits + weak_hits + filler_hits + passive) / wc * 100
    precision = max(0, min(100, 100 - density * 6 - max(0, avg_sentence_len - 24) * 2))

    return {
        "word_count": wc,
        "sentence_count": sc,
        "unique_words": unique,
        "avg_word_length": round(avg_word_len, 2),
        "avg_sentence_length": round(avg_sentence_len, 1),
        "flesch_reading_ease": round(flesch, 1),
        "hedges": hedge_hits,
        "weak_intensifiers": weak_hits,
        "filler": filler_hits,
        "passive_constructions": passive,
        "scores": {
            "vocabulary": round(vocab),
            "clarity": round(clarity),
            "precision": round(precision),
        },
    }

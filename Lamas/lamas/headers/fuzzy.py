import re

from thefuzz import fuzz

DIGITS = re.compile(r'([0-9-]{2,})')
AUTO_MERGE_THRESHOLD = 95
SUGGESTION_THRESHOLD = 80


def normalize_for_fuzzy(header: str) -> str:
    """Collapse runs of digits so headers differing only in an embedded number still compare as similar."""
    return DIGITS.sub(r'\1\1\1\1\1', header)


def best_match(header, candidates):
    """Return (best_candidate, score) among `candidates`, or (None, None) if there are none."""
    norm_header = normalize_for_fuzzy(header)
    best = None
    best_score = -1
    for cand in candidates:
        score = fuzz.ratio(norm_header, normalize_for_fuzzy(cand))
        if score > best_score:
            best = cand
            best_score = score
    if best is None:
        return None, None
    return best, best_score


def pairwise_near_duplicates(headers, threshold=AUTO_MERGE_THRESHOLD):
    """Yield (a, b, score) for every pair of headers scoring above `threshold`."""
    headers = list(headers)
    for i in range(len(headers)):
        for j in range(i + 1, len(headers)):
            score = fuzz.ratio(normalize_for_fuzzy(headers[i]), normalize_for_fuzzy(headers[j]))
            if score > threshold:
                yield headers[i], headers[j], score

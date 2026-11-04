"""Topic-name tokenizing and similarity."""

import collections
import re

STOPWORDS = frozenset(
    "a an and are as at be by can do for from how i in is it me my of on or our so the this to up we what "
    "when where which why with you your please help make new add fix get use using need want into about "
    "session conversation codex".split()
)


def tokens(title: str) -> set[str]:
    """Meaningful lowercase words of a topic name."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", title)
    words = re.split(r"[^A-Za-z0-9]+", spaced.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS and not w.isdigit()}


def similarity(a: set[str], b: set[str]) -> float:
    """Overlap coefficient of two token sets; suits short topic names."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def common_words(titles: list[str], limit: int) -> list[str]:
    """Most frequent topic words across titles, in frequency order."""
    counts = collections.Counter(word for title in titles for word in tokens(title))
    return [word for word, _ in counts.most_common(limit)]

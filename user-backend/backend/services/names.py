"""Rarity-weighted name matching over a match's (or several matches') entities: teams, players, storylines."""
import math
import re
import unicodedata
from collections import Counter


def words(text):
    plain = unicodedata.normalize('NFKD', text or '').encode('ascii', 'ignore').decode().casefold()
    return set(re.findall(r'[a-z0-9]+', plain))


def rarity(entities):
    """Word weights over the match's entities (each a list of names): log((N + 1) / entities using the word), so a
    word every name shares ("the") counts for little and a word one entity owns counts most."""
    used = Counter(w for names in entities for w in set().union(*map(words, filter(None, names))))
    return {w: math.log((len(entities) + 1) / n) for w, n in used.items()}


def match_score(subject, names, weight):
    """The best weighted word overlap between the subject and any of the names, as a share of the heavier of the
    two (words no entity uses do not count)."""
    asked = words(subject) & weight.keys()
    total = lambda ws: sum(weight[w] for w in ws)
    return max((total(asked & have) / max(total(asked), total(have))
                for have in map(words, filter(None, names)) if asked and have and total(have)), default=0.0)


def coverage(text, names, weight):
    """The best weighted share of any one name's words that `text` contains: 1.0 when a whole name appears, more
    when the words it shares with `text` are rare. Words no entity uses do not count."""
    said = words(text) & weight.keys()
    total = lambda ws: sum(weight[w] for w in ws)
    return max((total(said & have) / total(have) for have in map(words, filter(None, names))
                if have and total(have)), default=0.0)

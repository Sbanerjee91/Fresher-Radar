"""Duplicate detection: same company + same role + same city = one job.

Two layers: (1) an exact hash of the *normalised* fields, which also catches the same job
on two job boards, and (2) a fuzzy title match inside the same company and city, which
catches "Software Intern" vs "Software Engineering Intern (m/f/d)".
"""
import hashlib
import re
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.88

_LEGAL = re.compile(r"\b(?:pvt|private|ltd|limited|llp|inc|llc|corp|corporation|technologies|technology|india)\b")
_BRACKETS = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_GENDER = re.compile(r"\b(?:m/?f/?d|w/?m/?d|f/?m/?d|all genders)\b")
_WORDS = {"internship": "intern", "interns": "intern", "engineering": "engineer", "developers": "developer"}


def _clean(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower().replace("&", " and ")).strip()


def norm_company(name):
    return re.sub(r"\s+", " ", _LEGAL.sub(" ", _clean(name or ""))).strip()


def norm_title(title):
    text = _GENDER.sub(" ", _BRACKETS.sub(" ", (title or "").lower()))
    return " ".join(_WORDS.get(w, w) for w in _clean(text).split())


def dedupe_hash(company, title, city):
    raw = f"{norm_company(company)}|{norm_title(title)}|{(city or '').lower()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def similar_titles(a, b):
    """a and b are already normalised with norm_title()."""
    return a == b or SequenceMatcher(None, a, b).ratio() >= FUZZY_THRESHOLD

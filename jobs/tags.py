"""Skill tags shown on job cards, guessed from the job title."""
import re

_TAGS = {
    "Python": r"python|django|flask",
    "Java": r"java|spring|kotlin",
    "JavaScript": r"javascript|typescript|node(?:\.?js)?|angular|vue|next\.?js|full[- ]?stack|mern",
    "React": r"react",
    "Frontend": r"front[- ]?end|ui developer|web developer",
    "Backend": r"back[- ]?end|api|golang|\.net|php",
    "Mobile": r"android|ios|flutter|mobile|react native",
    "Data": r"data|analyst|analytics|sql|bi\b",
    "AI/ML": r"machine learning|\bml\b|\bai\b|deep learning|nlp|llm",
    "DevOps": r"devops|cloud|sre|aws|azure|infrastructure",
    "QA": r"\bqa\b|\btest(?:er|ing)?\b|quality",
    "Security": r"security|cyber|soc analyst",
    "Design": r"design|ux|ui/ux|graphic|figma",
    "Marketing": r"marketing|seo|content|social media|growth",
    "Sales": r"sales|business development|bdr|sdr",
    "Support": r"support|customer|success|service desk",
    "HR": r"\bhr\b|recruit|talent|people",
    "Finance": r"finance|account|audit|tax",
}
_COMPILED = {name: re.compile(r"(?<![a-z])(?:" + rx + r")(?![a-z])" if "\\b" not in rx else rx, re.I) for name, rx in _TAGS.items()}


def tags_for(title, limit=3):
    return [name for name, rx in _COMPILED.items() if rx.search(title)][:limit]

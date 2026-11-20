"""Role taxonomy + the rule-based tagger (the free baseline and the LLM's fallback)."""
import re

ROLES = [
    "Software Engineering", "Frontend", "Backend", "Full Stack", "Mobile", "Data & Analytics",
    "AI / ML", "DevOps & Cloud", "QA & Testing", "Design (UI/UX)", "Product",
    "Marketing & Content", "Sales & Business Dev", "Customer Support", "HR & Recruiting",
    "Finance & Accounting", "Operations", "Other",
]

# First match wins, so specific roles come before generic ones.
_RULES = [
    ("AI / ML", r"machine learning|\bml\b|\bai\b|deep learning|\bnlp\b|\bllm\b|computer vision|data scien"),
    ("Data & Analytics", r"data|analyst|analytics|\bsql\b|\bbi\b|business intelligence"),
    ("DevOps & Cloud", r"devops|\bcloud\b|\bsre\b|\baws\b|azure|infrastructure|site reliability"),
    ("QA & Testing", r"\bqa\b|\btest(?:er|ing)?\b|quality (?:assurance|engineer)|sdet"),
    ("Mobile", r"android|\bios\b|flutter|mobile|react native|swift"),
    ("Full Stack", r"full[- ]?stack|\bmern\b|\bmean\b"),
    ("Frontend", r"front[- ]?end|\bui developer|web developer|\breact\b|angular|\bvue\b"),
    ("Backend", r"back[- ]?end|\bapi\b|golang|\.net|\bphp\b|\bnode"),
    ("Design (UI/UX)", r"design|\bux\b|\bui/ux\b|graphic|figma|illustrat"),
    ("Product", r"product (?:manager|management|analyst|owner)|\bapm\b"),
    ("Marketing & Content", r"marketing|\bseo\b|content|social media|growth|copywrit|brand"),
    ("Sales & Business Dev", r"sales|business development|\bbdr\b|\bsdr\b|\bbda\b|inside sales"),
    ("Customer Support", r"support|customer (?:success|service|care)|service desk|helpdesk"),
    ("HR & Recruiting", r"\bhr\b|human resource|recruit|talent|people (?:ops|operations|partner)"),
    ("Finance & Accounting", r"financ|account|audit|\btax\b|\bcfa\b|\bca\b|bookkeep"),
    ("Operations", r"operations|logistics|supply chain|\bops\b|admin|coordinator|executive assistant"),
    ("Software Engineering", r"software|developer|engineer|\bsde\b|programmer|coding|\bjava\b|python|\.net|technical"),
]
_COMPILED = [(role, re.compile(rx, re.I)) for role, rx in _RULES]


def rules_role(title):
    for role, rx in _COMPILED:
        if rx.search(title or ""):
            return role
    return "Other"


def clean_role(value):
    """Map whatever the LLM wrote onto the fixed taxonomy (case-insensitive)."""
    wanted = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    for role in ROLES:
        if role.lower() == wanted:
            return role
    return "Other"

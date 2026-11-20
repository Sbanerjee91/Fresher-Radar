"""Turn messy location strings into (canonical city, is it in India?)."""
import re

CITIES = {
    "Bengaluru": ["bengaluru", "bangalore", "bengalooru"],
    "Mumbai": ["mumbai", "bombay", "navi mumbai", "thane"],
    "Pune": ["pune", "pimpri", "chinchwad"],
    "Hyderabad": ["hyderabad", "secunderabad"],
    "Chennai": ["chennai", "madras"],
    "Delhi": ["delhi", "new delhi", "ncr"],
    "Gurugram": ["gurugram", "gurgaon"],
    "Noida": ["noida", "greater noida"],
    "Kolkata": ["kolkata", "calcutta"],
    "Ahmedabad": ["ahmedabad"],
    "Kochi": ["kochi", "cochin", "ernakulam"],
    "Thiruvananthapuram": ["thiruvananthapuram", "trivandrum"],
    "Kozhikode": ["kozhikode", "calicut"],
    "Coimbatore": ["coimbatore"],
    "Jaipur": ["jaipur"],
    "Indore": ["indore"],
    "Chandigarh": ["chandigarh", "mohali"],
    "Lucknow": ["lucknow"],
    "Nagpur": ["nagpur"],
    "Bhubaneswar": ["bhubaneswar"],
    "Vadodara": ["vadodara", "baroda"],
    "Surat": ["surat"],
    "Mysuru": ["mysuru", "mysore"],
    "Visakhapatnam": ["visakhapatnam", "vizag"],
    "Bhopal": ["bhopal"],
    "Patna": ["patna"],
    "Nashik": ["nashik"],
}
STATES = [
    "andhra pradesh", "telangana", "karnataka", "tamil nadu", "kerala", "maharashtra", "gujarat",
    "rajasthan", "madhya pradesh", "uttar pradesh", "uttarakhand", "haryana", "punjab", "west bengal",
    "odisha", "bihar", "jharkhand", "chhattisgarh", "assam", "goa", "himachal pradesh",
]
REMOTE = "Remote"
UNSPECIFIED = "India (unspecified)"

_CITY_RX = {name: re.compile(r"\b(?:" + "|".join(aliases) + r")\b") for name, aliases in CITIES.items()}
_ALIAS_TO_CITY = {a: name for name, aliases in CITIES.items() for a in aliases}
_INDIA_RX = re.compile(r"\bindia\b|\b(?:" + "|".join(STATES) + r")\b")
_REMOTE_RX = re.compile(r"\bremote\b|work from home|\bwfh\b|\banywhere\b")
KNOWN_CITIES = set(CITIES) | {REMOTE, UNSPECIFIED}


def canonical_city(text):
    """'Bangalore' -> 'Bengaluru'. Returns None if the text names no known city."""
    text = (text or "").lower().strip()
    if text in _ALIAS_TO_CITY:
        return _ALIAS_TO_CITY[text]
    if text == "remote":
        return REMOTE
    return None


def parse_location(location, india_source=False):
    """Returns (city, is_india).

    india_source=True means the API was already queried for India only, so a bare
    "Remote" or "Maharashtra" is trusted. For global job boards the text itself must
    mention India, an Indian state or a known Indian city.
    """
    text = (location or "").lower()
    found = [(m.start(), name) for name, rx in _CITY_RX.items() if (m := rx.search(text))]
    if found:  # several cities ("Pune / Mumbai"): the first one written wins
        return min(found)[1], True
    is_india = bool(_INDIA_RX.search(text)) or india_source
    if not is_india:
        return "", False
    if _REMOTE_RX.search(text):
        return REMOTE, True
    first = re.split(r"[,/|;-]", location or "")[0].strip()
    if first and first.lower() not in STATES and first.lower() != "india":
        return first.title(), True  # a smaller town, e.g. "Rajkot, Gujarat"
    return UNSPECIFIED, True

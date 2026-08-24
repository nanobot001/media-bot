"""
Authoritative single source of truth for classifying media as Major Studio vs Indie & Boutique.
"""
import re
from typing import Optional, Sequence, Union, Dict, Any

MAJOR_STUDIO_NAMES = (
    "walt disney", "disney", "marvel studios", "pixar", "lucasfilm",
    "20th century studios", "20th century fox", "20th television",
    "warner bros", "warner pictures", "dc studios", "dc films", "dc entertainment",
    "paramount pictures", "paramount animation", "paramount+",
    "universal pictures", "universal studios",
    "columbia pictures", "sony pictures", "tristar pictures", "screen gems",
    "metro-goldwyn-mayer", "mgm", "amazon mgm studios", "amazon studios",
    "apple original films", "apple studios",
    "netflix", "lionsgate", "summit entertainment",
    "dreamworks animation", "dreamworks pictures", "illumination",
    "gracie films", "legendary pictures", "legendary entertainment", "new line cinema",
    "village roadshow", "amblin entertainment", "blumhouse"
)

INDIE_MOCKBUSTER_STUDIOS = (
    "the asylum", "asylum", "full moon features", "full moon", "troma",
    "corman", "syfy", "marvista", "itn distribution", "uncork'd", "wild eye",
    "the asylum home entertainment", "graveyard shift"
)

MAJOR_NETWORKS = (
    "hbo", "max", "netflix", "apple tv+", "prime video", "amazon", "disney+",
    "hulu", "paramount+", "peacock", "showtime", "amc", "fx", "cbs", "nbc", "abc", "fox", "bbc"
)

MAJOR_FRANCHISE_REGEX = re.compile(
    r"\b(the simpsons|simpsons|star wars|marvel|avengers|batman|superman|spider-man|spiderman|deadpool|wolverine|toy story|jurassic park|jurassic world|transformers|harry potter|lord of the rings|fast & furious|fast and furious|mission:\s*impossible|james bond|007|godzilla|king kong|shrek|despicable me|minions|homer|disney|pixar)\b",
    re.IGNORECASE
)


def classify_media_tier(
    title: str = "",
    overview: str = "",
    vote_count: int = 0,
    popularity: float = 0.0,
    budget: Optional[int] = None,
    revenue: Optional[int] = None,
    production_companies: Optional[Sequence[Union[str, Dict[str, Any]]]] = None,
    networks: Optional[Sequence[Union[str, Dict[str, Any]]]] = None,
) -> str:
    """
    Authoritative classifier for Major Studio vs Indie & Boutique media.
    Returns 'major' or 'indie'.
    """
    # 1. Check for explicit low-budget B-movie / mockbuster studios first
    if production_companies:
        for c in production_companies:
            c_name = (c.get("name") if isinstance(c, dict) else str(c)).lower()
            if any(s in c_name for s in INDIE_MOCKBUSTER_STUDIOS):
                return "indie"

    # 2. Check for recognized Major Studio production companies
    if production_companies:
        for c in production_companies:
            c_name = (c.get("name") if isinstance(c, dict) else str(c)).lower()
            if any(s in c_name for s in MAJOR_STUDIO_NAMES):
                return "major"

    # 3. Check for recognized Major TV Networks / Streamers
    if networks:
        for n in networks:
            n_name = (n.get("name") if isinstance(n, dict) else str(n)).lower()
            if any(s in n_name for s in MAJOR_NETWORKS):
                return "major"

    # 4. Financial Scale
    if budget and budget >= 20_000_000:
        return "major"
    if revenue and revenue >= 40_000_000:
        return "major"

    # 5. Major Franchise IP Regex Match in Title
    if title and MAJOR_FRANCHISE_REGEX.search(title):
        return "major"

    # 6. Global Engagement / Vote Footprint (Statistical empirical threshold for wide-release global distribution)
    if vote_count >= 800 or (vote_count >= 500 and popularity >= 50.0):
        return "major"

    return "indie"


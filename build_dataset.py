"""
Orchard Gate - Dataset Builder
==============================

Converts the raw qualification output (qualify_checkpoint.jsonl, produced by
qualify.py) into the exact shape the FastAPI service and dashboard expect,
writing `prospect_data.json`.

Three things happen here:

1. Encoding repair. The crawler read some UTF-8 directory pages as Latin-1,
   leaving names like "CaffÃ¨" and "MÃ¸rkÃ¸v". A cp1252 -> utf-8 round-trip
   restores them.
2. Country recovery. The directory listing carries a flag emoji plus a
   two-letter code (e.g. "🇩🇰 DK 540 listings"). That is ground truth, so it
   wins over the LLM's inferred geography, which is often "Unknown".
3. Noise filtering. Directory chrome (cookie banners, app-store links,
   calculators) occasionally survives scraping. Anything scoring below
   MIN_PRIORITY_SCORE is dropped.

Usage:
    python build_dataset.py
    python build_dataset.py --input qualify_checkpoint.jsonl --output prospect_data.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_INPUT = "qualify_checkpoint.jsonl"
DEFAULT_OUTPUT = "prospect_data.json"

# Records below this score are directory noise, not buyers.
MIN_PRIORITY_SCORE = 20.0

# Two-letter code -> country name, for the flag emoji embedded in the listing.
COUNTRY_NAMES: Dict[str, str] = {
    "AL": "Albania", "AM": "Armenia", "AT": "Austria", "AU": "Australia",
    "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria",
    "BR": "Brazil", "BY": "Belarus", "CA": "Canada", "CH": "Switzerland",
    "CL": "Chile", "CN": "China", "CO": "Colombia", "CR": "Costa Rica",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "DO": "Dominican Republic", "EE": "Estonia", "EG": "Egypt",
    "ES": "Spain", "ET": "Ethiopia", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GR": "Greece",
    "GT": "Guatemala", "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia",
    "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IN": "India", "IS": "Iceland", "IT": "Italy", "JP": "Japan",
    "KE": "Kenya", "KR": "South Korea", "KZ": "Kazakhstan",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "MA": "Morocco", "MD": "Moldova", "ME": "Montenegro", "MK": "North Macedonia",
    "MT": "Malta", "MX": "Mexico", "MY": "Malaysia", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PE": "Peru", "PL": "Poland",
    "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "RU": "Russia",
    "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore",
    "SI": "Slovenia", "SK": "Slovakia", "SV": "El Salvador",
    "TH": "Thailand", "TR": "Turkey", "TW": "Taiwan", "UA": "Ukraine",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VN": "Vietnam", "ZA": "South Africa",
}

_FALLBACK_COUNTRY_NAMES = {name.lower(): name for name in COUNTRY_NAMES.values()}
_FALLBACK_COUNTRY_NAMES.update({
    "usa": "United States", "u.s.a.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "czech republic": "Czechia",
    "the netherlands": "Netherlands", "holland": "Netherlands",
})

_COUNTRY_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted(_FALLBACK_COUNTRY_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# A resolved country must look like a country name, not a stray initial
# ("P Public Coffee Roasters...") or a listing count ("PL 138 listings").
_VALID_COUNTRY_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' .\-()]{2,}$")

# Spelling variants -> canonical name, so the dashboard does not show both
# "USA" and "United States" (or "Czech Republic" and "Czechia").
COUNTRY_ALIASES: Dict[str, str] = {
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "us": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "wales": "United Kingdom",
    "czech republic": "Czechia",
    "holland": "Netherlands",
    "the netherlands": "Netherlands",
    "turkey": "Turkey",
    "uae": "United Arab Emirates",
    "emirates": "United Arab Emirates",
    "vietnam": "Vietnam",
    "viet nam": "Vietnam",
    "russia": "Russia",
    "russian federation": "Russia",
    "south korea": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "taiwan": "Taiwan",
    "hong kong": "Hong Kong",
    "macau": "Macau",
    "ivory coast": "Côte d'Ivoire",
    "cote d'ivoire": "Côte d'Ivoire",
}

# City -> country, used only when a record has no usable country at all.
# Keyed on lowercase city name. Deliberately conservative: no ambiguous names.
CITY_TO_COUNTRY: Dict[str, str] = {
    # Netherlands
    "amsterdam": "Netherlands", "rotterdam": "Netherlands", "utrecht": "Netherlands",
    "eindhoven": "Netherlands", "groningen": "Netherlands", "haarlem": "Netherlands",
    "delft": "Netherlands", "breda": "Netherlands", "nijmegen": "Netherlands",
    # Germany
    "berlin": "Germany", "hamburg": "Germany", "munich": "Germany",
    "munchen": "Germany", "cologne": "Germany", "koln": "Germany",
    "stuttgart": "Germany", "leipzig": "Germany", "kiel": "Germany",
    "dresden": "Germany", "frankfurt": "Germany", "dusseldorf": "Germany",
    "hannover": "Germany", "bremen": "Germany", "dortmund": "Germany",
    "essen": "Germany", "bonn": "Germany", "munster": "Germany",
    "karlsruhe": "Germany", "mannheim": "Germany", "augsburg": "Germany",
    "wiesbaden": "Germany", "nuremberg": "Germany", "nurnberg": "Germany",
    "freiburg": "Germany", "heidelberg": "Germany", "rostock": "Germany",
    # Austria
    "vienna": "Austria", "wien": "Austria", "graz": "Austria",
    "salzburg": "Austria", "linz": "Austria", "innsbruck": "Austria",
    "klagenfurt": "Austria", "st. polten": "Austria", "st pölten": "Austria",
    # Switzerland
    "zurich": "Switzerland", "zürich": "Switzerland", "geneva": "Switzerland",
    "geneve": "Switzerland", "basel": "Switzerland", "bern": "Switzerland",
    "lausanne": "Switzerland", "lugano": "Switzerland", "winterthur": "Switzerland",
    # Czechia / Slovakia
    "prague": "Czechia", "praha": "Czechia", "brno": "Czechia",
    "ostrava": "Czechia", "bratislava": "Slovakia", "kosice": "Slovakia",
    # Poland
    "warsaw": "Poland", "warszawa": "Poland", "krakow": "Poland",
    "kraków": "Poland", "gdansk": "Poland", "gdańsk": "Poland",
    "wroclaw": "Poland", "poznan": "Poland", "lodz": "Poland",
    "katowice": "Poland", "lublin": "Poland", "szczecin": "Poland",
    "gdynia": "Poland", "poznań": "Poland", "łódź": "Poland",
    # Hungary / Romania / Bulgaria / Balkans
    "budapest": "Hungary", "debrecen": "Hungary", "szeged": "Hungary",
    "bucharest": "Romania", "bucuresti": "Romania", "cluj": "Romania",
    "timisoara": "Romania", "iasi": "Romania", "brasov": "Romania",
    "constanta": "Romania", "targu mures": "Romania",
    "sofia": "Bulgaria", "plovdiv": "Bulgaria", "varna": "Bulgaria",
    "zagreb": "Croatia", "split": "Croatia", "rijeka": "Croatia",
    "ljubljana": "Slovenia", "belgrade": "Serbia", "beograd": "Serbia",
    "novi sad": "Serbia", "sarajevo": "Bosnia and Herzegovina",
    "skopje": "North Macedonia", "tirana": "Albania",
    "podgorica": "Montenegro", "chisinau": "Moldova",
    # Nordics / Baltics
    "copenhagen": "Denmark", "kobenhavn": "Denmark", "aarhus": "Denmark",
    "odense": "Denmark", "stockholm": "Sweden", "gothenburg": "Sweden",
    "göteborg": "Sweden", "malmo": "Sweden", "malmö": "Sweden",
    "uppsala": "Sweden", "oslo": "Norway", "bergen": "Norway",
    "trondheim": "Norway", "stavanger": "Norway",
    "helsinki": "Finland", "espoo": "Finland", "tampere": "Finland",
    "turku": "Finland", "vantaa": "Finland", "oulu": "Finland",
    "reykjavik": "Iceland", "reykjavík": "Iceland",
    "vilnius": "Lithuania", "kaunas": "Lithuania", "riga": "Latvia",
    "tallinn": "Estonia", "tartu": "Estonia",
    "kyiv": "Ukraine", "kiev": "Ukraine", "lviv": "Ukraine",
    "kharkiv": "Ukraine", "odesa": "Ukraine", "dnipro": "Ukraine",
    # Italy / Iberia / France / UK / Ireland
    "milan": "Italy", "milano": "Italy", "rome": "Italy", "roma": "Italy",
    "turin": "Italy", "torino": "Italy", "florence": "Italy",
    "firenze": "Italy", "naples": "Italy", "napoli": "Italy",
    "bologna": "Italy", "palermo": "Italy", "genoa": "Italy",
    "genova": "Italy", "venice": "Italy", "venezia": "Italy",
    "verona": "Italy", "bari": "Italy", "catania": "Italy",
    "madrid": "Spain", "barcelona": "Spain", "valencia": "Spain",
    "seville": "Spain", "sevilla": "Spain", "bilbao": "Spain",
    "malaga": "Spain", "zaragoza": "Spain", "lisbon": "Portugal",
    "lisboa": "Portugal", "porto": "Portugal", "braga": "Portugal",
    "coimbra": "Portugal", "paris": "France", "lyon": "France",
    "marseille": "France", "bordeaux": "France", "toulouse": "France",
    "nantes": "France", "lille": "France", "strasbourg": "France",
    "montpellier": "France", "dublin": "Ireland", "cork": "Ireland",
    "galway": "Ireland", "london": "United Kingdom",
    "manchester": "United Kingdom", "birmingham": "United Kingdom",
    "bristol": "United Kingdom", "leeds": "United Kingdom",
    "glasgow": "United Kingdom", "edinburgh": "United Kingdom",
    "liverpool": "United Kingdom", "sheffield": "United Kingdom",
    "athens": "Greece", "thessaloniki": "Greece", "patras": "Greece",
    # Turkey / Middle East / Africa
    "istanbul": "Turkey", "ankara": "Turkey", "izmir": "Turkey",
    "tel aviv": "Israel", "jerusalem": "Israel",
    "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "riyadh": "Saudi Arabia", "jeddah": "Saudi Arabia",
    "cairo": "Egypt", "alexandria": "Egypt",
    "nairobi": "Kenya", "addis ababa": "Ethiopia",
    "johannesburg": "South Africa", "cape town": "South Africa",
    "durban": "South Africa",
    # India
    "mumbai": "India", "bengaluru": "India", "bangalore": "India",
    "new delhi": "India", "delhi": "India", "chennai": "India",
    "kolkata": "India", "hyderabad": "India", "pune": "India",
    "mysore": "India", "mysuru": "India", "chikmagalur": "India",
    "coorg": "India", "goa": "India",
    # Asia-Pacific
    "tokyo": "Japan", "osaka": "Japan", "kyoto": "Japan",
    "seoul": "South Korea", "busan": "South Korea",
    "shanghai": "China", "beijing": "China", "shenzhen": "China",
    "guangzhou": "China", "taipei": "Taiwan",
    "bangkok": "Thailand", "chiang mai": "Thailand",
    "kuala lumpur": "Malaysia", "singapore": "Singapore",
    "jakarta": "Indonesia", "bandung": "Indonesia",
    "ho chi minh city": "Vietnam", "hanoi": "Vietnam",
    "manila": "Philippines", "sydney": "Australia",
    "melbourne": "Australia", "brisbane": "Australia",
    "perth": "Australia", "adelaide": "Australia",
    "auckland": "New Zealand", "wellington": "New Zealand",
    "christchurch": "New Zealand",
    # North America
    "new york": "United States", "los angeles": "United States",
    "san francisco": "United States", "chicago": "United States",
    "seattle": "United States", "portland": "United States",
    "austin": "United States", "boston": "United States",
    "denver": "United States", "miami": "United States",
    "atlanta": "United States", "houston": "United States",
    "dallas": "United States", "philadelphia": "United States",
    "phoenix": "United States", "san diego": "United States",
    "minneapolis": "United States", "detroit": "United States",
    "nashville": "United States", "pittsburgh": "United States",
    "baltimore": "United States", "washington": "United States",
    "toronto": "Canada", "vancouver": "Canada", "montreal": "Canada",
    "calgary": "Canada", "ottawa": "Canada",
}


def canonicalize_country(value: str) -> Optional[str]:
    """Normalise a country string, stripping any leading city segment."""
    if not value:
        return None
    text = value.strip()
    if not text or text.lower() in ("unknown", "n/a", "na", ""):
        return None
    if "," in text:
        tail = text.split(",")[-1].strip()
        if tail:
            text = tail
    key = text.lower()
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    if key in _FALLBACK_COUNTRY_NAMES:
        return _FALLBACK_COUNTRY_NAMES[key]
    if not _VALID_COUNTRY_RE.match(text):
        return None
    return text


def country_from_city(text: str) -> Optional[str]:
    """Infer a country from a known city name appearing in free text."""
    lowered = (text or "").lower()
    if not lowered:
        return None
    for city in sorted(CITY_TO_COUNTRY, key=len, reverse=True):
        if re.search(r"\b" + re.escape(city) + r"\b", lowered):
            return CITY_TO_COUNTRY[city]
    return None


def repair_text(value: Any) -> Any:
    """Undo UTF-8-read-as-Latin-1 mojibake where possible."""
    if not isinstance(value, str):
        return value
    try:
        return value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _flag_code(text: str) -> Optional[str]:
    """Pull the ISO country code out of a flag emoji."""
    regional = [c for c in text if 0x1F1E6 <= ord(c) <= 0x1F1FF]
    if len(regional) < 2:
        return None
    code = "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in regional[:2])
    return code if code in COUNTRY_NAMES else None


def derive_country(record: Dict[str, Any]) -> str:
    """Resolve a readable country name.

    Order of preference: the directory's own flag emoji (ground truth), then
    the LLM's geography, then a country name in the text, then a city lookup.
    """
    location = repair_text(record.get("country_city")) or ""

    code = _flag_code(location)
    if code:
        return COUNTRY_NAMES[code]

    for candidate in (record.get("geography"), location):
        resolved = canonicalize_country(repair_text(candidate) or "")
        if resolved:
            return resolved

    for source in (location, record.get("company_name")):
        if not isinstance(source, str):
            continue
        match = _COUNTRY_NAME_RE.search(repair_text(source) or "")
        if match:
            resolved = canonicalize_country(match.group(1))
            if resolved:
                return resolved

    for source in (location, record.get("company_name")):
        if not isinstance(source, str):
            continue
        inferred = country_from_city(repair_text(source) or "")
        if inferred:
            return inferred

    return "Unknown"


def load_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    skipped = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                skipped += 1
    if skipped:
        print(f"Skipped {skipped} unparseable line(s)")
    return records


def to_api_prospect(index: int, record: Dict[str, Any]) -> Dict[str, Any]:
    offerings = record.get("recommended_offerings") or []
    if isinstance(offerings, list):
        offerings_text = ", ".join(str(o) for o in offerings)
    else:
        offerings_text = str(offerings)

    try:
        score = round(float(record.get("priority_score") or 0.0), 1)
    except (TypeError, ValueError):
        score = 0.0

    return {
        "sn": index,
        "company_name": repair_text(record.get("company_name")) or "Unknown",
        "country": derive_country(record),
        "buyer_category": repair_text(record.get("buyer_type"))
        or repair_text(record.get("buyer_category_scraped"))
        or "Unknown",
        "priority_score": score,
        "key_offerings": offerings_text or "To be confirmed",
        "rationale": repair_text(record.get("relevance_rationale")) or "",
        "data_health_status": record.get("data_health_status") or "Partial",
        "website": repair_text(record.get("website")) or "",
        "priority_tier": record.get("priority_tier") or "D",
        "buyer_potential": repair_text(record.get("buyer_potential")) or "",
    }


def build(input_path: Path, output_path: Path) -> List[Dict[str, Any]]:
    records = load_records(input_path)

    kept = []
    for record in records:
        try:
            score = float(record.get("priority_score") or 0.0)
        except (TypeError, ValueError):
            continue
        if score < MIN_PRIORITY_SCORE:
            continue
        kept.append(record)

    kept.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)

    prospects = [to_api_prospect(i + 1, r) for i, r in enumerate(kept)]

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(prospects, handle, ensure_ascii=False, indent=2)

    return prospects


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the API prospect dataset.")
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    prospects = build(input_path, Path(args.output))
    if not prospects:
        raise SystemExit("No prospects survived filtering.")

    scores = [p["priority_score"] for p in prospects]
    unknown = sum(1 for p in prospects if p["country"] == "Unknown")

    print(f"Wrote {len(prospects)} prospects to {args.output}")
    print(f"Average priority score: {sum(scores) / len(scores):.1f}")
    print(f"Top score: {max(scores)}")
    print(f"Unknown country: {unknown} ({unknown / len(prospects):.1%})")


if __name__ == "__main__":
    main()
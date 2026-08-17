import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import re
import requests

# ============================================================
# CONFIGURATION & CONSTANTS
# ============================================================

API_URL = "https://ca.iiivega.com/api/search-result/search/format-groups"
CUSTOMER_DOMAIN = "kpl-kitch.ca.iiivega.com"
HOST_DOMAIN = "kpl-kitch.ca.iiivega.com"
ANONYMOUS_USER_ID = "dea947e8-3b30-4191-b55d-5221ff3d5d6b"

HEADERS = {
    "accept": "application/json, text/plain, */*",
    "api-version": "2",
    "anonymous-user-id": ANONYMOUS_USER_ID,
    "content-type": "application/json",
    "iii-customer-domain": CUSTOMER_DOMAIN,
    "iii-host-domain": HOST_DOMAIN,
    "origin": f"https://{CUSTOMER_DOMAIN}",
    "referer": f"https://{CUSTOMER_DOMAIN}/",
}

PLATFORM_STOP_WORDS = {"ps5", "ps4", "xbox", "switch", "nintendo", "pc"}
FORMAT_STOP_WORDS = {"dvd", "blu-ray", "movie", "book", "audiobook", "cd", "music"}


# ============================================================
# ENTERPRISE QUERY UNDERSTANDING (QU) & FACET EXTRACTION
# ============================================================

def parse_query_generalized(raw_query):
    """
    Generalized enterprise query parser:
    Extracts temporal patterns (years) and constraints (platforms/formats) 
    from any unstructured text string using regex and token analysis.
    """
    # 1. Extract 4-digit years (e.g., 2024, 1999) dynamically
    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', raw_query)
    extracted_year = year_match.group(1) if year_match else None

    # 2. Tokenize and extract platforms/formats
    tokens = raw_query.lower().split()
    extracted_platforms = []
    extracted_formats = []
    core_tokens = []

    for token in tokens:
        # Skip the year token from core text search
        if extracted_year and token == extracted_year:
            continue
            
        if token in PLATFORM_STOP_WORDS:
            extracted_platforms.append(token.upper())
        elif token in FORMAT_STOP_WORDS:
            extracted_formats.append(token.capitalize())
        else:
            core_tokens.append(token)

    core_query = " ".join(core_tokens) if core_tokens else raw_query

    return {
        "core_query": core_query,
        "year_filter": extracted_year,
        "platforms": extracted_platforms,
        "formats": extracted_formats,
        "raw_query": raw_query
    }


def search_catalog(raw_query, page_size=50):
    parsed = parse_query_generalized(raw_query)

    payload = {
        "pageNum": 0,
        "pageSize": page_size,
        "resourceType": "FormatGroup",
        "searchText": parsed["core_query"],
        "searchType": "everything",
        "sortOrder": "asc",
        "sorting": "relevance",
    }

    response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    items = data.get("data", [])

    # Fallback: if strict core tokens return nothing, try raw query string
    if not items and parsed["core_query"] != raw_query:
        payload["searchText"] = raw_query
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        items = data.get("data", [])

    # ========================================================
    # LEARNING-TO-RANK (LTR) & MULTI-FEATURE SCORING LAYER
    # ========================================================
    if items:
        scored_items = []
        core_words = set(parsed["core_query"].lower().split())

        for item in items:
            title = item.get("title", "").lower()
            pub_date = str(item.get("publicationDate", ""))
            item_blob = json.dumps(item).lower()

            # Base check: title relevance
            title_matches = any(word in title for word in core_words)
            if not title_matches and core_words:
                continue  # Suppress token pollution / irrelevant descriptions

            score = 10  # Base score

            # Feature 1: Temporal / Year Boosting
            if parsed["year_filter"] and parsed["year_filter"] in pub_date:
                score += 50  # Reward items matching the requested release year

            # Feature 2: Hardware Platform Boosting
            for p in parsed["platforms"]:
                if p.lower() in item_blob:
                    score += 40

            scored_items.append((score, item))

        # Sort dynamically by calculated feature score
        scored_items.sort(key=lambda x: x[0], reverse=True)
        data["data"] = [item for score, item in scored_items] if scored_items else items

    return data


# ============================================================
# DATA NORMALIZATION & SERVERLESS HANDLER
# ============================================================

def classify_item(item):
    tabs = item.get("materialTabs", [])
    names = {tab.get("name", "").lower() for tab in tabs if tab.get("name")}
    
    if "video game" in names:
        return "Video Game"
    if "book" in names:
        return "Book"
    if any(m in names for m in ["dvd", "blu-ray", "movie", "video"]):
        return "Movie / DVD"
    if any(m in names for m in ["music cd", "cd", "music"]):
        return "Music"
    if any(m in names for m in ["audiobook", "audio book"]):
        return "Audiobook"
    return "Other"


def normalize_item(item):
    material_tabs = item.get("materialTabs", [])
    locations = []

    for tab in material_tabs:
        for location in tab.get("locations", []):
            locations.append({
                "name": location.get("label", "Unknown Branch"),
                "status": location.get("availabilityStatus", "Unknown"),
            })
    
    unique_locations = []
    seen = set()
    for loc in locations:
        key = (loc["name"], loc["status"])
        if key not in seen:
            seen.add(key)
            unique_locations.append(loc)

    available_anywhere = any(loc["status"].lower() == "available" for loc in unique_locations)
    total_copies = sum(tab.get("itemCount", 0) for tab in material_tabs if isinstance(tab.get("itemCount"), int))
    
    cover_url = (
        item.get("coverUrl", {}).get("large") or 
        item.get("coverUrl", {}).get("medium")
    )

    return {
        "id": item.get("id"),
        "title": item.get("title", "Unknown title"),
        "category": classify_item(item),
        "publicationDate": item.get("publicationDate", ""),
        "description": item.get("description", ""),
        "cover": cover_url,
        "availableAnywhere": available_anywhere,
        "locations": unique_locations,
        "copies": total_copies,
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        query = params.get("q", [""])[0].strip()

        if not query:
            self.send_json({"items": []})
            return

        try:
            raw_response = search_catalog(query)
            normalized_items = [normalize_item(item) for item in raw_response.get("data", [])]
            self.send_json({"items": normalized_items})
        except Exception as error:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(error)}).encode())

    def send_json(self, data):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
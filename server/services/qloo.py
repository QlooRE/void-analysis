import ssl
import certifi
import urllib.request
import urllib.parse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed


def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))

_ssl_ctx = ssl.create_default_context(cafile=certifi.where())
_API_KEY  = os.environ.get("QLOO_API_KEY", "")
_BASE     = "https://staging.api.qloo.com"
_HEADERS  = {"x-api-key": _API_KEY}

AGE_GROUP_IDS = {
    "gen_z":            "24_and_younger",
    "young_millennial": "25_to_29",
    "millennial":       "30_to_34",
    "older_millennial": "35_to_44",
    "gen_x":            "45_to_54",
    "boomer":           "55_and_older",
}

# Tags that disqualify a brand (digital, non-retail physical, orgs)
_EXCLUDE_TAGS = {
    # Online / digital-only retail — no physical storefront
    # Note: Qloo tags these inconsistently; many DTC brands carry only generic fashion tags
    "online retailers", "online retailer", "online retailers of the united states",
    "online shopping", "online store",
    "direct to consumer", "dtc", "e-commerce", "ecommerce", "e-tailer",
    "e commerce app",        # Qloo tag on SHEIN, Amazon
    "subscription", "subscription box", "subscription service",
    "marketplace", "digital marketplace",
    "clothing rental companies",   # Rent the Runway etc.
    # Media & digital services
    "media", "website", "podcast", "streaming", "news & politics", "social media",
    "digital media", "news", "radio", "television", "music streaming",
    "software", "internet", "app", "saas",
    # Non-profits / orgs
    "ngo", "environmental ngo", "nonprofit",
    # Financial
    "financial services", "banking", "insurance",
    # Non-retail physical (not relevant to mall/ground-floor leasing)
    "museum", "art museum", "science museum", "gallery", "art gallery",
    "sports organization", "sports team", "major league baseball",
    "major league soccer", "nfl", "nba", "nhl", "mlb", "nascar",
    "professional services", "consulting", "real estate",
    "theme park", "amusement park", "zoo", "aquarium",
    "hospital", "healthcare", "clinic", "university", "college",
    "airline", "airport", "cruise", "hotel", "resort", "lodging",
    "record label", "music label", "publisher", "book publisher",
}

# Tag IDs / prefixes that confirm a place is NOT a non-food retail store.
# Used to filter false-positive place matches for clothing/beauty/home/electronics brands.
# Qloo place entities always have types=['urn:entity:place'] and subtype=None,
# so the tag IDs are the only reliable category signal.
_NONFOOD_BRAND_DISQUALIFY_PREFIXES = (
    "urn:tag:genre:restaurant",     # restaurant, bar, breakfast, food court, etc.
    "urn:tag:cuisine:qloo:",        # any cuisine style
    "urn:tag:culinary_style:qloo:",
    "urn:tag:dining_options:",      # dine-in, takeout, etc. — only on food venues
)
_NONFOOD_BRAND_DISQUALIFY_VALUES = {
    # Food & drink
    "urn:tag:category:bar",
    "urn:tag:category:pub",
    "urn:tag:category:restaurant",
    "urn:tag:category:breakfast_restaurant",
    "urn:tag:genre:place:pub",
    "urn:tag:genre:place:bar",
    "urn:tag:genre:place:brewery",
    "urn:tag:genre:place:coffee_shop",
    "urn:tag:genre:place:cafe",
    "urn:tag:genre:place:bakery",
    # Cannabis
    "urn:tag:category:cannabis_store",
    "urn:tag:genre:place:cannabis_store",
    # Yoga / fitness studios (not retail)
    "urn:tag:category:yoga_studio",
    "urn:tag:genre:place:yoga_studio",
    "urn:tag:category:gym",
    "urn:tag:genre:place:gym",
    # Event / entertainment venues
    "urn:tag:genre:place:event_venue",
    "urn:tag:genre:place:music_venue",
    "urn:tag:genre:place:night_club",
    "urn:tag:genre:place:performing_arts_theater",
}

# Brand tags indicating non-food retail (clothing, beauty, home goods, etc.)
_NONFOOD_RETAIL_TAGS = {
    "clothing", "fashion", "apparel", "sportswear", "footwear", "shoe",
    "sneakers", "streetwear", "luxury", "accessories", "jewelry", "watches",
    "eyewear", "swimwear", "lingerie", "activewear", "denim", "kids clothing",
    "beauty", "cosmetics", "skincare", "fragrance",
    "furniture", "home goods", "home decor", "kitchenware",
    "electronics", "sporting goods", "bookstore", "pet store",
}

# Tags that positively confirm retail or dining relevance
_RETAIL_TAGS = {
    # Apparel & accessories
    "clothing", "fashion", "apparel", "sportswear", "footwear",
    "shoe", "sneakers", "outdoor clothing", "streetwear", "luxury",
    "bags & leather", "accessories", "jewelry", "watches", "eyewear",
    "swimwear", "lingerie", "activewear", "denim", "kids clothing",
    # Food & beverage
    "restaurant", "fast food", "fast casual", "coffee", "cafe",
    "bakery", "dessert", "ice cream", "smoothie", "juice bar",
    "pizza", "burger", "sushi", "taco", "sandwich", "noodle",
    "steakhouse", "seafood", "brunch", "bar", "cocktail bar",
    "wine bar", "brewery", "food & beverage", "cuisine",
    # Beauty & personal care
    "beauty", "cosmetics", "skincare", "hair salon", "nail salon",
    "fragrance", "wellness", "spa",
    # Home & lifestyle
    "furniture", "home goods", "home decor", "kitchenware", "candles",
    "florist", "stationery",
    # Electronics & specialty retail
    "electronics", "sporting goods", "outdoor", "toys", "games",
    "bookstore", "pet store", "pharmacy", "grocery", "specialty retail",
    # General retail
    "retail", "department store", "boutique", "market",
}


def _get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, context=_ssl_ctx, timeout=20) as res:
        return json.loads(res.read())


def _brand_is_nonfood(tags):
    """True if brand tags indicate non-food retail (clothing, beauty, home, electronics…)."""
    lower = {t.lower() for t in tags}
    return any(nf in lower for nf in _NONFOOD_RETAIL_TAGS)


def _place_disqualified_for_nonfood_brand(entity):
    """True if a place should be rejected as a location for a non-food retail brand.

    Qloo place entities always have types=['urn:entity:place'] and subtype=None,
    so we read category from tag IDs. Disqualifies food venues, cannabis stores,
    yoga studios, and entertainment venues — anything clearly not a retail store.
    """
    for tag in entity.get("tags", []):
        tid = tag.get("tag_id", "")
        if tid in _NONFOOD_BRAND_DISQUALIFY_VALUES:
            return True
        if any(tid.startswith(p) for p in _NONFOOD_BRAND_DISQUALIFY_PREFIXES):
            return True
    return False


def _is_retail(tags):
    """Return True only if brand is a retailer or restaurant/cafe."""
    lower = {t.lower() for t in tags}
    if any(ex in t for t in lower for ex in _EXCLUDE_TAGS):
        return False
    return any(rt in t for t in lower for rt in _RETAIL_TAGS)


def get_affinity_brands(location_query, lat, lon, age_group_keys, entity_signals, tag_signals,
                        location_mode="locality", radius_m=8047, take=25):
    """Brands by affinity for this location, sampled across the popularity spectrum.

    Makes four calls at decreasing popularity ceilings (1.0 / 0.75 / 0.5 / 0.25),
    deduplicates by entity_id, and returns the union sorted by affinity descending.
    This ensures niche and emerging brands surface alongside mainstream ones, rather
    than the single-call result being dominated by globally popular names.

    location_mode:
        'locality' — signal.location.query = named place (Qloo locality)
        'address'  — signal.location = POINT(lon lat) + signal.location.radius
    """
    age_ids = ",".join(AGE_GROUP_IDS[k] for k in age_group_keys if k in AGE_GROUP_IDS)

    base_params = {
        "filter.type":            "urn:entity:brand",
        "signal.location.weight": "very_high",
        "take":                   take,
    }

    if location_mode == "address":
        base_params["signal.location"]        = f"POINT({lon} {lat})"
        base_params["signal.location.radius"] = int(radius_m)
    else:
        base_params["signal.location.query"] = location_query

    if age_ids:
        base_params["signal.demographics.age.ids"] = age_ids
    if entity_signals:
        base_params["signal.interests.entities"] = ",".join(entity_signals)
    if tag_signals:
        base_params["signal.interests.tags"] = ",".join(tag_signals)

    seen_ids: dict = {}  # entity_id → brand dict (first occurrence wins)

    for pop_max in [1.0, 0.75, 0.5, 0.25]:
        try:
            data = _get(f"{_BASE}/v2/insights",
                        {**base_params, "filter.popularity.max": pop_max})
        except Exception as e:
            print(f"Brand affinity error (pop_max={pop_max}): {e}")
            continue
        for e in data.get("results", {}).get("entities", []):
            eid = e["entity_id"]
            if eid in seen_ids:
                continue
            tags  = [t["name"] for t in e.get("tags", [])]
            props = e.get("properties", {})
            seen_ids[eid] = {
                "id":          eid,
                "name":        e.get("name", ""),
                "affinity":    round(e.get("query", {}).get("affinity", 0), 4),
                "description": props.get("short_description", ""),
                "tags":        tags[:4],
                "is_retail":   _is_retail(tags),
            }

    return sorted(seen_ids.values(), key=lambda b: -b["affinity"])


def find_brand_locations(brand_name, target_city, target_state, target_metro, target_country,
                         lat=None, lon=None, location_mode="locality", radius_m=8047,
                         brand_tags=None):
    """Search Qloo place catalog for physical locations of a brand.

    In address mode, pre-filters results to within radius_m of (lat, lon).
    In locality mode, uses geocode city/state/metro matching for proximity tiers.

    brand_tags: list of tag strings for the brand, used to cross-validate place results.
    If a brand is tagged as non-food retail (clothing, beauty, etc.) but the found place
    is a bar/restaurant, it's rejected — preventing false matches like "Hatch" bar
    appearing as a location for "Hatch" the maternity clothing brand.
    """
    # Two-pass search for better local coverage:
    # 1. Targeted: "{brand} {target_city}" — biases results toward the market we care about
    # 2. Generic:  "{brand}"              — catches any national presence for Near Void vs Hard Void
    # Qloo's place search has no location filter, so a pure generic search often returns
    # only the brand's most globally prominent stores, missing local ones entirely.
    raw_results: dict = {}  # entity_id → entity (deduplicated)
    queries = [f"{brand_name} {target_city}", brand_name] if target_city else [brand_name]
    for q in queries:
        try:
            data = _get(f"{_BASE}/search", {"query": q, "types": "urn:entity:place", "take": 10})
            for e in data.get("results", []):
                eid = e.get("entity_id")
                if eid and eid not in raw_results:
                    raw_results[eid] = e
        except Exception as ex:
            print(f"Place search error for '{q}': {ex}")

    nonfood_brand = _brand_is_nonfood(brand_tags or [])

    brand_lower = brand_name.lower()

    locations = []
    for e in raw_results.values():
        # Name validation: place must be related to the brand, not just any venue that
        # happened to appear in a "{brand} {city}" query (e.g. "Trump Tower" from "Nike Chicago")
        place_name_lower = e.get("name", "").lower()
        if not (brand_lower in place_name_lower or place_name_lower in brand_lower):
            continue

        # Cross-category guard: skip clearly wrong-category venues for non-food retail brands
        if nonfood_brand and _place_disqualified_for_nonfood_brand(e):
            continue

        props   = e.get("properties", {})
        address = props.get("address", "")
        geocode = props.get("geocode") or {}
        city    = (geocode.get("city") or "").lower()
        state   = (geocode.get("admin1_region") or "").lower()
        metro   = (geocode.get("metro") or "").lower()
        country = (geocode.get("country_code") or "").lower()
        name    = e.get("name", "")

        if not address:
            continue

        # Tier matching is the same for both modes — geocode fields are authoritative
        if city and city == target_city.lower():
            tier = "city"
        elif metro and metro == target_metro.lower():
            tier = "metro"
        elif state and state == target_state.lower():
            tier = "state"
        elif country and country == target_country.lower():
            tier = "country"
        else:
            tier = "other"

        locations.append({
            "name":    name,
            "address": address,
            "city":    geocode.get("city", ""),
            "state":   geocode.get("admin1_region", ""),
            "metro":   geocode.get("metro", ""),
            "tier":    tier,
        })

    return locations


# In address mode, affinity is measured within a tight 2-block radius (~300 m) to
# capture hyper-local taste signals at a specific site. The user's chosen radius_m
# is used separately for void assessment (how far to look for physical locations).
_AFFINITY_RADIUS_ADDRESS_M = 300

def analyze_voids(location_query, lat, lon, age_group_keys, entity_signals, tag_signals,
                  geo_context, location_mode="locality", radius_m=8047):
    """
    1. Fetch affinity brands from Qloo (demand signal)
       — address mode: 2-block (~300 m) affinity radius for hyper-local taste signal
       — locality mode: full locality used as the signal area
    2. Filter to retail/dining brands only
    3. For each brand, search Qloo place catalog for store presence
    4. Classify void status by proximity tier (mode-aware)
       — address mode: metro → Underserved, state → Available, country → Near Void
       — locality mode: metro/state → Underserved, country → Near Void
    """
    affinity_radius = _AFFINITY_RADIUS_ADDRESS_M if location_mode == "address" else radius_m
    affinity_brands = get_affinity_brands(
        location_query, lat, lon, age_group_keys, entity_signals, tag_signals,
        location_mode=location_mode, radius_m=affinity_radius,
    )

    target_city    = geo_context.get("city", "")
    target_state   = geo_context.get("state", "")
    target_metro   = geo_context.get("metro", "")
    target_country = geo_context.get("country_code", "US")

    # Filter to retail/dining only; cap at 30 to keep enrichment time reasonable
    retail_brands = [b for b in affinity_brands if b["is_retail"]]
    bm_brands = retail_brands[:30]

    STATUS_ORDER = {"Pop-up Candidate": 0, "Near Void": 1, "Available": 2, "Underserved": 3, "Present": 4}

    def enrich(brand):
        locations = find_brand_locations(
            brand["name"], target_city, target_state, target_metro, target_country,
            lat=lat, lon=lon, location_mode=location_mode, radius_m=radius_m,
            brand_tags=brand.get("tags", []),
        )

        tiers = {loc["tier"] for loc in locations}

        if "city" in tiers:
            # Already operating in this city
            status, status_class = "Present", "present"
        elif "metro" in tiers:
            # Within the metro area — close but not at this location
            status, status_class = "Underserved", "underserved"
        elif "state" in tiers:
            if location_mode == "address":
                # Address mode: state-level = accessible by car (~25–50 mi range)
                status, status_class = "Available", "available"
            else:
                # Locality mode: in-state counts as underserved
                status, status_class = "Underserved", "underserved"
        elif "country" in tiers or locations:
            # Has physical presence but not in this region
            status, status_class = "Near Void", "near-void"
        else:
            # No physical locations found — brand may be DTC/digital-first;
            # flag as pop-up candidate rather than a traditional void
            status, status_class = "Pop-up Candidate", "hard-void"

        nearby = [l for l in locations if l["tier"] in ("city", "metro", "state")]

        return {
            **brand,
            "status":        status,
            "status_class":  status_class,
            "nearby_count":  len(nearby),   # locations confirmed in city/metro/state
            "nearby":        nearby[:3],
        }

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(enrich, b): b for b in bm_brands}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass

    results.sort(key=lambda b: (STATUS_ORDER[b["status"]], -b["affinity"]))
    return results, len(affinity_brands) - len(retail_brands)


# Maps Qloo genre keys (from urn:tag:genre:place:restaurant:{key}) to
# (display_name, search_queries, all_genre_keys).
#
# display_name:   shown in the UI
# search_queries: sent to /search as "{query} {city}" to count local supply
# all_genre_keys: full set of genre/category key suffixes for this cuisine
#   (the discovered key plus close variants that should be counted together,
#    e.g. "sushi" and "sushi_bar" are both Japanese supply)
#
# Used in Step 2 (supply counting) after Step 1 discovers which genre keys
# appear in the location's affinity-ranked restaurant sample.
_CUISINE_GENRE_MAP = {
    # key               display_name        search_queries                       all_genre_keys
    "american":       ("American",          ["american restaurant", "burger steakhouse grill"],
                       {"american", "american_new", "steak_house", "burger", "barbecue", "diner"}),
    "italian":        ("Italian",           ["italian restaurant", "pizza pasta trattoria"],
                       {"italian", "pizza", "neapolitan"}),
    "mexican":        ("Mexican",           ["mexican restaurant", "taqueria tacos"],
                       {"mexican", "tex_mex", "taqueria"}),
    "japanese":       ("Japanese / Sushi",  ["japanese restaurant", "sushi ramen"],
                       {"japanese", "sushi", "sushi_bar", "ramen", "izakaya"}),
    "sushi":          ("Japanese / Sushi",  ["sushi restaurant", "japanese restaurant"],
                       {"japanese", "sushi", "sushi_bar", "ramen", "izakaya"}),
    "sushi_bar":      ("Japanese / Sushi",  ["sushi restaurant", "japanese restaurant"],
                       {"japanese", "sushi", "sushi_bar", "ramen", "izakaya"}),
    "chinese":        ("Chinese",           ["chinese restaurant", "dim sum"],
                       {"chinese", "dim_sum", "cantonese", "szechuan", "sichuan"}),
    "indian":         ("Indian",            ["indian restaurant", "curry tandoori"],
                       {"indian", "north_indian", "south_indian"}),
    "north_indian":   ("Indian",            ["indian restaurant", "curry tandoori"],
                       {"indian", "north_indian", "south_indian"}),
    "south_indian":   ("Indian",            ["indian restaurant", "curry tandoori"],
                       {"indian", "north_indian", "south_indian"}),
    "thai":           ("Thai",              ["thai restaurant"],
                       {"thai"}),
    "korean":         ("Korean",            ["korean restaurant", "korean bbq"],
                       {"korean", "korean_barbecue"}),
    "korean_barbecue":("Korean",            ["korean restaurant", "korean bbq"],
                       {"korean", "korean_barbecue"}),
    "mediterranean":  ("Mediterranean",     ["mediterranean restaurant", "greek lebanese"],
                       {"mediterranean", "greek", "lebanese", "middle_eastern", "turkish"}),
    "greek":          ("Mediterranean",     ["mediterranean restaurant", "greek restaurant"],
                       {"mediterranean", "greek", "lebanese", "middle_eastern", "turkish"}),
    "vietnamese":     ("Vietnamese",        ["vietnamese restaurant", "pho banh mi"],
                       {"vietnamese", "pho"}),
    "ethiopian":      ("Ethiopian",         ["ethiopian restaurant", "east african restaurant"],
                       {"ethiopian", "east_african"}),
    "east_african":   ("Ethiopian",         ["ethiopian restaurant", "east african restaurant"],
                       {"ethiopian", "east_african"}),
    "french":         ("French",            ["french restaurant bistro", "brasserie"],
                       {"french", "bistro", "brasserie"}),
    "seafood":        ("Seafood",           ["seafood restaurant", "fish restaurant"],
                       {"seafood", "fish_and_chips", "oyster_bar"}),
    "steak_house":    ("Steakhouse",        ["steakhouse", "steak restaurant"],
                       {"steak_house", "american"}),
    "pizza":          ("Pizza",             ["pizza restaurant"],
                       {"pizza", "italian", "neapolitan"}),
    "ramen":          ("Japanese / Sushi",  ["ramen restaurant", "japanese restaurant"],
                       {"japanese", "sushi", "sushi_bar", "ramen", "izakaya"}),
}

# Genre keys that are eating occasions, place types, or service modes — not cuisines.
# These are filtered out of Step 1 results before doing supply analysis.
_NON_CUISINE_GENRES = {
    "restaurant", "bar", "bar_grill", "cocktail_bar", "wine_bar", "sports_bar",
    "family", "brunch", "breakfast", "lunch", "dinner", "buffet", "takeout",
    "delivery", "cafe", "coffee_shop", "espresso_bar", "tea_house", "bakery",
    "pastry_shop", "dessert_shop", "ice_cream", "non_vegetarian", "vegetarian",
    "vegan", "gluten_free", "banquet_hall", "food_court", "live_music_venue",
    "event_venue", "new_american", "asian", "diner", "fast_food", "food_truck",
    "catering", "gastropub", "pub",
}

# Back-compat: keep _CUISINE_PROFILES as a flat list for get_cuisine_places()
_CUISINE_PROFILES = [
    (k, v[0], v[1], v[2])
    for k, v in _CUISINE_GENRE_MAP.items()
    if k not in {"sushi", "sushi_bar", "north_indian", "south_indian",
                 "korean_barbecue", "greek", "east_african",
                 "ramen", "steak_house", "pizza"}
]


def _has_cuisine_genre(entity_tags, genre_keys):
    """Return True if the entity's Qloo tags classify it under one of the given cuisine genre keys.

    Handles both tag formats returned by different Qloo endpoints:
      /search:       urn:tag:genre:restaurant:{key}        / urn:tag:category:{key}_restaurant
      /v2/insights:  urn:tag:genre:place:restaurant:{key}  / urn:tag:category:place:{key}_restaurant
    """
    for tag in entity_tags:
        tid = tag.get("tag_id") or tag.get("id", "")
        for k in genre_keys:
            if (f":genre:restaurant:{k}" in tid
                    or f":genre:place:restaurant:{k}" in tid
                    or f":category:{k}_restaurant" in tid
                    or f":category:place:{k}_restaurant" in tid):
                return True
    return False


def analyze_cuisine_voids(location_query, lat, lon, location_mode="locality", radius_m=16093,
                          city="", state=""):
    """
    Two-step cuisine void analysis using lat/lon + radius throughout.

    Step 1 — Demand discovery.
      Sample restaurants within max(user_radius, 5 mi) across 4 popularity tiers
      (filter.popularity.max = 1.0 / 0.75 / 0.5 / 0.25) with a medium location signal.
      Dedupe by entity_id, tally cuisine genre tag appearances. Top 12 by count = demand
      ranking for this area.

    Step 2 — Supply check + progressive nearest-finder.
      For each top cuisine, count supply within the user's exact radius. If zero, expand
      progressively (1 mi → 5 mi → 10 → 15 → 20 …) until a venue is found, then compute
      haversine distance to report the nearest option.

    Always uses POINT(lon lat) + radius — locality mode simply uses the locality centroid.
    """
    _MI_TO_M = 1609.34

    # Step 1 uses at least 5 miles so the sample is large enough to tally cuisines
    step1_radius_m = max(radius_m, 5 * _MI_TO_M)

    step1_params = {
        "filter.type":             "urn:entity:place",
        "filter.tags":             "urn:tag:genre:place:restaurant",
        "filter.location":         f"POINT({lon} {lat})",
        "filter.location.radius":  int(step1_radius_m),
        "signal.location":         f"POINT({lon} {lat})",
        "signal.location.radius":  int(step1_radius_m),
        "signal.location.weight":  "medium",
        "take":                    50,
    }

    seen_ids:     set  = set()
    demand_count: dict = {}   # display_name -> appearances in sample

    for pop_max in [1.0, 0.75, 0.5, 0.25]:
        try:
            data = _get(f"{_BASE}/v2/insights",
                        {**step1_params, "filter.popularity.max": pop_max})
        except Exception as ex:
            print(f"Cuisine step1 error (pop_max={pop_max}): {ex}")
            continue
        for e in data.get("results", {}).get("entities", []):
            eid = e.get("entity_id", "")
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            for tag in e.get("tags", []):
                tid = tag.get("id", "") or tag.get("tag_id", "")
                if ":genre:place:restaurant:" in tid:
                    key = tid.split(":genre:place:restaurant:")[-1]
                    if key and key not in _NON_CUISINE_GENRES and key in _CUISINE_GENRE_MAP:
                        display = _CUISINE_GENRE_MAP[key][0]
                        demand_count[display] = demand_count.get(display, 0) + 1

    top_cuisines  = sorted(demand_count, key=lambda d: -demand_count[d])[:12]
    total_sampled = len(seen_ids)
    print(f"Step 1: sampled {total_sampled} restaurants across "
          f"{step1_radius_m/1609:.1f} mi, found {len(demand_count)} cuisine types")

    # Build per-display-name genre key set (union of all aliases)
    _canonical: dict = {}
    _genre_keys: dict = {}
    for gk, (display, _queries, genre_keys) in _CUISINE_GENRE_MAP.items():
        if display not in _canonical:
            _canonical[display] = gk
            _genre_keys[display] = set(genre_keys)
        else:
            _genre_keys[display].update(genre_keys)

    # Progressive radius schedule: user radius, then 1→5→10→15→20… mi
    _expansion_mi = [1, 5, 10, 15, 20, 25, 30, 40, 50]
    initial_mi    = radius_m / _MI_TO_M

    def _fetch_at_radius(filter_tags, r_m):
        return _get(f"{_BASE}/v2/insights", {
            "filter.type":            "urn:entity:place",
            "filter.tags":            filter_tags,
            "filter.location":        f"POINT({lon} {lat})",
            "filter.location.radius": int(r_m),
            "take": 50,
        })

    def _nearest(entities):
        """Return the name of the first (highest-ranked) venue in the expanded results."""
        for e in entities:
            name = e.get("name", "")
            if name:
                return name
        return None

    def _make_places(entities):
        places = []
        for e in entities[:20]:
            props   = e.get("properties") or {}
            geocode = props.get("geocode") or {}
            places.append({
                "name":     e.get("name", ""),
                "address":  props.get("address", ""),
                "city":     geocode.get("city", ""),
                "state":    geocode.get("admin1_region", ""),
                "affinity": None,
                "local":    True,
            })
        return places

    def count_supply(display_name):
        canonical_key  = _canonical[display_name]
        all_genre_keys = _genre_keys[display_name]
        tag_id         = f"urn:tag:cuisine:qloo:{canonical_key}"
        filter_tags    = ",".join(
            f"urn:tag:genre:place:restaurant:{k}" for k in sorted(all_genre_keys)
        )

        # Check supply at the user's radius
        try:
            data     = _fetch_at_radius(filter_tags, radius_m)
            entities = data.get("results", {}).get("entities", [])
        except Exception as ex:
            print(f"Supply error for {display_name}: {ex}")
            entities = []

        supply_count       = len(entities)
        nearest_venue      = None
        found_at_radius_mi = None

        if supply_count == 0:
            # Progressive expansion to find nearest
            for exp_mi in _expansion_mi:
                if exp_mi <= initial_mi:
                    continue
                try:
                    exp_data     = _fetch_at_radius(filter_tags, exp_mi * _MI_TO_M)
                    exp_entities = exp_data.get("results", {}).get("entities", [])
                except Exception:
                    continue
                if exp_entities:
                    nearest_venue      = _nearest(exp_entities)
                    found_at_radius_mi = exp_mi
                    entities           = exp_entities   # use these for the place list
                    break

        # Status assigned in post-processing; placeholder for void cases only
        if supply_count == 0 and nearest_venue is None:
            status, status_class = "Cuisine Void", "cuisine-void"
        elif supply_count == 0:
            status, status_class = "Near Void", "near-void"
        else:
            status, status_class = None, None   # resolved below

        return {
            "cuisine":             display_name,
            "tag_id":              tag_id,
            "demand_count":        demand_count.get(display_name, 0),
            "supply_count":        supply_count,
            "nearest_venue":       nearest_venue,
            "found_at_radius_mi":  found_at_radius_mi,
            "cuisine_affinity":    None,
            "distribution_share":  None,         # resolved below
            "status":              status,
            "status_class":        status_class,
            "places":              _make_places(entities),
        }

    results = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(count_supply, dn): dn for dn in top_cuisines}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r is not None:
                    results.append(r)
            except Exception as ex:
                print(f"Cuisine supply error: {ex}")

    # ── Post-processing: distribution-based classification ────────────────────
    # For cuisines with supply > 0, compute each one's share of the total local
    # restaurant mix, then compare demand rank and distribution share to their
    # respective medians to place each cuisine in the demand/supply matrix:
    #
    #   High demand + Low distribution  → Underserved   (opportunity)
    #   High demand + High distribution → Well Represented
    #   Low demand  + Low distribution  → Niche          (small but balanced)
    #   Low demand  + High distribution → Well Represented (not actionable)

    supplied = [r for r in results if r["supply_count"] > 0]

    if supplied:
        total_supply = sum(r["supply_count"] for r in supplied)
        for r in supplied:
            r["distribution_share"] = r["supply_count"] / total_supply

        shares  = [r["distribution_share"] for r in supplied]
        demands = [r["demand_count"]        for r in supplied]

        # Use sorted medians (works for even and odd lengths)
        median_share  = sorted(shares) [len(shares)  // 2]
        median_demand = sorted(demands)[len(demands) // 2]

        for r in supplied:
            above_demand = r["demand_count"]        >= median_demand
            above_dist   = r["distribution_share"]  >= median_share
            if above_demand and not above_dist:
                r["status"], r["status_class"] = "Underserved",      "underserved"
            elif not above_demand and not above_dist:
                r["status"], r["status_class"] = "Niche",            "niche"
            elif not above_demand and above_dist:
                r["status"], r["status_class"] = "Saturated",        "saturated"
            else:
                r["status"], r["status_class"] = "Well Represented", "present"

        print(f"Medians — demand: {median_demand:.1f}, distribution: {median_share:.3f}")

    STATUS_ORDER = {
        "Cuisine Void": 0, "Near Void": 1,
        "Underserved": 2, "Niche": 3, "Well Represented": 4, "Saturated": 5,
    }
    results.sort(key=lambda x: (STATUS_ORDER.get(x["status"], 9), x["supply_count"]))
    return results, total_sampled


def get_cuisine_places(cuisine_tag_id, location_query, lat, lon,
                       location_mode="locality", radius_m=16093):
    """
    Fetch cuisine-classified places for a specific cuisine tag in a locality.

    Uses signal.interests.tags as an affinity/location signal to surface
    candidate places, then filters by Qloo's own genre/category tags to keep
    only places that are actually classified as that cuisine type.

    This correctly handles restaurants with non-descriptive names (e.g. "Demera
    Restaurant" has urn:tag:genre:restaurant:ethiopian but no "ethiopian" in name).

    NOTE: This query takes ~16 s on Qloo's staging API; call on-demand only.
    """
    # Look up the genre keys for this cuisine
    cuisine_key = cuisine_tag_id.split(":")[-1]
    genre_keys: set = set()
    for key, _name, _queries, gks in _CUISINE_PROFILES:
        if key == cuisine_key:
            genre_keys = gks
            break

    params = {
        "filter.type":            "urn:entity:place",
        "signal.interests.tags":  cuisine_tag_id,
        "signal.location.weight": "very_high",
        "take":                   50,
    }
    if location_mode == "address":
        params["signal.location"]        = f"POINT({lon} {lat})"
        params["signal.location.radius"] = int(radius_m)
    else:
        params["signal.location.query"] = location_query

    import ssl as _ssl, certifi as _certifi, urllib.request as _ur, urllib.parse as _up
    _ctx = _ssl.create_default_context(cafile=_certifi.where())

    url = f"{_BASE}/v2/insights?{_up.urlencode(params)}"
    req = _ur.Request(url, headers=_HEADERS)
    try:
        with _ur.urlopen(req, context=_ctx, timeout=30) as res:
            data = json.loads(res.read())
    except Exception as e:
        print(f"get_cuisine_places error for {cuisine_tag_id}: {e}")
        return []

    places = []
    for e in data.get("results", {}).get("entities", []):
        # Filter to places Qloo has classified as this cuisine type via genre/category tags.
        if genre_keys and not _has_cuisine_genre(e.get("tags", []), genre_keys):
            continue
        props   = e.get("properties") or {}
        geocode = props.get("geocode") or {}
        places.append({
            "name":     e.get("name", ""),
            "address":  props.get("address", ""),
            "city":     geocode.get("city", ""),
            "state":    geocode.get("admin1_region", ""),
            "affinity": round(e.get("query", {}).get("affinity", 0), 4),
            "local":    False,
        })
    return places


def search_entities(query, take=6):
    params = {"query": query, "take": take}
    data = _get(f"{_BASE}/search", params)
    return [
        {
            "id":      e["entity_id"],
            "name":    e["name"],
            "subtype": e.get("subtype") or (e.get("types") or [""])[0],
            "kind":    "entity",
        }
        for e in data.get("results", [])
    ]


def _tag_type_label(tag_id):
    """Derive a human-readable type label from a Qloo tag URN.

    Examples:
      urn:tag:cuisine:qloo:italian          → 'cuisine'
      urn:tag:genre:place:restaurant:italian → 'restaurant'
      urn:tag:genre:music:italian           → 'music'
      urn:tag:amenity:place:italian         → 'place'
      urn:tag:genre:place:hotel:italian     → 'hotel'
      urn:tag:interest:qloo:outdoors        → 'interest'
    """
    parts = tag_id.split(":")
    # parts[0]='urn', parts[1]='tag', parts[2]=category, ...
    if len(parts) < 3:
        return ""
    category = parts[2]
    if category == "genre" and len(parts) > 3:
        subcat = parts[3]                        # 'place', 'music', 'tv', …
        if subcat == "place" and len(parts) > 4:
            return parts[4]                      # 'restaurant', 'hotel', …
        return subcat
    if category in ("cuisine", "interest", "amenity"):
        return category
    return category


def search_tags(query, take=6):
    params = {"filter.query": query, "take": take}
    data = _get(f"{_BASE}/v2/tags", params)
    return [
        {
            "id":      t["id"],
            "name":    t.get("name", t["id"].split(":")[-1].replace("_", " ").title()),
            "subtype": _tag_type_label(t["id"]),
            "kind":    "tag",
        }
        for t in data.get("results", {}).get("tags", [])
    ]

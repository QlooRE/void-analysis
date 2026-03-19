import re
import ssl
import certifi
import urllib.request
import urllib.parse
import json

_ssl_ctx   = ssl.create_default_context(cafile=certifi.where())
_BASE      = "https://staging.api.qloo.com"
_API_KEY   = "U1HM0OelGf8tRZxxk1yC32NoQfbWBnbd66EI6eld"
_HEADERS   = {"x-api-key": _API_KEY}

# ISO 2-letter codes for common country names returned by Qloo
_COUNTRY_CODES = {
    "united states of america": "US",
    "united states":             "US",
    "united kingdom":            "GB",
    "canada":                    "CA",
    "australia":                 "AU",
    "germany":                   "DE",
    "france":                    "FR",
    "spain":                     "ES",
    "italy":                     "IT",
    "japan":                     "JP",
    "brazil":                    "BR",
    "mexico":                    "MX",
}


def _centroid_from_wkt(wkt):
    """Return (lat, lon) approximate centroid from a WKT POLYGON or MULTIPOLYGON."""
    pairs = re.findall(r'(-?\d+\.?\d*)\s+(-?\d+\.?\d*)', wkt)
    if not pairs:
        return None, None
    lons = [float(p[0]) for p in pairs]
    lats = [float(p[1]) for p in pairs]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _parse_ancestors(ancestors):
    """Extract city, state, country_code from Qloo locality ancestors list."""
    city = state = country_code = ""
    for a in ancestors:
        place = a.get("place", "")
        name  = a.get("name", "")
        level = a.get("admin_level", 0)
        if place in ("city", "town", "municipality") or level == 5:
            city = name
        elif place == "state" or level == 4:
            state = name
        elif place == "country" or level == 2:
            country_code = _COUNTRY_CODES.get(name.lower(), "US")
    return city, state, country_code


def geocode(query, limit=5):
    """
    Resolve a location query via Qloo's locality catalog.
    Returns list of {display_name, lat, lon, city, state, country_code, locality_id, qloo_name}.
    Falls back to Nominatim if Qloo returns nothing.
    """
    try:
        params = urllib.parse.urlencode({"query": query, "types": "urn:entity:locality", "take": limit})
        req = urllib.request.Request(f"{_BASE}/search?{params}", headers=_HEADERS)
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=10) as res:
            data = json.loads(res.read())

        results = []
        for e in data.get("results", []):
            props     = e.get("properties", {})
            ancestors = props.get("ancestors", [])
            city, state, country_code = _parse_ancestors(ancestors)

            lat, lon = _centroid_from_wkt(props.get("boundaries", ""))
            if lat is None:
                continue

            # Build a readable display name
            parts = [e["name"]]
            if city and city != e["name"]:
                parts.append(city)
            if state:
                parts.append(state)
            if country_code:
                parts.append(country_code)

            results.append({
                "display_name": ", ".join(parts),
                "qloo_name":    e["name"],
                "locality_id":  e["entity_id"],
                "lat":          round(lat, 6),
                "lon":          round(lon, 6),
                "city":         city,
                "state":        state,
                "country_code": country_code,
            })

        if results:
            return results

    except Exception as e:
        print(f"Qloo locality search error: {e}")

    # Fallback: Nominatim
    return _nominatim_geocode(query, limit)


_addr_cache: dict = {}


def geocode_address(query, limit=5):
    """Geocode a street address or landmark via Nominatim (better for addresses than Qloo)."""
    key = query.strip().lower()
    if key in _addr_cache:
        return _addr_cache[key]
    results = _nominatim_geocode(query, limit)
    _addr_cache[key] = results
    return results


def _nominatim_geocode(query, limit=5):
    _NOMINATIM  = "https://nominatim.openstreetmap.org/search"
    _NOM_HDRS   = {"User-Agent": "VoidAnalysisApp/1.0"}
    params = {"q": query, "format": "json", "limit": limit, "addressdetails": "1"}
    url = f"{_NOMINATIM}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_NOM_HDRS)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=10) as res:
            data = json.loads(res.read())
        results = []
        for r in data:
            addr = r.get("address", {})
            city = (
                addr.get("city") or addr.get("town") or
                addr.get("village") or addr.get("municipality") or ""
            )
            results.append({
                "display_name": r["display_name"],
                "qloo_name":    city or r["display_name"].split(",")[0].strip(),
                "locality_id":  None,
                "lat":          float(r["lat"]),
                "lon":          float(r["lon"]),
                "city":         city,
                "state":        addr.get("state", ""),
                "country_code": addr.get("country_code", "us").upper(),
            })
        return results
    except Exception as e:
        print(f"Nominatim geocode error: {e}")
        return []

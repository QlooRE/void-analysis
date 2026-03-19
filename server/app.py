from flask import Flask, jsonify, render_template, request
from services.geo import geocode, geocode_address
from services.qloo import analyze_voids, analyze_cuisine_voids, get_cuisine_places, search_entities, search_tags

app = Flask(__name__)

_MI_TO_M  = 1609.34
_KM_TO_M  = 1000.0
_DEFAULT_RADIUS_M = 8047   # 5 miles


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/geocode-suggest")
def geocode_suggest():
    q    = request.args.get("q", "").strip()
    mode = request.args.get("mode", "locality")   # locality | address
    if len(q) < 3:
        return jsonify([])
    try:
        if mode == "address":
            return jsonify(geocode_address(q, limit=5))
        else:
            return jsonify(geocode(q, limit=5))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/search")
def search():
    q    = request.args.get("q", "").strip()
    kind = request.args.get("kind", "entity")
    if not q:
        return jsonify([])
    try:
        if kind == "tag":
            return jsonify(search_tags(q))
        else:
            return jsonify(search_entities(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/analyze")
def analyze():
    body           = request.get_json(force=True)
    location       = body.get("location") or {}
    age_group_keys = body.get("age_groups", [])
    entity_signals = body.get("entity_signals", [])
    tag_signals    = body.get("tag_signals", [])
    radius_m       = float(body.get("radius_m", _DEFAULT_RADIUS_M))

    # Accept full location object or plain string
    if isinstance(location, str):
        location = location.strip()
        if not location:
            return jsonify({"error": "Location is required"}), 400
        geo_results = geocode_address(location, limit=1)
        if not geo_results:
            return jsonify({"error": f"Could not geocode '{location}'"}), 400
        loc = geo_results[0]
    elif isinstance(location, dict) and location.get("lat"):
        loc = location
    else:
        return jsonify({"error": "Location is required"}), 400

    geo_context = {
        "city":         loc.get("city", ""),
        "state":        loc.get("state", ""),
        "metro":        "",
        "country_code": loc.get("country_code", "US").lower(),
    }

    brands, skipped = analyze_voids(
        loc.get("qloo_name") or loc.get("display_name", ""),
        loc["lat"], loc["lon"],
        age_group_keys, entity_signals, tag_signals,
        geo_context,
        location_mode='address',
        radius_m=radius_m,
    )

    if not brands:
        return jsonify({"error": "No brands returned. Try a different location or signals."}), 404

    summary = {"Taste Signal, No Presence": 0, "Taste Signal, Regional Gap": 0, "Taste Signal, Distant Presence": 0, "Taste Signal, Local Gap": 0, "Taste-Aligned": 0}
    for b in brands:
        summary[b["status"]] = summary.get(b["status"], 0) + 1

    return jsonify({
        "location":        loc,
        "location_mode":   'address',
        "brands":          brands,
        "summary":         summary,
        "skipped_digital": skipped,
        "radius_m":        radius_m,
    })


@app.post("/api/analyze-cuisine")
def analyze_cuisine():
    body     = request.get_json(force=True)
    location = body.get("location") or {}
    radius_m = float(body.get("radius_m", 16093))  # default 10 miles

    if isinstance(location, dict) and location.get("lat"):
        loc = location
    else:
        return jsonify({"error": "Location is required"}), 400

    cuisines, total_sampled = analyze_cuisine_voids(
        loc.get("qloo_name") or loc.get("display_name", ""),
        loc["lat"], loc["lon"],
        location_mode='address',
        radius_m=radius_m,
        city=loc.get("city", ""),
        state=loc.get("state", ""),
    )

    if not cuisines:
        return jsonify({"error": "No cuisine data returned. Try a different location."}), 404

    return jsonify({
        "location":       loc,
        "location_mode":  'address',
        "radius_m":       radius_m,
        "cuisines":       cuisines,
        "total_sampled":  total_sampled,
    })


@app.get("/api/cuisine-places")
def cuisine_places():
    """
    On-demand: fetch Qloo tag-validated places for a single cuisine in a locality.
    Called lazily when the user expands a cuisine card.
    """
    tag_id        = request.args.get("tag_id", "").strip()
    location_query = request.args.get("location_query", "").strip()
    lat           = request.args.get("lat", type=float)
    lon           = request.args.get("lon", type=float)
    city          = request.args.get("city", "").strip().lower()
    location_mode = request.args.get("location_mode", "locality")
    radius_m      = request.args.get("radius_m", 16093, type=float)

    # For locality mode, loc.city is often empty (Chicago is the locality itself).
    # Fall back to the first token of location_query (e.g. "Chicago, Illinois, US" → "chicago").
    if not city and location_query:
        city = location_query.split(",")[0].strip().lower()

    if not tag_id or lat is None or lon is None:
        return jsonify({"error": "tag_id, lat, lon required"}), 400

    try:
        places = get_cuisine_places(
            tag_id, location_query, lat, lon,
            location_mode=location_mode, radius_m=radius_m,
        )
        # Mark which places are local to this city
        for p in places:
            p["local"] = (p["city"].lower() == city) if city else False

        return jsonify({"places": places, "tag_id": tag_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/geocode-venues")
def geocode_venues():
    body = request.get_json(force=True)
    addresses = body.get("addresses", [])[:10]  # max 10
    from services.geo import geocode_address as _geocode_address
    import time
    results = []
    for addr in addresses:
        if not addr or not addr.strip():
            results.append(None)
            continue
        geo = _geocode_address(addr.strip(), limit=1)
        results.append({"lat": geo[0]["lat"], "lon": geo[0]["lon"]} if geo else None)
        time.sleep(1.1)  # Nominatim rate limit
    return jsonify(results)


if __name__ == "__main__":
    app.run(port=3003, debug=True)

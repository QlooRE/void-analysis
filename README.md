# Void Analysis

Retail demand vs. physical presence — powered by [Qloo Taste AI™](https://qloo.com).

Given an address and radius, Void Analysis identifies where consumer demand exists but physical retail or dining supply does not — surfacing actionable gaps for leasing, expansion, and pop-up strategy.

---

## What it does

### Brand Void Analysis
Fetches brands the local audience has affinity for (via Qloo's taste graph), filters to retail and dining, then checks whether each brand has a physical presence nearby. Brands are classified by proximity:

| Status | Meaning |
|---|---|
| **Pop-up Candidate** | No physical locations found anywhere — likely DTC or digitally native |
| **Near Void** | Has physical presence, but none in this region |
| **Available** | Located within this state (~25–50 mi away) |
| **Underserved** | In the metro area but not at this specific location |
| **Present** | Already operating in this city |

Brands are sampled across four popularity bands (`filter.popularity.max = 1.0 / 0.75 / 0.5 / 0.25`) to surface a mix of mainstream and niche brands rather than only globally popular names.

### Cuisine Void Analysis
A two-step pipeline that identifies which cuisine types are in demand but undersupplied within the search radius.

**Step 1 — Demand discovery:** Samples restaurants across 4 popularity tiers within the radius, tallies cuisine genre tag appearances, and ranks the top 12 cuisines by local demand signal.

**Step 2 — Supply check:** For each top cuisine, counts how many matching venues exist within the user's exact radius. If zero, progressively expands (1 → 5 → 10 → 15 → 20 → 25 → 30 → 40 → 50 mi) to find the nearest option.

Cuisines with supply are classified using a 4-quadrant demand/distribution matrix:

| Status | Meaning |
|---|---|
| **Cuisine Void** | No restaurants of this type found within 50 mi |
| **Near Void** | None within radius — nearest found just beyond it |
| **Underserved** | Above-median demand, below-median distribution share — real opportunity |
| **Niche** | Below-median demand and distribution — small but balanced |
| **Well Represented** | Demand and supply are proportionate |
| **Saturated** | Above-median distribution, below-median demand — oversupplied |

---

## Stack

- **Backend:** Python / Flask
- **Taste API:** [Qloo Insights API](https://qloo.com) (`/v2/insights`, `/search`, `/v2/tags`)
- **Geocoding:** Nominatim (OpenStreetMap)
- **Frontend:** Vanilla JS + [Leaflet](https://leafletjs.com) (no framework)
- **Tests:** pytest (unit + integration)

---

## Setup

### Prerequisites
- Python 3.10+
- A Qloo API key

### Install

```bash
cd server
pip install -r requirements.txt
```

### Configure

Set your Qloo API key as an environment variable:

```bash
export QLOO_API_KEY=your_key_here
```

Or create a `.env` file (gitignored):

```
QLOO_API_KEY=your_key_here
```

### Run

```bash
cd server
python app.py
```

App runs at `http://localhost:3003`.

---

## Tests

```bash
cd server
pip install pytest

# Unit tests only (no API calls)
pytest tests/test_classification.py

# Full suite including integration tests (requires QLOO_API_KEY)
pytest --run-integration
```

---

## Project structure

```
server/
├── app.py                      # Flask routes
├── services/
│   ├── qloo.py                 # Qloo API client + void analysis logic
│   └── geo.py                  # Nominatim geocoding
├── static/
│   ├── app.js                  # Frontend (map, UI, rendering)
│   └── style.css
├── templates/
│   └── index.html
└── tests/
    ├── test_classification.py  # Unit tests (haversine, cuisine map, status matrix)
    └── test_cuisine_integration.py  # Integration tests (real API)
```

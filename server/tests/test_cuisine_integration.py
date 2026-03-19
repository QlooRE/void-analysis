"""
Integration tests for cuisine void analysis.
These hit the real Qloo API — run with: pytest -m integration -v
"""
import pytest
CHICAGO_LAT   = 41.886881
CHICAGO_LON   = -87.684102
CHICAGO_QUERY = "Chicago, Illinois, US"

pytestmark = pytest.mark.integration

@pytest.fixture(scope="module")
def chicago_1mi():
    from services.qloo import analyze_cuisine_voids
    results, total = analyze_cuisine_voids(
        CHICAGO_QUERY, CHICAGO_LAT, CHICAGO_LON,
        location_mode='address', radius_m=1609, city='Chicago'
    )
    return results, total

@pytest.fixture(scope="module")
def chicago_5mi():
    from services.qloo import analyze_cuisine_voids
    results, total = analyze_cuisine_voids(
        CHICAGO_QUERY, CHICAGO_LAT, CHICAGO_LON,
        location_mode='address', radius_m=8047, city='Chicago'
    )
    return results, total

class TestChicago1MileRadius:
    def test_returns_results(self, chicago_1mi):
        results, total = chicago_1mi
        assert len(results) > 0
        assert total > 50  # step1 5mi floor should sample plenty

    def test_all_statuses_valid(self, chicago_1mi):
        valid = {"Cuisine Void", "Near Void", "Underserved", "Well Represented"}
        for r in chicago_1mi[0]:
            assert r["status"] in valid

    def test_vietnamese_is_near_void_or_void(self, chicago_1mi):
        """Vietnamese has demand signal but none within 1mi of River North."""
        results, _ = chicago_1mi
        viet = next((r for r in results if r["cuisine"] == "Vietnamese"), None)
        if viet:  # only assert if Vietnamese appeared in top 12 demand
            assert viet["status"] in ("Near Void", "Cuisine Void")
            assert viet["supply_count"] == 0

    def test_near_void_has_nearest_venue(self, chicago_1mi):
        """Any Near Void must include nearest_venue and found_at_radius_mi."""
        for r in chicago_1mi[0]:
            if r["status"] == "Near Void":
                assert r["nearest_venue"] is not None
                assert r["found_at_radius_mi"] is not None
                assert r["found_at_radius_mi"] > 1  # beyond initial 1mi radius

    def test_american_is_well_represented(self, chicago_1mi):
        """American cuisine should have strong supply in River North."""
        results, _ = chicago_1mi
        american = next((r for r in results if r["cuisine"] == "American"), None)
        if american:
            assert american["status"] == "Well Represented"
            assert american["supply_count"] > 3

    def test_demand_count_positive_for_all(self, chicago_1mi):
        """All returned cuisines should have appeared in Step 1 sample."""
        for r in chicago_1mi[0]:
            assert r["demand_count"] >= 1

    def test_places_capped_at_20(self, chicago_1mi):
        for r in chicago_1mi[0]:
            assert len(r["places"]) <= 20

    def test_sorted_voids_first(self, chicago_1mi):
        order = {"Cuisine Void": 0, "Near Void": 1, "Underserved": 2, "Well Represented": 3}
        statuses = [order[r["status"]] for r in chicago_1mi[0]]
        assert statuses == sorted(statuses)

class TestChicago5MileRadius:
    def test_more_supply_than_1mi(self, chicago_1mi, chicago_5mi):
        """5mi radius should have >= supply count vs 1mi for all cuisines."""
        r1 = {r["cuisine"]: r["supply_count"] for r in chicago_1mi[0]}
        r5 = {r["cuisine"]: r["supply_count"] for r in chicago_5mi[0]}
        for cuisine in set(r1) & set(r5):
            assert r5[cuisine] >= r1[cuisine], f"{cuisine}: 5mi supply < 1mi supply"

    def test_fewer_voids_at_larger_radius(self, chicago_1mi, chicago_5mi):
        void_statuses = {"Cuisine Void", "Near Void"}
        voids_1mi = sum(1 for r in chicago_1mi[0] if r["status"] in void_statuses)
        voids_5mi = sum(1 for r in chicago_5mi[0] if r["status"] in void_statuses)
        assert voids_5mi <= voids_1mi

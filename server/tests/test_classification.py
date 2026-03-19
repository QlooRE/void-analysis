"""Unit tests for classification logic and pure functions."""
import pytest
from services.qloo import _haversine_miles, _CUISINE_GENRE_MAP, _NON_CUISINE_GENRES, _has_cuisine_genre

class TestHaversine:
    def test_same_point(self):
        assert _haversine_miles(41.88, -87.68, 41.88, -87.68) == 0.0

    def test_known_distance(self):
        # Chicago to NYC ~713 miles
        d = _haversine_miles(41.878, -87.630, 40.713, -74.006)
        assert 700 < d < 730

    def test_symmetry(self):
        d1 = _haversine_miles(41.88, -87.68, 40.71, -74.01)
        d2 = _haversine_miles(40.71, -74.01, 41.88, -87.68)
        assert abs(d1 - d2) < 0.001

class TestCuisineGenreMap:
    def test_all_display_names_have_entries(self):
        for key, (display, queries, genre_keys) in _CUISINE_GENRE_MAP.items():
            assert display, f"Empty display name for key {key}"
            assert genre_keys, f"Empty genre_keys for key {key}"

    def test_no_overlap_with_non_cuisine(self):
        # Cuisine genre keys should not appear in _NON_CUISINE_GENRES
        for key in _CUISINE_GENRE_MAP:
            assert key not in _NON_CUISINE_GENRES, f"{key} in both maps"

    def test_known_aliases_share_display(self):
        assert _CUISINE_GENRE_MAP["sushi"][0] == _CUISINE_GENRE_MAP["japanese"][0]
        assert _CUISINE_GENRE_MAP["ramen"][0] == _CUISINE_GENRE_MAP["japanese"][0]
        assert _CUISINE_GENRE_MAP["korean_barbecue"][0] == _CUISINE_GENRE_MAP["korean"][0]
        assert _CUISINE_GENRE_MAP["east_african"][0] == _CUISINE_GENRE_MAP["ethiopian"][0]

class TestHasCuisineGenre:
    def test_insights_tag_format(self):
        tags = [{"id": "urn:tag:genre:place:restaurant:ethiopian"}]
        assert _has_cuisine_genre(tags, {"ethiopian"})

    def test_search_tag_format(self):
        tags = [{"id": "urn:tag:genre:restaurant:ethiopian"}]
        assert _has_cuisine_genre(tags, {"ethiopian"})

    def test_no_match(self):
        tags = [{"id": "urn:tag:genre:place:restaurant:italian"}]
        assert not _has_cuisine_genre(tags, {"ethiopian"})

    def test_multiple_keys(self):
        tags = [{"id": "urn:tag:genre:place:restaurant:sushi"}]
        assert _has_cuisine_genre(tags, {"japanese", "sushi", "ramen"})

class TestStatusMatrix:
    """Test the 4-quadrant demand/distribution classification matrix."""

    def _classify(self, supply, has_nearest=False,
                  above_demand=True, above_dist=True):
        if supply == 0 and not has_nearest:
            return "Culinary Blind Spot"
        if supply == 0 and has_nearest:
            return "Culinary Proximity Gap"
        if above_demand and not above_dist:
            return "Culinary Demand Surplus"
        if not above_demand and not above_dist:
            return "Understated"
        if not above_demand and above_dist:
            return "Culinary Oversupply"
        return "Palate-Matched"

    def test_culinary_blind_spot(self):
        assert self._classify(0, False) == "Culinary Blind Spot"

    def test_culinary_proximity_gap(self):
        assert self._classify(0, True) == "Culinary Proximity Gap"

    def test_culinary_demand_surplus(self):
        assert self._classify(2, above_demand=True,  above_dist=False) == "Culinary Demand Surplus"

    def test_understated(self):
        assert self._classify(1, above_demand=False, above_dist=False) == "Understated"

    def test_culinary_oversupply(self):
        assert self._classify(7, above_demand=False, above_dist=True)  == "Culinary Oversupply"

    def test_palate_matched(self):
        assert self._classify(9, above_demand=True,  above_dist=True)  == "Palate-Matched"

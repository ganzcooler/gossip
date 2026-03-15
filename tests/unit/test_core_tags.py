"""
Unit tests for app/core/tags.py
"""
import pytest

from app.core import tags as tags_module


class TestTags:
    """Tests for TAGS dictionary."""

    def test_tags_is_dict(self):
        """Test that TAGS is a dictionary."""
        assert isinstance(tags_module.TAGS, dict)

    def test_contains_expected_committee_tags(self):
        """Test that expected committee tags exist."""
        expected_committees = [
            "bau",
            "feuerwehr",
            "jugend",
            "schule",
            "sport",
            "gemeinderat",
            "wirtschaft",
        ]

        for committee in expected_committees:
            assert committee in tags_module.TAGS

    def test_contains_expected_district_tags(self):
        """Test that expected district tags exist."""
        expected_districts = [
            "atzenhausen",
            "dahlenrode",
            "dramfeld",
            "rosdorf",
        ]

        for district in expected_districts:
            assert district in tags_module.TAGS

    def test_tag_values_are_strings(self):
        """Test that all tag values are strings."""
        for key, value in tags_module.TAGS.items():
            assert isinstance(value, str), f"Tag {key} value is not a string"

    def test_tag_keys_are_strings(self):
        """Test that all tag keys are strings."""
        for key in tags_module.TAGS.keys():
            assert isinstance(key, str)

    def test_tag_values_not_empty(self):
        """Test that all tag values are non-empty."""
        for key, value in tags_module.TAGS.items():
            assert len(value) > 0, f"Tag {key} has empty value"

    def test_gemeinderat_tag(self):
        """Test specific gemeinderat tag value."""
        assert tags_module.TAGS["gemeinderat"] == "Gemeinderat"

    def test_bau_umwelt_tag(self):
        """Test specific Bau/Umwelt tag value."""
        assert tags_module.TAGS["bau"] == "Bau, Umwelt, Verkehr"

    def test_schule_tag(self):
        """Test specific Schule tag value."""
        assert tags_module.TAGS["schule"] == "Schule, Bildung"

    def test_number_of_tags(self):
        """Test that expected number of tags exists."""
        # 7 committees + 11 ortsrat = 18 total
        assert len(tags_module.TAGS) == 18

    def test_all_ortsrat_tags(self):
        """Test that all Ortsrat tags exist."""
        districts = ["atzenhausen", "dahlenrode", "dramfeld", "klein_wiershausen",
                     "mengershausen", "lemshausen", "obernjesa", "rosdorf",
                     "sieboldshausen", "settmarshausen", "volkerode"]
        ortsrat_tags = [k for k in tags_module.TAGS.keys() if k in districts]
        assert len(ortsrat_tags) == 11  # 11 districts
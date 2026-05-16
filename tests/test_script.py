"""Tests for script.py"""
import json
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script import (
    NUMBER_REPLACEMENTS,
    SWEDISH_DAYS,
    SWEDISH_MONTHS,
    _dynamic_length_params,
    filter_by_relevance,
    preprocess_script,
    swedish_date,
)


class TestSwedishDate:
    def test_weekday_name(self):
        # 2026-05-18 is a Monday (weekday=0)
        dt = datetime(2026, 5, 18)
        result = swedish_date(dt)
        assert "måndag" in result

    def test_month_name(self):
        dt = datetime(2026, 1, 1)
        result = swedish_date(dt)
        assert "januari" in result

    def test_year_replacement(self):
        dt = datetime(2026, 5, 18)
        result = swedish_date(dt)
        assert "två tusen tjugosex" in result
        assert "2026" not in result

    def test_year_2025_replacement(self):
        dt = datetime(2025, 3, 15)
        result = swedish_date(dt)
        assert "två tusen tjugofem" in result

    def test_format_contains_day_number(self):
        # 2026-05-01 = fredag den första maj
        dt = datetime(2026, 5, 1)
        result = swedish_date(dt)
        assert "första" in result
        assert "maj" in result


class TestPreprocessScript:
    def test_replaces_year(self):
        text = "Det var år 2026 som allt förändrades."
        result = preprocess_script(text)
        assert "2026" not in result
        assert "två tusen tjugosex" in result

    def test_no_change_for_normal_text(self):
        text = "Hej och välkommen till podden."
        result = preprocess_script(text)
        assert result == text

    def test_replaces_multiple_years(self):
        text = "Från 2024 till 2026."
        result = preprocess_script(text)
        assert "2024" not in result
        assert "2026" not in result
        assert "två tusen tjugofyra" in result
        assert "två tusen tjugosex" in result

    def test_all_replacements_present(self):
        for year, spoken in NUMBER_REPLACEMENTS.items():
            result = preprocess_script(year)
            assert spoken in result


class TestDynamicLengthParams:
    def test_slow_day_for_three_or_fewer_articles(self):
        _, _, is_slow = _dynamic_length_params(3, 1300, 1500)
        assert is_slow is True

    def test_slow_day_for_one_article(self):
        _, _, is_slow = _dynamic_length_params(1, 1300, 1500)
        assert is_slow is True

    def test_not_slow_for_four_articles(self):
        _, _, is_slow = _dynamic_length_params(4, 1300, 1500)
        assert is_slow is False

    def test_not_slow_for_six_articles(self):
        _, _, is_slow = _dynamic_length_params(6, 1300, 1500)
        assert is_slow is False

    def test_scaling_for_few_articles(self):
        min_w, max_w, _ = _dynamic_length_params(2, 1300, 1500)
        assert min_w == int(1300 * 0.65)
        assert max_w == int(1500 * 0.65)

    def test_scaling_for_medium_articles(self):
        min_w, max_w, _ = _dynamic_length_params(5, 1300, 1500)
        assert min_w == int(1300 * 0.85)
        assert max_w == int(1500 * 0.85)

    def test_full_scale_for_many_articles(self):
        min_w, max_w, _ = _dynamic_length_params(8, 1300, 1500)
        assert min_w == 1300
        assert max_w == 1500


class TestFilterByRelevance:
    def _make_cfg(self):
        return {
            "openai": {"model": "gpt-4o"},
            "episodes": {
                "ep1": {
                    "relevance_cutoff": 7,
                    "max_articles": 8,
                }
            }
        }

    def _make_articles(self, n: int) -> list:
        return [{"category": "Test", "title": f"Artikel {i}", "summary": "..."} for i in range(n)]

    def test_returns_max_articles_on_api_failure(self):
        articles = self._make_articles(15)
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")
        cfg = self._make_cfg()

        result = filter_by_relevance(articles, cfg, mock_client)
        assert len(result) <= cfg["episodes"]["ep1"]["max_articles"]
        assert result == articles[:8]

    def test_filters_below_cutoff(self):
        articles = self._make_articles(5)
        mock_client = MagicMock()
        scores = [9, 3, 8, 2, 7]  # index 1 and 3 below cutoff=7
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({"scores": scores})
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 10
        mock_client.chat.completions.create.return_value = mock_response
        cfg = self._make_cfg()

        result = filter_by_relevance(articles, cfg, mock_client)
        assert len(result) == 3  # only scores >= 7

    def test_handles_empty_list(self):
        mock_client = MagicMock()
        cfg = self._make_cfg()
        result = filter_by_relevance([], cfg, mock_client)
        assert result == []

    def test_falls_back_to_all_when_all_filtered(self):
        """If all articles score below cutoff, return first max_articles."""
        articles = self._make_articles(5)
        mock_client = MagicMock()
        scores = [1, 2, 3, 1, 2]  # all below cutoff=7
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({"scores": scores})
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 10
        mock_client.chat.completions.create.return_value = mock_response
        cfg = self._make_cfg()

        result = filter_by_relevance(articles, cfg, mock_client)
        assert len(result) <= cfg["episodes"]["ep1"]["max_articles"]
        assert len(result) > 0

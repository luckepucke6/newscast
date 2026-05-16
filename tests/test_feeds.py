"""Tests for feeds.py"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import article_key
from feeds import fetch_articles, fetch_weather


class TestArticleKey:
    def test_same_input_same_hash(self):
        assert article_key("Titel", "https://example.com") == article_key("Titel", "https://example.com")

    def test_case_insensitive(self):
        assert article_key("TITEL", "https://example.com") == article_key("titel", "https://example.com")

    def test_different_input_different_hash(self):
        assert article_key("Titel A", "https://a.com") != article_key("Titel B", "https://b.com")

    def test_url_matters(self):
        assert article_key("Titel", "https://a.com") != article_key("Titel", "https://b.com")

    def test_title_matters(self):
        assert article_key("A", "https://example.com") != article_key("B", "https://example.com")


class TestFetchWeather:
    def test_returns_string_with_temp_on_success(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "current": {
                "temperature_2m": 15.7,
                "weathercode": 0,
            }
        }
        with patch("feeds.requests.get", return_value=mock_resp):
            result = fetch_weather()
        assert "16" in result or "15" in result  # rounded temp
        assert "grader" in result

    def test_returns_empty_string_on_network_error(self):
        with patch("feeds.requests.get", side_effect=Exception("timeout")):
            result = fetch_weather()
        assert result == ""

    def test_returns_empty_string_on_json_error(self):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("bad json")
        with patch("feeds.requests.get", return_value=mock_resp):
            result = fetch_weather()
        assert result == ""


class TestFetchArticles:
    def _make_entry(self, title: str, link: str, summary: str = "") -> MagicMock:
        entry = MagicMock()
        entry.title = title
        entry.get = lambda k, default="": {"link": link, "summary": summary}.get(k, default)
        return entry

    def test_skips_already_seen_articles(self):
        title = "Gammal nyhet"
        url = "https://example.com/old"
        key = article_key(title, url)
        history = {key: datetime.now().isoformat()}

        mock_feed = MagicMock()
        mock_feed.entries = [self._make_entry(title, url)]

        with patch("feeds.feedparser.parse", return_value=mock_feed):
            articles = fetch_articles({"TestFeed": "https://example.com/rss"}, history, max_per_feed=5)

        assert len(articles) == 0

    def test_includes_new_articles(self):
        history = {}
        mock_feed = MagicMock()
        mock_feed.entries = [
            self._make_entry("Ny nyhet 1", "https://example.com/1"),
            self._make_entry("Ny nyhet 2", "https://example.com/2"),
        ]

        with patch("feeds.feedparser.parse", return_value=mock_feed):
            articles = fetch_articles({"TestFeed": "https://example.com/rss"}, history, max_per_feed=5)

        assert len(articles) == 2
        assert articles[0]["title"] == "Ny nyhet 1"

    def test_respects_max_per_feed(self):
        history = {}
        mock_feed = MagicMock()
        mock_feed.entries = [
            self._make_entry(f"Nyhet {i}", f"https://example.com/{i}")
            for i in range(10)
        ]

        with patch("feeds.feedparser.parse", return_value=mock_feed):
            articles = fetch_articles({"TestFeed": "https://example.com/rss"}, history, max_per_feed=3)

        assert len(articles) == 3

    def test_adds_seen_articles_to_history(self):
        history = {}
        mock_feed = MagicMock()
        mock_feed.entries = [self._make_entry("Nyhet", "https://example.com/1")]

        with patch("feeds.feedparser.parse", return_value=mock_feed):
            fetch_articles({"TestFeed": "https://example.com/rss"}, history, max_per_feed=5)

        expected_key = article_key("Nyhet", "https://example.com/1")
        assert expected_key in history

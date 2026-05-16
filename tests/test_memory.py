"""Tests for memory.py"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import (
    article_key,
    extract_headlines,
    load_history,
    load_memory,
    memory_to_context,
    save_history,
    save_memory,
)


def _make_cfg(tmpdir: str, days: int = 7) -> dict:
    return {
        "history": {
            "file": os.path.join(tmpdir, "seen_urls.json"),
            "memory_file": os.path.join(tmpdir, "topic_memory.json"),
            "days": days,
        }
    }


class TestLoadHistory:
    def test_returns_empty_dict_if_file_missing(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        result = load_history(cfg)
        assert result == {}

    def test_returns_existing_data(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        data = {"abc123": datetime.now().isoformat()}
        with open(cfg["history"]["file"], "w") as f:
            json.dump(data, f)
        result = load_history(cfg)
        assert result == data


class TestSaveHistory:
    def test_prunes_old_entries(self, tmp_path):
        cfg = _make_cfg(str(tmp_path), days=7)
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        new_date = datetime.now().isoformat()
        history = {
            "old_key": old_date,
            "new_key": new_date,
        }
        save_history(history, cfg)
        result = load_history(cfg)
        assert "old_key" not in result
        assert "new_key" in result

    def test_roundtrip(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        history = {"key1": datetime.now().isoformat()}
        save_history(history, cfg)
        result = load_history(cfg)
        assert "key1" in result


class TestSaveAndLoadMemory:
    def test_save_and_load(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        memory = []
        entry = {
            "date": datetime.now().isoformat(),
            "episode": 1,
            "headlines": ["Nyhet 1", "Nyhet 2"],
        }
        save_memory(memory, entry, cfg)
        result = load_memory(cfg)
        assert len(result) == 1
        assert result[0]["episode"] == 1

    def test_load_returns_empty_if_file_missing(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        result = load_memory(cfg)
        assert result == []

    def test_old_entries_pruned_on_load(self, tmp_path):
        cfg = _make_cfg(str(tmp_path), days=7)
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        new_date = datetime.now().isoformat()
        data = [
            {"date": old_date, "episode": 1, "headlines": []},
            {"date": new_date, "episode": 1, "headlines": ["Nyhet"]},
        ]
        with open(cfg["history"]["memory_file"], "w") as f:
            json.dump(data, f)
        result = load_memory(cfg)
        assert len(result) == 1
        assert result[0]["date"] == new_date


class TestMemoryToContext:
    def test_filters_on_episode(self):
        memory = [
            {"date": "2026-05-15", "episode": 1, "headlines": ["EP1 nyhet"]},
            {"date": "2026-05-15", "episode": 2, "headlines": ["EP2 nyhet"]},
        ]
        result = memory_to_context(memory, episode=1)
        assert "EP1 nyhet" in result
        assert "EP2 nyhet" not in result

    def test_returns_empty_string_for_no_match(self):
        memory = [
            {"date": "2026-05-15", "episode": 2, "headlines": ["EP2 nyhet"]},
        ]
        result = memory_to_context(memory, episode=1)
        assert result == ""

    def test_returns_empty_for_empty_memory(self):
        result = memory_to_context([], episode=1)
        assert result == ""

    def test_includes_date(self):
        memory = [
            {"date": "2026-05-15T10:00:00", "episode": 1, "headlines": ["Nyhet"]},
        ]
        result = memory_to_context(memory, episode=1)
        assert "2026-05-15" in result


class TestExtractHeadlines:
    def test_returns_max_8(self):
        articles = [
            {"category": "Test", "title": f"Artikel {i}", "summary": ""}
            for i in range(12)
        ]
        result = extract_headlines("", articles)
        assert len(result) == 8

    def test_includes_category_prefix(self):
        articles = [{"category": "SVT", "title": "Test", "summary": ""}]
        result = extract_headlines("", articles)
        assert "[SVT]" in result[0]

    def test_truncates_long_titles(self):
        long_title = "A" * 100
        articles = [{"category": "X", "title": long_title, "summary": ""}]
        result = extract_headlines("", articles)
        assert len(result[0]) < len(long_title) + 10  # prefix adds a few chars

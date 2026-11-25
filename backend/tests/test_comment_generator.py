"""Smoke tests for the AI comment generator.

Covers:
  - happy-path generation at n=5 with a mock router
  - length filter drops candidates over 500 chars
  - within-batch dedup filter drops exact duplicates
  - safety filter drops links, @-mentions, emails, phones, blocklist
  - generated rows land as needs_approval (never active)
  - the module has no direct path to approve_comment
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from phantom_fleet.core import comment_generator, comment_safety
from phantom_fleet.core import targets_admission as ta


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    """Point the shared sched store at a tmp sqlite DB per test."""
    from ops.sched import _store

    db_path = tmp_path / "persona-store.sqlite"
    monkeypatch.setattr(_store, "STORE", db_path)
    _store.apply_migrations()
    yield


@pytest.fixture(autouse=True)
def _clear_safety_cache():
    comment_safety.clear_blocklist_cache()
    yield
    comment_safety.clear_blocklist_cache()


def _mk_gen(outputs):
    def _fn(niche, n, hints):
        return list(outputs)
    return _fn


def test_generate_happy_path_lands_needs_approval():
    candidates = [
        "Love this look!",
        "Absolutely gorgeous shot.",
        "The lighting is perfect here.",
        "Obsessed with this vibe.",
        "This made my day, honestly.",
    ]
    receipt = comment_generator.generate_comments(
        niche="fashion",
        n=5,
        generator_fn=_mk_gen(candidates),
    )
    assert receipt["requested"] == 5
    assert receipt["submitted_to_admission"] == 5
    assert receipt["admission"]["inserted"] == 5

    pending = ta.list_pending_comments(limit=10)
    assert len(pending) == 5
    assert all(r["status"] == "needs_approval" for r in pending)
    assert all(r["niche"] == "fashion" for r in pending)


def test_length_filter_drops_over_500_chars():
    long_text = "x" * 501
    short_text = "nice"
    receipt = comment_generator.generate_comments(
        niche="generic",
        n=2,
        generator_fn=_mk_gen([long_text, short_text]),
    )
    assert receipt["length_dropped"] == 1
    assert receipt["submitted_to_admission"] == 1
    pending = ta.list_pending_comments()
    assert len(pending) == 1
    assert pending[0]["text"] == short_text


def test_within_batch_dedup():
    receipt = comment_generator.generate_comments(
        niche="generic",
        n=3,
        generator_fn=_mk_gen(["nice pic", "nice pic", "great shot"]),
    )
    assert receipt["within_batch_duplicates"] == 1
    assert receipt["submitted_to_admission"] == 2


def test_safety_filter_drops_link_mention_email_phone():
    receipt = comment_generator.generate_comments(
        niche="generic",
        n=5,
        generator_fn=_mk_gen([
            "check https://spam.example.com now",
            "dm me @someuser",
            "email me at hi@foo.com",
            "call +1 (555) 123-4567 today",
            "lovely photo",
        ]),
    )
    dropped_reasons = sorted(d["reason"] for d in receipt["safety_dropped"])
    assert "contains_link" in dropped_reasons
    assert "contains_mention" in dropped_reasons
    assert "contains_email" in dropped_reasons
    assert "contains_phone" in dropped_reasons
    assert receipt["submitted_to_admission"] == 1


def test_safety_filter_blocklist(monkeypatch, tmp_path):
    bl = tmp_path / "comment_blocklist.txt"
    bl.write_text("# header\nscam\n", encoding="utf-8")
    monkeypatch.setattr(comment_safety, "_BLOCKLIST_PATH", bl)
    comment_safety.clear_blocklist_cache()

    receipt = comment_generator.generate_comments(
        niche="generic",
        n=2,
        generator_fn=_mk_gen(["this is a SCAM post", "cute dog"]),
    )
    reasons = [d["reason"] for d in receipt["safety_dropped"]]
    assert any(r.startswith("blocklist:") for r in reasons)
    assert receipt["submitted_to_admission"] == 1


def test_module_cannot_approve():
    """The generator module must not re-export approve_comment."""
    assert not hasattr(comment_generator, "approve_comment")


def test_invalid_n_rejected():
    with pytest.raises(ValueError):
        comment_generator.generate_comments(
            niche="x", n=0, generator_fn=_mk_gen([]),
        )
    with pytest.raises(ValueError):
        comment_generator.generate_comments(
            niche="x", n=201, generator_fn=_mk_gen([]),
        )

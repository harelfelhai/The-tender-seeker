"""Shared setup for LLM eval tests.

Tests in this package call the real Claude API. They are gated on:
  1. The ``eval`` pytest marker — run with:  pytest -m eval
  2. ANTHROPIC_API_KEY being set in the environment

Estimated cost per full run: ~$0.01–0.02 (two small tenders on Haiku).
"""
from __future__ import annotations

import os
import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if item.get_closest_marker("eval"):
            # Skip automatically when there is no API key.
            if not os.getenv("ANTHROPIC_API_KEY"):
                item.add_marker(
                    pytest.mark.skip(reason="ANTHROPIC_API_KEY not set — skip LLM eval")
                )

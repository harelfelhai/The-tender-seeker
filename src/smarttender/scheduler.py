"""Periodic harvest scheduler using APScheduler.

Configuration (environment variables):
  HARVEST_INTERVAL_HOURS   default: 6   — how often to fetch new tenders
  HARVEST_ENABLED          default: true — set to false to disable auto-harvest

The scheduler is started/stopped in the FastAPI lifespan (app.py).
It runs harvest_and_notify() on the configured interval, which:
  1. Pulls new raw tenders from all registered sources
  2. Notifies matching companies via configured notifiers
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger(__name__)

_INTERVAL_HOURS = float(os.getenv("HARVEST_INTERVAL_HOURS", "6"))
_ENABLED = os.getenv("HARVEST_ENABLED", "true").lower() == "true"


def build_scheduler(harvest_job) -> AsyncIOScheduler | None:
    """Create and configure the scheduler.  Returns None if disabled."""
    if not _ENABLED:
        log.info("Harvest scheduler disabled (HARVEST_ENABLED=false)")
        return None

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        harvest_job,
        trigger="interval",
        hours=_INTERVAL_HOURS,
        id="harvest_all",
        replace_existing=True,
        max_instances=1,           # never run two harvests in parallel
        misfire_grace_time=300,    # if missed by <5 min, still run
    )
    log.info("Harvest scheduler configured: every %.1f hours", _INTERVAL_HOURS)
    return scheduler

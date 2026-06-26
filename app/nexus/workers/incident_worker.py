"""Dedicated worker for incident-heavy workflows."""

from __future__ import annotations


WORKER_NAME = "incident-worker"
WORKER_FLOW = "incidents"
WORKER_MODE = "event-driven"

from __future__ import annotations

from .database import list_requests, log_request


def can_generate() -> bool:
    return True


def record_request(data: dict) -> None:
    log_request(data.get("type", "unknown"), data.get("campaign_id"), data.get("prompt", ""))


def summarize_usage() -> dict:
    requests = list_requests()
    return {
        "requests": len(requests),
        "last_request": requests[0]["created_at"] if requests else None,
    }

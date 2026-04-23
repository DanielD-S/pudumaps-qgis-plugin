"""Unit tests for PudumapsClient. No QGIS runtime required."""

from __future__ import annotations

import time

import pytest
import requests_mock  # noqa: F401  (fixture used via pytest plugin)

from pudumaps_qgis.api_client import (
    DEFAULT_BASE_URL,
    PudumapsClient,
    PudumapsError,
)


def make_client() -> PudumapsClient:
    return PudumapsClient(api_key="pdmp_test", base_url=DEFAULT_BASE_URL)


def test_list_projects_parses_response(requests_mock):
    requests_mock.get(
        f"{DEFAULT_BASE_URL}/v1/projects",
        json={
            "data": [
                {
                    "id": "aaa",
                    "name": "A",
                    "description": None,
                    "visibility": "private",
                    "created_at": "2026-04-23T00:00:00Z",
                }
            ]
        },
    )
    projects = make_client().list_projects()
    assert len(projects) == 1
    assert projects[0].id == "aaa"
    assert projects[0].visibility == "private"


def test_missing_api_key_raises():
    with pytest.raises(PudumapsError):
        PudumapsClient(api_key="")


def test_401_raises_with_code(requests_mock):
    requests_mock.get(
        f"{DEFAULT_BASE_URL}/v1/projects",
        status_code=401,
        json={"error": {"code": "invalid_api_key", "message": "revoked"}},
    )
    with pytest.raises(PudumapsError) as exc_info:
        make_client().list_projects()
    assert exc_info.value.status == 401
    assert exc_info.value.code == "invalid_api_key"


def test_429_retries_respecting_reset(requests_mock, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    # Reset ~1s in the future
    reset_at = int(time.time()) + 1
    requests_mock.get(
        f"{DEFAULT_BASE_URL}/v1/projects",
        [
            {
                "status_code": 429,
                "headers": {"X-RateLimit-Reset": str(reset_at)},
                "json": {"error": {"code": "rate_limit_exceeded", "message": ""}},
            },
            {"status_code": 200, "json": {"data": []}},
        ],
    )
    projects = make_client().list_projects()
    assert projects == []
    assert len(sleeps) == 1
    assert 0.5 <= sleeps[0] <= 60


def test_429_gives_up_after_one_retry(requests_mock, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    requests_mock.get(
        f"{DEFAULT_BASE_URL}/v1/projects",
        status_code=429,
        json={"error": {"code": "rate_limit_exceeded", "message": ""}},
    )
    with pytest.raises(PudumapsError) as exc_info:
        make_client().list_projects()
    assert exc_info.value.status == 429


def test_create_project_posts_body(requests_mock):
    requests_mock.post(
        f"{DEFAULT_BASE_URL}/v1/projects",
        json={
            "data": {
                "id": "xxx",
                "name": "new",
                "description": "desc",
                "visibility": "private",
                "created_at": "2026-04-23T00:00:00Z",
            }
        },
        status_code=201,
    )
    p = make_client().create_project("new", "desc")
    assert p.id == "xxx"
    assert requests_mock.last_request.json() == {"name": "new", "description": "desc"}


def test_update_layer_requires_fields():
    with pytest.raises(PudumapsError, match="no fields"):
        make_client().update_layer("some-id")


def test_user_agent_sent(requests_mock):
    requests_mock.get(f"{DEFAULT_BASE_URL}/v1/projects", json={"data": []})
    make_client().list_projects()
    assert requests_mock.last_request.headers["User-Agent"].startswith("pudumaps-qgis/")
    assert requests_mock.last_request.headers["X-API-Key"] == "pdmp_test"


def test_delete_layer_returns_none(requests_mock):
    requests_mock.delete(
        f"{DEFAULT_BASE_URL}/v1/layers/abc",
        status_code=200,
        json={"ok": True},
    )
    # Should not raise
    make_client().delete_layer("abc")

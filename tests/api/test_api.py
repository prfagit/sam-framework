from __future__ import annotations

import os
import asyncio
from typing import Callable

from fastapi.testclient import TestClient

from sam.api import create_app
from sam.api.auth import get_user_store
from sam.config.settings import Settings


TEST_USERNAME = "tester"
TEST_PASSWORD = "test123"


def _make_headers(token: str, csrf_token: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if csrf_token:
        headers["X-CSRF-Token"] = csrf_token
    return headers


def _agent_payload(name: str = "test-agent") -> dict[str, object]:
    return {
        "name": name,
        "description": "Integration test agent",
        "system_prompt": "You are a helpful test agent.",
        "tools": [],
    }


def _create_client(tmp_path) -> tuple[TestClient, Callable[[], None]]:
    original_agent_root = os.environ.get("SAM_API_AGENT_ROOT")
    original_fernet = os.environ.get("SAM_FERNET_KEY")
    original_db = os.environ.get("SAM_DB_PATH")
    original_registration = os.environ.get("SAM_API_ALLOW_REGISTRATION")
    original_token_secret = os.environ.get("SAM_API_TOKEN_SECRET")
    original_agent_storage = os.environ.get("SAM_AGENT_STORAGE")

    os.environ["SAM_API_AGENT_ROOT"] = str(tmp_path)
    os.environ["SAM_DB_PATH"] = str(tmp_path / "sam_api.db")
    os.environ["SAM_API_TOKEN_SECRET"] = "test-token-secret"
    os.environ["SAM_API_ALLOW_REGISTRATION"] = "false"
    # Use file storage for tests to avoid event loop issues
    os.environ["SAM_AGENT_STORAGE"] = "file"
    if not original_fernet:
        os.environ.setdefault(
            "SAM_FERNET_KEY",
            "ZmFrZV9mZXJuZXRfa2V5XzMyX2NoYXJzXzEyMzQ1Njc=",
        )

    Settings.refresh_from_env()
    app = create_app({"docs_url": None, "redoc_url": None})
    client = TestClient(app)

    async def _bootstrap_user() -> None:
        store = await get_user_store()
        existing = await store.get_user(TEST_USERNAME)
        if not existing:
            await store.create_user(TEST_USERNAME, TEST_PASSWORD, is_admin=True)

    asyncio.run(_bootstrap_user())

    def cleanup() -> None:
        if original_agent_root is None:
            os.environ.pop("SAM_API_AGENT_ROOT", None)
        else:
            os.environ["SAM_API_AGENT_ROOT"] = original_agent_root
        if original_fernet is None:
            os.environ.pop("SAM_FERNET_KEY", None)
        else:
            os.environ["SAM_FERNET_KEY"] = original_fernet
        if original_db is None:
            os.environ.pop("SAM_DB_PATH", None)
        else:
            os.environ["SAM_DB_PATH"] = original_db
        if original_registration is None:
            os.environ.pop("SAM_API_ALLOW_REGISTRATION", None)
        else:
            os.environ["SAM_API_ALLOW_REGISTRATION"] = original_registration
        if original_token_secret is None:
            os.environ.pop("SAM_API_TOKEN_SECRET", None)
        else:
            os.environ["SAM_API_TOKEN_SECRET"] = original_token_secret
        if original_agent_storage is None:
            os.environ.pop("SAM_AGENT_STORAGE", None)
        else:
            os.environ["SAM_AGENT_STORAGE"] = original_agent_storage
        Settings.refresh_from_env()

    return client, cleanup


def _login(client: TestClient, username: str = TEST_USERNAME, password: str = TEST_PASSWORD) -> tuple[str, str]:
    """Login and return (access_token, csrf_token)."""
    response = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    access_token = response.json()["access_token"]
    # CSRF token is set in cookies after login
    csrf_token = response.cookies.get("sam_csrf_token", "")
    return access_token, csrf_token


def test_health_endpoint(tmp_path) -> None:
    client, cleanup = _create_client(tmp_path)
    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data
    finally:
        client.close()
        cleanup()


def test_agent_crud_flow(tmp_path) -> None:
    client, cleanup = _create_client(tmp_path)
    try:
        token, csrf_token = _login(client)
        headers = _make_headers(token, csrf_token)
        payload = _agent_payload()
        # POST requires CSRF token in both header and cookie
        create = client.post("/v1/agents", json=payload, headers=headers, cookies={"sam_csrf_token": csrf_token})
        assert create.status_code == 201
        body = create.json()
        assert body["name"] == payload["name"]
        assert body["source"] == "user"

        detail = client.get(f"/v1/agents/{payload['name']}", headers=headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["source"] == "user"
        assert detail_body["definition"]["name"] == payload["name"]

        listing = client.get("/v1/agents", headers=headers)
        assert listing.status_code == 200
        names = {item["name"] for item in listing.json()}
        assert payload["name"] in names
    finally:
        client.close()
        cleanup()


def test_session_lifecycle(tmp_path) -> None:
    client, cleanup = _create_client(tmp_path)
    try:
        token, csrf_token = _login(client)
        headers = _make_headers(token, csrf_token)
        cookies = {"sam_csrf_token": csrf_token}

        create = client.post("/v1/sessions", json={}, headers=headers, cookies=cookies)
        assert create.status_code == 201
        session_id = create.json()["session_id"]

        listing = client.get("/v1/sessions", headers=headers)
        assert listing.status_code == 200
        sessions = listing.json()
        assert any(item["session_id"] == session_id for item in sessions)

        detail = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["session_id"] == session_id

        delete = client.delete(f"/v1/sessions/{session_id}", headers=headers, cookies=cookies)
        assert delete.status_code == 204

        missing = client.delete(f"/v1/sessions/{session_id}", headers=headers, cookies=cookies)
        assert missing.status_code == 404
    finally:
        client.close()
        cleanup()


def test_stream_requires_auth(tmp_path) -> None:
    client, cleanup = _create_client(tmp_path)
    try:
        payload = {"prompt": "ping"}
        response = client.post("/v1/agents/sam/stream", json=payload)
        # CSRF middleware may return 403 before auth middleware returns 401
        # Both indicate the request is rejected without valid credentials
        assert response.status_code in (401, 403)
    finally:
        client.close()
        cleanup()

"""Unit tests for Agent OS Web UI and HTTP/SSE API endpoints."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from agent_os.bootstrap import build_runtime
from agent_os.domain.config import AppConfig
from agent_os.domain.kernel import KernelConfig
from agent_os.web.app import create_web_app


@pytest.fixture
def test_client(tmp_path: Path):
    """Create an isolated test runtime and Starlette TestClient."""
    kernel_config = KernelConfig(
        storage_root=str(tmp_path / "sessions.db"),
        companion_name="WebCompanion",
        approval_mode="autonomous",
    )
    runtime = build_runtime(
        app_config=AppConfig(),
        data_dir=str(tmp_path),
        kernel_config=kernel_config,
    )
    app = create_web_app(runtime.kernel)
    return TestClient(app)


def test_index_page_serves_html(test_client):
    """Verify root URL serves the Web UI index.html."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert "Agent OS" in response.text
    assert "text/html" in response.headers.get("content-type", "")


def test_health_endpoint(test_client):
    """Verify /api/health returns health score and report vitals."""
    response = test_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "health_score" in data
    assert data["health_score"] == 100


def test_sessions_crud_and_turn_history(test_client):
    """Verify listing, creating sessions and inspecting turn history."""
    # 1. Create a session
    post_res = test_client.post("/api/sessions", json={"title": "UI Integration Chat"})
    assert post_res.status_code == 200
    sess_data = post_res.json()
    session_id = sess_data["session_id"]
    assert sess_data["title"] == "UI Integration Chat"

    # 2. List sessions
    list_res = test_client.get("/api/sessions")
    assert list_res.status_code == 200
    sessions = list_res.json()
    assert any(s["session_id"] == session_id for s in sessions)

    # 3. Turns endpoint for empty session
    turns_res = test_client.get(f"/api/sessions/{session_id}/turns")
    assert turns_res.status_code == 200
    assert turns_res.json() == []


def test_ambient_nudges_endpoint(test_client):
    """Verify polling ambient notifications returns an array."""
    res = test_client.get("/api/ambient?session_id=test_sess")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_chat_stream_validation(test_client):
    """Verify /api/chat/stream validates required payload fields."""
    # Missing fields
    res = test_client.post("/api/chat/stream", json={})
    assert res.status_code == 400

    # Missing message
    res = test_client.post("/api/chat/stream", json={"session_id": "s1"})
    assert res.status_code == 400


def test_chat_stream_returns_sse_events(test_client):
    """Verify /api/chat/stream initiates an SSE event stream."""
    # Create session first
    create_res = test_client.post("/api/sessions", json={"title": "Stream Test"})
    session_id = create_res.json()["session_id"]

    res = test_client.post(
        "/api/chat/stream",
        json={"session_id": session_id, "message": "Hello Web UI"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    assert "event: " in res.text


def test_mcp_status_endpoint(test_client):
    """Verify /api/mcp/status returns servers, proposals, and tools."""
    res = test_client.get("/api/mcp/status")
    assert res.status_code == 200
    data = res.json()
    assert "servers" in data
    assert "proposals" in data
    assert "tools" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "workspace_read" in tool_names
    assert "workspace_command" in tool_names

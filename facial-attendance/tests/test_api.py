"""Unit and integration tests for FastAPI backend layer (app/api.py)."""

from io import BytesIO
from pathlib import Path
import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.api import app, services
from app.config import Config
from tests.test_face_recognizer import DummyFace, DummyFaceApp


@pytest.fixture
def api_client(tmp_path: Path):
    """Set up TestClient with isolated temporary services."""
    test_cfg = Config(project_root=tmp_path)
    test_cfg.ensure_directories()

    # Re-wire services to test directory
    services.config = test_cfg
    services.excel_service.registry_file = test_cfg.students_file
    services.excel_service.attendance_file = test_cfg.attendance_file
    services.enrollment_mgr.config = test_cfg
    services.attendance_mgr.config = test_cfg
    services.enrollment_mgr.student_ids = []
    services.enrollment_mgr.embeddings = np.zeros((0, 512), dtype=np.float32)
    services.attendance_mgr.present_student_ids.clear()
    services.attendance_mgr.recent_events.clear()

    # Mock face app for deterministic enrollment tests
    rng = np.random.RandomState(42)
    dummy_vec = rng.randn(512).astype(np.float32)
    dummy_vec /= np.linalg.norm(dummy_vec)
    dummy_face = DummyFace(bbox=[20, 20, 100, 100], embedding=dummy_vec)
    services.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    client = TestClient(app)
    yield client


def test_get_status_endpoint(api_client: TestClient):
    resp = api_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "camera_active" in data
    assert "session_active" in data
    assert "counts" in data
    assert "enrolled" in data["counts"]


def test_session_lifecycle_endpoints(api_client: TestClient):
    # Start session
    resp1 = api_client.post("/api/session/start", json={"session_id": "API_TEST_SES"})
    assert resp1.status_code == 200
    assert resp1.json()["session_id"] == "API_TEST_SES"

    status_resp = api_client.get("/api/status")
    assert status_resp.json()["session_active"] is True
    assert status_resp.json()["session_id"] == "API_TEST_SES"

    # Stop session
    resp2 = api_client.post("/api/session/stop")
    assert resp2.status_code == 200
    assert resp2.json()["success"] is True

    status_resp2 = api_client.get("/api/status")
    assert status_resp2.json()["session_active"] is False


def test_camera_toggle_endpoints(api_client: TestClient):
    # Stop camera
    resp = api_client.post("/api/camera/stop")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert services.camera_active is False


def test_enroll_student_success_via_api(api_client: TestClient):
    # Create valid JPEG image in-memory
    img = np.ones((120, 120, 3), dtype=np.uint8) * 150
    _, img_bytes = cv2.imencode(".jpg", img)

    files = {"image": ("test.jpg", BytesIO(img_bytes), "image/jpeg")}
    data = {"student_id": "API_S101", "name": "Deepika Padukone"}

    resp = api_client.post("/api/students", data=data, files=files)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["student_id"] == "API_S101"

    # Verify student appears in /api/students
    list_resp = api_client.get("/api/students")
    assert list_resp.status_code == 200
    students = list_resp.json()["students"]
    assert any(s["student_id"] == "API_S101" for s in students)


def test_enroll_student_failure_duplicate_via_api(api_client: TestClient):
    img = np.ones((120, 120, 3), dtype=np.uint8) * 150
    _, img_bytes = cv2.imencode(".jpg", img)

    files1 = {"image": ("test.jpg", BytesIO(img_bytes), "image/jpeg")}
    data1 = {"student_id": "DUP_01", "name": "First"}
    r1 = api_client.post("/api/students", data=data1, files=files1)
    assert r1.status_code == 200

    # Try duplicate
    files2 = {"image": ("test.jpg", BytesIO(img_bytes), "image/jpeg")}
    data2 = {"student_id": "DUP_01", "name": "Second"}
    r2 = api_client.post("/api/students", data=data2, files=files2)
    assert r2.status_code == 400
    assert "already enrolled" in r2.json()["detail"].lower()


def test_enroll_student_failure_no_face_via_api(api_client: TestClient):
    # Make face app return no faces
    services.enrollment_mgr._face_app = DummyFaceApp([])

    img = np.ones((120, 120, 3), dtype=np.uint8) * 150
    _, img_bytes = cv2.imencode(".jpg", img)
    files = {"image": ("blank.jpg", BytesIO(img_bytes), "image/jpeg")}
    data = {"student_id": "NO_FACE_01", "name": "Invisible"}

    resp = api_client.post("/api/students", data=data, files=files)
    assert resp.status_code == 400
    assert "No face detected" in resp.json()["detail"]


def test_recent_attendance_endpoint(api_client: TestClient):
    # Manually add an attendance mark
    services.attendance_mgr.start_session(session_id="REC_SES")
    services.attendance_mgr.confirm_and_write_attendance("S101", "Alice", 0.88)

    resp = api_client.get("/api/attendance/recent")
    assert resp.status_code == 200
    recent = resp.json()["recent"]
    assert len(recent) == 1
    assert recent[0]["student_id"] == "S101"
    assert recent[0]["name"] == "Alice"
    assert recent[0]["status"] == "Present"

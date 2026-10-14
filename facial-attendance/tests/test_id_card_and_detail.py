"""Unit and integration tests for ID Card and Student Detail Page features.

Covers:
1. Enrollment with ID card: success, wrong type, oversized file, corrupted file (with transactional rollback).
2. Backward compatibility: students.xlsx without id_card_path loads; legacy students show no ID card.
3. Detail endpoint: valid student, unknown student (404), missing file (404), response never contains embeddings.
4. Path traversal protection.
5. Image serving endpoints (/photo, /id-card).
"""

from io import BytesIO
from pathlib import Path
import cv2
from fastapi.testclient import TestClient
import numpy as np
import openpyxl
import pandas as pd
import pytest

from app.api import app, services
from app.config import Config
from app.excel_service import AttendanceEvent, ExcelService, StudentRecord
from tests.test_face_recognizer import DummyFace, DummyFaceApp


@pytest.fixture
def id_card_env(tmp_path: Path):
    """Set up isolated Config, ExcelService, EnrollmentManager, and TestClient."""
    test_cfg = Config(
        project_root=tmp_path,
        id_card_max_mb=1.0,  # 1MB limit for testing
        id_card_required=True,
    )
    test_cfg.ensure_directories()

    # Re-wire services
    services.config = test_cfg
    services.excel_service.registry_file = test_cfg.students_file
    services.excel_service.attendance_file = test_cfg.attendance_file
    services.enrollment_mgr.config = test_cfg
    services.attendance_mgr.config = test_cfg
    services.enrollment_mgr.student_ids = []
    services.enrollment_mgr.embeddings = np.zeros((0, 512), dtype=np.float32)
    services.enrollment_mgr.id_to_record.clear()
    services.attendance_mgr.present_student_ids.clear()
    services.attendance_mgr.recent_events.clear()

    # Mock face app for deterministic enrollment tests
    rng = np.random.RandomState(42)
    dummy_vec = rng.randn(512).astype(np.float32)
    dummy_vec /= np.linalg.norm(dummy_vec)
    dummy_face = DummyFace(bbox=[20, 20, 100, 100], embedding=dummy_vec)
    services.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    client = TestClient(app)
    yield test_cfg, services.excel_service, services.enrollment_mgr, client


def test_enrollment_id_card_missing_when_required_fails(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env
    config.id_card_required = True

    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S705",
        name="No Card",
        image_input=photo_bytes.tobytes(),
        excel_service=excel_service,
        id_card_input=None,
    )
    assert success is False
    assert "id card image is required" in msg.lower()


def test_enrollment_with_id_card_success(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    # Prepare dummy reference face photo (JPEG bytes)
    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)

    # Prepare dummy ID card image (PNG bytes)
    id_card_arr = np.ones((200, 320, 3), dtype=np.uint8) * 230
    cv2.putText(id_card_arr, "STUDENT ID CARD", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    _, id_card_bytes = cv2.imencode(".png", id_card_arr)

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S701",
        name="Rohan Verma",
        image_input=photo_bytes.tobytes(),
        excel_service=excel_service,
        id_card_input=id_card_bytes.tobytes(),
        id_card_filename="student_card.png",
    )

    assert success is True
    assert "enrolled successfully" in msg.lower()

    # Verify ID card was saved in data/id_cards/S701.png
    saved_card = config.id_card_dir / "S701.png"
    assert saved_card.exists()

    # Verify photo was saved in data/photos/S701.jpg
    saved_photo = config.photos_dir / "S701.jpg"
    assert saved_photo.exists()

    # Verify students.xlsx has id_card_path column and value
    df = pd.read_excel(config.students_file)
    assert "id_card_path" in df.columns
    assert df.iloc[0]["id_card_path"] == "id_cards/S701.png"

    # Verify in-memory record has ID card path
    rec = excel_service.get_student_by_id("S701")
    assert rec is not None
    assert rec.id_card_path == saved_card


def test_enrollment_id_card_wrong_type_fails_and_rolls_back(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)

    dummy_content = b"fake binary data"

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S702",
        name="Bad File",
        image_input=photo_bytes.tobytes(),
        excel_service=excel_service,
        id_card_input=dummy_content,
        id_card_filename="id_card.gif",  # Disallowed type
    )

    assert success is False
    assert "invalid id card file type" in msg.lower()

    # Transactional rollback check
    assert not (config.photos_dir / "S702.jpg").exists()
    assert not (config.id_card_dir / "S702.gif").exists()
    if config.students_file.exists():
        df = pd.read_excel(config.students_file)
        assert len(df) == 0
    assert "S702" not in enrollment_mgr.student_ids


def test_enrollment_id_card_oversized_fails_and_rolls_back(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)

    # 1.5 MB dummy content (exceeds 1.0 MB limit)
    oversized_bytes = b"X" * int(1.5 * 1024 * 1024)

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S703",
        name="Too Large",
        image_input=photo_bytes.tobytes(),
        excel_service=excel_service,
        id_card_input=oversized_bytes,
        id_card_filename="card.jpg",
    )

    assert success is False
    assert "exceeds maximum limit" in msg.lower()

    # Rollback verification
    assert not (config.photos_dir / "S703.jpg").exists()
    assert not (config.id_card_dir / "S703.jpg").exists()
    assert "S703" not in enrollment_mgr.student_ids


def test_enrollment_id_card_corrupted_fails_and_rolls_back(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)

    corrupted_bytes = b"RIFF....WEBPVP8 ... not valid jpg"

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S704",
        name="Corrupted",
        image_input=photo_bytes.tobytes(),
        excel_service=excel_service,
        id_card_input=corrupted_bytes,
        id_card_filename="corrupted.jpg",
    )

    assert success is False
    assert "could not be decoded" in msg.lower() or "corrupted" in msg.lower()
    assert not (config.photos_dir / "S704.jpg").exists()


def test_legacy_students_without_id_card_path_loads(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    # Create a photo file for legacy student
    photo_file = config.photos_dir / "S100.jpg"
    img = np.ones((100, 100, 3), dtype=np.uint8) * 150
    cv2.imwrite(str(photo_file), img)

    # Create 3-column legacy students.xlsx
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append(["student_id", "name", "photo_path"])
    ws.append(["S100", "Legacy User", "photos/S100.jpg"])
    wb.save(config.students_file)
    wb.close()

    records, errors = excel_service.read_registry()
    assert len(errors) == 0
    assert len(records) == 1
    rec = records[0]
    assert rec.student_id == "S100"
    assert rec.id_card_path is None
    assert rec.raw_id_card_path is None


def test_api_student_detail_and_never_exposes_embeddings(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    # 1. Enroll student with ID card via API
    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)
    card_arr = np.ones((200, 320, 3), dtype=np.uint8) * 220
    _, card_bytes = cv2.imencode(".jpg", card_arr)

    enroll_resp = client.post(
        "/api/students",
        data={"student_id": "S800", "name": "Meera Nair"},
        files={
            "photo": ("photo.jpg", BytesIO(photo_bytes.tobytes()), "image/jpeg"),
            "id_card": ("card.jpg", BytesIO(card_bytes.tobytes()), "image/jpeg"),
        },
    )
    assert enroll_resp.status_code == 200

    # 2. Add an attendance record in Excel
    att_event = AttendanceEvent(
        session_id="SES_HIST_01",
        student_id="S800",
        name="Meera Nair",
        date_str="2026-10-14",
        time_str="10:30:00",
        status="Present",
        match_score=0.8412,
    )
    excel_service.write_attendance_batch([att_event])

    # 3. Call GET /api/students/S800?session_id=SES_HIST_01
    detail_resp = client.get("/api/students/S800?session_id=SES_HIST_01")
    assert detail_resp.status_code == 200
    data = detail_resp.json()

    # Verify payload contents
    assert data["student_id"] == "S800"
    assert data["name"] == "Meera Nair"
    assert data["has_photo"] is True
    assert data["has_id_card"] is True
    assert data["photo_url"] == "/api/students/S800/photo"
    assert data["id_card_url"] == "/api/students/S800/id-card"

    # Verify attendance record matches Excel
    assert data["attendance"] is not None
    assert data["attendance"]["session_id"] == "SES_HIST_01"
    assert data["attendance"]["status"] == "Present"
    assert data["attendance"]["time"] == "10:30:00"
    assert data["attendance"]["similarity"] == 0.8412

    # SECURITY CHECK: Confirm embeddings are NEVER returned in response
    assert "embedding" not in data
    assert "embeddings" not in data
    assert "vector" not in data


def test_api_student_detail_unmarked_session(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    # Enroll student without attendance
    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)
    card_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, card_bytes = cv2.imencode(".jpg", card_arr)

    client.post(
        "/api/students",
        data={"student_id": "S801", "name": "Arjun Das"},
        files={
            "photo": ("p.jpg", BytesIO(photo_bytes.tobytes()), "image/jpeg"),
            "id_card": ("c.jpg", BytesIO(card_bytes.tobytes()), "image/jpeg"),
        },
    )

    resp = client.get("/api/students/S801?session_id=NON_EXISTENT_SESSION")
    assert resp.status_code == 200
    data = resp.json()
    assert data["attendance"]["status"] == "Not marked in this session"


def test_api_student_detail_unknown_404(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env
    resp = client.get("/api/students/UNKNOWN_STUDENT_999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_serve_photo_and_id_card_endpoints(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    photo_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, photo_bytes = cv2.imencode(".jpg", photo_arr)
    card_arr = np.ones((120, 120, 3), dtype=np.uint8) * 200
    _, card_bytes = cv2.imencode(".jpg", card_arr)

    client.post(
        "/api/students",
        data={"student_id": "S802", "name": "Devi"},
        files={
            "photo": ("p.jpg", BytesIO(photo_bytes.tobytes()), "image/jpeg"),
            "id_card": ("c.jpg", BytesIO(card_bytes.tobytes()), "image/jpeg"),
        },
    )

    photo_resp = client.get("/api/students/S802/photo")
    assert photo_resp.status_code == 200
    assert "image" in photo_resp.headers["content-type"]
    assert len(photo_resp.content) > 0

    id_card_resp = client.get("/api/students/S802/id-card")
    assert id_card_resp.status_code == 200
    assert "image" in id_card_resp.headers["content-type"]
    assert len(id_card_resp.content) > 0


def test_path_traversal_attempts_rejected(id_card_env):
    config, excel_service, enrollment_mgr, client = id_card_env

    # Path traversal in student_id URL parameter
    resp1 = client.get("/api/students/..%2F..%2Fwindows")
    assert resp1.status_code in (400, 404)

    resp2 = client.get("/api/students/..%2F..%2Fdata/photo")
    assert resp2.status_code in (400, 404)

    resp3 = client.get("/api/students/..%2F..%2Fdata/id-card")
    assert resp3.status_code in (400, 404)

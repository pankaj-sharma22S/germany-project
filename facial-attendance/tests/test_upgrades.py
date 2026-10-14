"""Unit tests for the new missing features:
1. Runtime single-student enrollment with transactional rollback.
2. Index updated live in-memory without restart.
3. Corrupted index recovery.
4. Face tracking and stability dynamics (excessive movement, timeout, lost tracking).
5. Attendance confirmed persistence ordering and duplicate-free retry.
"""

from pathlib import Path
import time
import cv2
import numpy as np
import openpyxl
import pandas as pd
import pytest

from app.attendance_manager import AttendanceManager
from app.config import Config
from app.enrollment import EnrollmentManager
from app.excel_service import ExcelService, StudentRecord
from app.stability_manager import FaceStabilityState, StabilityDecision, StabilityManager
from app.tracker import FaceTracker, TrackedFace
from tests.test_face_recognizer import DummyFace, DummyFaceApp


@pytest.fixture
def upgraded_env(tmp_path: Path):
    config = Config(
        project_root=tmp_path,
        stability_duration_seconds=0.2,  # Short duration for fast unit tests
        max_center_movement_px=20.0,
        max_size_change_ratio=0.15,
        stability_timeout_seconds=0.5,
        required_stable_frames=3,
    )
    config.ensure_directories()

    excel_service = ExcelService(
        project_root=tmp_path,
        registry_file=config.students_file,
        attendance_file=config.attendance_file,
    )

    enrollment_mgr = EnrollmentManager(config=config)
    tracker = FaceTracker()
    stability_mgr = StabilityManager(config=config)
    attendance_mgr = AttendanceManager(config=config, excel_service=excel_service)

    return config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr


def test_enroll_single_student_success_and_live_index_update(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Setup dummy face app returning 1 face with 512-d embedding
    rng = np.random.RandomState(42)
    dummy_vec = rng.randn(512).astype(np.float32)
    dummy_vec /= np.linalg.norm(dummy_vec)
    dummy_face = DummyFace(bbox=[20, 20, 100, 100], embedding=dummy_vec)
    enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    # Reference image input (numpy array)
    test_img = np.ones((150, 150, 3), dtype=np.uint8) * 180

    # 1. Enroll single student
    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S999",
        name="Vikram Rao",
        image_input=test_img,
        excel_service=excel_service,
    )
    assert success is True
    assert "enrolled successfully" in msg.lower()

    # 2. Verify photo was saved to data/photos/S999.jpg
    saved_photo = config.photos_dir / "S999.jpg"
    assert saved_photo.exists()

    # 3. Verify students.xlsx has row
    df = pd.read_excel(config.students_file)
    assert len(df) == 1
    assert df.iloc[0]["student_id"] == "S999"
    assert df.iloc[0]["name"] == "Vikram Rao"

    # 4. Verify embeddings.npz has entry
    assert config.embeddings_file.exists()
    with np.load(config.embeddings_file, allow_pickle=True) as data:
        assert list(data["student_ids"]) == ["S999"]
        assert data["embeddings"].shape == (1, 512)

    # 5. Verify live in-memory index was updated immediately (no restart needed!)
    assert "S999" in enrollment_mgr.student_ids
    assert enrollment_mgr.embeddings.shape == (1, 512)
    assert "S999" in enrollment_mgr.id_to_record
    assert enrollment_mgr.id_to_record["S999"].name == "Vikram Rao"


def test_enrollment_failure_no_face_rollback(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Dummy face app returns 0 faces
    enrollment_mgr._face_app = DummyFaceApp([])
    test_img = np.ones((150, 150, 3), dtype=np.uint8) * 200

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S888",
        name="Ghost Student",
        image_input=test_img,
        excel_service=excel_service,
    )
    assert success is False
    assert "No face detected" in msg

    # Verify complete rollback: no photo, no excel row, no embeddings.npz
    assert not (config.photos_dir / "S888.jpg").exists()
    assert not config.students_file.exists() or len(pd.read_excel(config.students_file)) == 0
    assert "S888" not in enrollment_mgr.student_ids


def test_enrollment_failure_multiple_faces_rollback(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Dummy face app returns 2 faces
    f1 = DummyFace(bbox=[10, 10, 50, 50], embedding=np.zeros(512))
    f2 = DummyFace(bbox=[60, 60, 100, 100], embedding=np.zeros(512))
    enrollment_mgr._face_app = DummyFaceApp([f1, f2])
    test_img = np.ones((150, 150, 3), dtype=np.uint8)

    success, msg = enrollment_mgr.enroll_single_student(
        student_id="S777",
        name="Crowd Photo",
        image_input=test_img,
        excel_service=excel_service,
    )
    assert success is False
    assert "Multiple faces" in msg
    assert not (config.photos_dir / "S777.jpg").exists()
    assert "S777" not in enrollment_mgr.student_ids


def test_enrollment_duplicate_rejection(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    dummy_vec = np.random.randn(512).astype(np.float32)
    dummy_face = DummyFace(bbox=[10, 10, 50, 50], embedding=dummy_vec)
    enrollment_mgr._face_app = DummyFaceApp([dummy_face])
    test_img = np.ones((100, 100, 3), dtype=np.uint8)

    # First enrollment
    s1, _ = enrollment_mgr.enroll_single_student("S100", "First", test_img, excel_service)
    assert s1 is True

    # Duplicate enrollment attempt
    s2, msg2 = enrollment_mgr.enroll_single_student("S100", "Duplicate", test_img, excel_service)
    assert s2 is False
    assert "already enrolled" in msg2.lower()


def test_corrupted_index_handling_and_safe_write(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Write corrupt data to embeddings.npz
    config.embeddings_file.write_bytes(b"CORRUPT_NON_NPZ_DATA_BYTES_RANDOM")

    # Add a student -> should handle corrupt file gracefully and overwrite with valid data
    dummy_vec = np.random.randn(512).astype(np.float32)
    dummy_face = DummyFace(bbox=[10, 10, 50, 50], embedding=dummy_vec)
    enrollment_mgr._face_app = DummyFaceApp([dummy_face])
    test_img = np.ones((100, 100, 3), dtype=np.uint8)

    success, msg = enrollment_mgr.enroll_single_student("S101", "Survivor", test_img, excel_service)
    assert success is True

    # Verify embeddings.npz is now valid and readable
    with np.load(config.embeddings_file, allow_pickle=True) as data:
        assert list(data["student_ids"]) == ["S101"]


def test_face_tracker_movement_and_stability_reset(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Frame 1: Face appears at (100, 100, 200, 200)
    tracks_f1 = tracker.update([(100, 100, 200, 200)])
    assert len(tracks_f1) == 1
    t1 = tracks_f1[0]
    dec1 = stability_mgr.update_face(t1)
    assert dec1.state in (FaceStabilityState.TRACKING, FaceStabilityState.STABILIZING)
    assert dec1.stable_frames == 1

    # Frame 2: Slight natural movement (102, 101, 202, 201) -> within threshold
    tracks_f2 = tracker.update([(102, 101, 202, 201)])
    assert len(tracks_f2) == 1
    t2 = tracks_f2[0]
    dec2 = stability_mgr.update_face(t2)
    assert dec2.state == FaceStabilityState.STABILIZING
    assert dec2.stable_frames == 2

    # Frame 3: EXCESSIVE MOVEMENT (jump by 80px to (180, 180, 280, 280))
    tracks_f3 = tracker.update([(180, 180, 280, 280)])
    assert len(tracks_f3) == 1
    t3 = tracks_f3[0]
    dec3 = stability_mgr.update_face(t3)
    assert dec3.state == FaceStabilityState.EXCESSIVE_MOVEMENT
    assert dec3.stable_frames == 0  # Counter reset!
    assert "movement detected" in dec3.feedback_message.lower()


def test_stability_completion_after_duration_and_frames(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Simulate stable frames
    for i in range(5):
        tracks = tracker.update([(100, 100, 200, 200)])
        time.sleep(0.08)  # Advance time to meet stability_duration_seconds (0.2s)
        dec = stability_mgr.update_face(tracks[0])

    assert dec.state == FaceStabilityState.STABLE
    assert dec.ready_for_recognition is True
    assert "verifying identity" in dec.feedback_message.lower()


def test_lost_tracking_pruning(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    # Face appears
    tracks = tracker.update([(100, 100, 200, 200)])
    t_id = tracks[0].track_id
    stability_mgr.update_face(tracks[0])
    assert t_id in stability_mgr._states

    # Face disappears for 6 frames (exceeding max_lost_frames=5)
    for _ in range(6):
        active = tracker.update([])
        stability_mgr.prune_lost_tracks([t.track_id for t in active])

    assert t_id not in tracker.tracks
    assert t_id not in stability_mgr._states


def test_confirmed_persistence_ordering_and_safe_retry(upgraded_env):
    config, excel_service, enrollment_mgr, tracker, stability_mgr, attendance_mgr = upgraded_env

    attendance_mgr.start_session(session_id="SESS_CONFIRM_TEST")

    # 1. Normal confirmed write
    msg, is_marked, err = attendance_mgr.confirm_and_write_attendance("S500", "Priya", 0.82)
    assert is_marked is True
    assert err is None
    assert "Attendance marked successfully - Priya (S500)" in msg
    assert "S500" in attendance_mgr.present_student_ids

    # Verify Excel was actually written to disk
    df = excel_service.load_existing_attendance()
    assert len(df) == 1
    assert df.iloc[0]["student_id"] == "S500"

    # 2. Retry with already marked student -> must NOT create duplicate in Excel
    msg2, is_marked2, err2 = attendance_mgr.confirm_and_write_attendance("S500", "Priya", 0.85)
    assert msg2 == "Already marked"
    assert is_marked2 is True
    df2 = excel_service.load_existing_attendance()
    assert len(df2) == 1  # Still 1 row! No duplicate!

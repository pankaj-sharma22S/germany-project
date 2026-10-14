"""Unit tests for AttendanceManager."""

from pathlib import Path
import time
import pytest

from app.attendance_manager import AttendanceManager
from app.config import Config
from app.excel_service import ExcelService, StudentRecord


@pytest.fixture
def manager_setup(tmp_path: Path):
    reg_file = tmp_path / "data" / "students.xlsx"
    att_file = tmp_path / "data" / "attendance.xlsx"

    config = Config(
        project_root=tmp_path,
        confirmation_frames=3,
        confirmation_window_sec=2.0,
    )
    config.ensure_directories()

    excel_service = ExcelService(tmp_path, reg_file, att_file)
    manager = AttendanceManager(config=config, excel_service=excel_service)
    manager.start_worker()

    eligible = [
        StudentRecord("S101", "Alice", tmp_path / "data" / "photos" / "S101.jpg", "photos/S101.jpg"),
        StudentRecord("S102", "Bob", tmp_path / "data" / "photos" / "S102.jpg", "photos/S102.jpg"),
        StudentRecord("S103", "Charlie", tmp_path / "data" / "photos" / "S103.jpg", "photos/S103.jpg"),
    ]

    yield manager, eligible, excel_service, att_file

    manager.stop_worker()


def test_stability_confirmation(manager_setup):
    manager, eligible, excel_service, att_file = manager_setup

    manager.start_session(session_id="TEST_SES_01", eligible_records=eligible)

    # Frame 1: Alice detected -> should report verifying
    status1, marked1 = manager.register_recognition("S101", "Alice", 0.78)
    assert marked1 is False
    assert "Verifying (1/3)" in status1

    # Frame 2: Alice detected -> verifying
    status2, marked2 = manager.register_recognition("S101", "Alice", 0.81)
    assert marked2 is False
    assert "Verifying (2/3)" in status2

    # Frame 3: Alice detected -> CONFIRMED & marked Present!
    status3, marked3 = manager.register_recognition("S101", "Alice", 0.82)
    assert marked3 is True
    assert "Attendance marked successfully" in status3

    # Frame 4: Alice detected again -> should report Already marked
    status4, marked4 = manager.register_recognition("S101", "Alice", 0.80)
    assert marked4 is False
    assert status4 == "Already marked"


def test_duplicate_prevention_across_frames(manager_setup):
    manager, eligible, excel_service, att_file = manager_setup

    manager.start_session(session_id="TEST_SES_02", eligible_records=eligible)

    # Confirm S101
    for _ in range(3):
        manager.register_recognition("S101", "Alice", 0.85)

    assert "S101" in manager.present_student_ids
    assert len(manager.present_student_ids) == 1

    # Send 10 more detections for S101
    for _ in range(10):
        status, marked = manager.register_recognition("S101", "Alice", 0.85)
        assert status == "Already marked"
        assert marked is False

    # Ensure still only 1 student marked present
    assert len(manager.present_student_ids) == 1


def test_session_separation_and_absent_marking(manager_setup):
    manager, eligible, excel_service, att_file = manager_setup

    # Session 1: Only S101 is present
    manager.start_session(session_id="CLASS_A", eligible_records=eligible)
    for _ in range(3):
        manager.register_recognition("S101", "Alice", 0.85)

    # Stop session with mark_absent=True -> S102 and S103 should be marked Absent
    present, absent = manager.stop_session(mark_absent=True)
    assert present == 1
    assert absent == 2

    # Verify Excel records
    df = excel_service.load_existing_attendance()
    assert len(df) == 3
    sess_a_records = df[df["session_id"] == "CLASS_A"]
    assert len(sess_a_records) == 3

    present_rows = sess_a_records[sess_a_records["status"] == "Present"]
    absent_rows = sess_a_records[sess_a_records["status"] == "Absent"]
    assert len(present_rows) == 1
    assert present_rows.iloc[0]["student_id"] == "S101"
    assert len(absent_rows) == 2
    assert set(absent_rows["student_id"]) == {"S102", "S103"}

    # Session 2: New session, same students eligible
    manager.start_session(session_id="CLASS_B", eligible_records=eligible)
    # Alice should be eligible again in CLASS_B!
    assert "S101" not in manager.present_student_ids
    for _ in range(3):
        status, marked = manager.register_recognition("S101", "Alice", 0.88)

    assert "S101" in manager.present_student_ids
    present_b, absent_b = manager.stop_session(mark_absent=True)
    assert present_b == 1
    assert absent_b == 2

    # Verify combined attendance sheet has both sessions
    df2 = excel_service.load_existing_attendance()
    assert len(df2) == 6  # 3 from CLASS_A + 3 from CLASS_B

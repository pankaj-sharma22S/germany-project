"""Integration tests for ImageAttendancePipeline."""

from pathlib import Path
import cv2
import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.image_runner import ImageAttendancePipeline
from tests.test_face_recognizer import DummyFace, DummyFaceApp


def test_image_pipeline_end_to_end(tmp_path: Path):
    config = Config(project_root=tmp_path, confirmation_frames=2)
    config.ensure_directories()

    # Create dummy photo and registry
    photo_file = config.photos_dir / "S101.jpg"
    blank_img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.imwrite(str(photo_file), blank_img)

    df = pd.DataFrame(
        [{"student_id": "S101", "name": "Alice Smith", "photo_path": "photos/S101.jpg"}]
    )
    df.to_excel(config.students_file, index=False)

    # Pre-generate valid embeddings.npz so setup() loads cleanly
    rng = np.random.RandomState(42)
    alice_vec = rng.randn(512).astype(np.float32)
    alice_vec /= np.linalg.norm(alice_vec)

    meta = {
        "model_name": config.model_name,
        "count": 1,
        "fingerprint": {
            "S101": "DUMMY",
        },
    }
    np.savez_compressed(
        config.embeddings_file,
        student_ids=np.array(["S101"]),
        embeddings=alice_vec.reshape(1, 512),
        metadata=pd.Series(meta).to_json(),
    )

    pipeline = ImageAttendancePipeline(config=config)
    pipeline.enrollment_mgr.student_ids = ["S101"]
    pipeline.enrollment_mgr.embeddings = alice_vec.reshape(1, 512)
    pipeline.attendance_mgr.start_worker()

    # Mock face detection in input image
    live_face = DummyFace(bbox=[30, 30, 120, 120], embedding=alice_vec)
    pipeline.face_recognizer.enrollment_mgr._face_app = DummyFaceApp([live_face])

    # Run on image
    test_img_path = tmp_path / "test_input.jpg"
    cv2.imwrite(str(test_img_path), blank_img)

    annotated, results = pipeline.process_image(
        image_path=test_img_path,
        session_id="IMAGE_SES_01",
        simulate_confirmations=True,
    )

    assert len(results) == 1
    match_res, status = results[0]
    assert match_res.student_id == "S101"
    assert "Attendance marked successfully" in status or status == "Present"

    pipeline.close()

    # Verify Excel was written
    df_att = pd.read_excel(config.attendance_file, sheet_name="Attendance")
    assert len(df_att) == 1
    assert df_att.iloc[0]["student_id"] == "S101"
    assert df_att.iloc[0]["status"] == "Present"

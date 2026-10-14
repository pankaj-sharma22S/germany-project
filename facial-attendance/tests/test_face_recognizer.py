"""Unit tests for FaceRecognizer and EnrollmentManager."""

from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np
import pytest

from app.config import Config
from app.enrollment import EnrollmentManager
from app.excel_service import StudentRecord
from app.face_recognizer import FaceMatchResult, FaceRecognizer


class DummyFace:
    """Mock InsightFace Face object for deterministic unit testing."""

    def __init__(self, bbox, embedding, det_score=0.95):
        self.bbox = np.array(bbox, dtype=np.float32)
        self.embedding = np.array(embedding, dtype=np.float32)
        self.det_score = det_score


class DummyFaceApp:
    """Mock InsightFace FaceAnalysis application."""

    def __init__(self, faces_to_return=None):
        self.faces_to_return = faces_to_return or []

    def get(self, img):
        return self.faces_to_return


@pytest.fixture
def recognizer_setup(tmp_path: Path):
    config = Config(
        project_root=tmp_path,
        recognition_threshold=0.50,
        det_thresh=0.40,
        min_face_size_pixels=30,
    )
    config.ensure_directories()

    # Generate distinct normalized 512-d unit vectors for 3 students
    rng = np.random.RandomState(42)
    vec1 = rng.randn(512).astype(np.float32)
    vec1 /= np.linalg.norm(vec1)

    vec2 = rng.randn(512).astype(np.float32)
    vec2 /= np.linalg.norm(vec2)

    vec3 = rng.randn(512).astype(np.float32)
    vec3 /= np.linalg.norm(vec3)

    enrollment_mgr = EnrollmentManager(config=config)
    enrollment_mgr.student_ids = ["S101", "S102", "S103"]
    enrollment_mgr.embeddings = np.vstack([vec1, vec2, vec3])
    enrollment_mgr.id_to_record = {
        "S101": StudentRecord("S101", "Alice", tmp_path / "S101.jpg", "photos/S101.jpg"),
        "S102": StudentRecord("S102", "Bob", tmp_path / "S102.jpg", "photos/S102.jpg"),
        "S103": StudentRecord("S103", "Charlie", tmp_path / "S103.jpg", "photos/S103.jpg"),
    }

    recognizer = FaceRecognizer(config=config, enrollment_mgr=enrollment_mgr)
    return recognizer, enrollment_mgr, [vec1, vec2, vec3]


def test_known_face_recognition(recognizer_setup):
    recognizer, enrollment_mgr, (vec1, vec2, vec3) = recognizer_setup

    # Test with a live vector nearly identical to Alice (cosine similarity ~ 0.95)
    live_vec = vec1 * 0.95 + np.random.RandomState(10).randn(512).astype(np.float32) * 0.05
    live_vec /= np.linalg.norm(live_vec)

    dummy_face = DummyFace(bbox=[50, 50, 150, 150], embedding=live_vec)
    recognizer.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    dummy_frame = np.zeros((300, 300, 3), dtype=np.uint8)
    results = recognizer.process_frame(dummy_frame)

    assert len(results) == 1
    res = results[0]
    assert res.is_known is True
    assert res.student_id == "S101"
    assert res.name == "Alice"
    assert res.similarity >= 0.50


def test_unknown_face_rejection(recognizer_setup):
    recognizer, enrollment_mgr, (vec1, vec2, vec3) = recognizer_setup

    # Generate an unknown vector orthogonal to all enrolled vectors
    rng = np.random.RandomState(999)
    unknown_vec = rng.randn(512).astype(np.float32)
    # Project out components of vec1, vec2, vec3 to ensure low similarity
    for v in (vec1, vec2, vec3):
        unknown_vec -= np.dot(unknown_vec, v) * v
    unknown_vec /= np.linalg.norm(unknown_vec)

    dummy_face = DummyFace(bbox=[50, 50, 150, 150], embedding=unknown_vec)
    recognizer.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    dummy_frame = np.zeros((300, 300, 3), dtype=np.uint8)
    results = recognizer.process_frame(dummy_frame)

    assert len(results) == 1
    res = results[0]
    assert res.is_known is False
    assert res.student_id is None
    assert res.name == "Unknown"
    assert res.similarity < 0.50


def test_ambiguous_face_rejection(recognizer_setup):
    recognizer, enrollment_mgr, (vec1, vec2, vec3) = recognizer_setup

    # Create a vector equally close to Alice (vec1) and Bob (vec2)
    # Both similarities high (~0.7), but margin is 0.0 -> ambiguous!
    ambiguous_vec = (vec1 + vec2) / np.linalg.norm(vec1 + vec2)

    dummy_face = DummyFace(bbox=[50, 50, 150, 150], embedding=ambiguous_vec)
    recognizer.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    dummy_frame = np.zeros((300, 300, 3), dtype=np.uint8)
    results = recognizer.process_frame(dummy_frame)

    assert len(results) == 1
    res = results[0]
    # Should be rejected as Unknown due to ambiguity check
    assert res.is_known is False
    assert res.is_ambiguous is True
    assert res.name == "Unknown"


def test_small_face_filtering(recognizer_setup):
    recognizer, enrollment_mgr, (vec1, vec2, vec3) = recognizer_setup

    # Create a face bbox smaller than min_face_size_pixels (30)
    tiny_face = DummyFace(bbox=[10, 10, 25, 25], embedding=vec1)  # 15x15 pixels
    recognizer.enrollment_mgr._face_app = DummyFaceApp([tiny_face])

    dummy_frame = np.zeros((300, 300, 3), dtype=np.uint8)
    results = recognizer.process_frame(dummy_frame)

    # Tiny face should be ignored completely
    assert len(results) == 0


def test_empty_enrolled_index(tmp_path: Path):
    config = Config(project_root=tmp_path)
    enrollment_mgr = EnrollmentManager(config=config)
    enrollment_mgr.student_ids = []
    enrollment_mgr.embeddings = np.zeros((0, 512), dtype=np.float32)

    recognizer = FaceRecognizer(config=config, enrollment_mgr=enrollment_mgr)
    rng = np.random.RandomState(1)
    face_vec = rng.randn(512).astype(np.float32)
    face_vec /= np.linalg.norm(face_vec)

    dummy_face = DummyFace(bbox=[50, 50, 150, 150], embedding=face_vec)
    recognizer.enrollment_mgr._face_app = DummyFaceApp([dummy_face])

    dummy_frame = np.zeros((300, 300, 3), dtype=np.uint8)
    results = recognizer.process_frame(dummy_frame)

    assert len(results) == 1
    assert results[0].is_known is False
    assert results[0].name == "Unknown"

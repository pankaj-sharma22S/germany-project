"""Unit tests for EnrollmentManager caching and stale detection."""

from pathlib import Path
import json
import numpy as np
import pytest

from app.config import Config
from app.enrollment import EnrollmentManager, compute_file_hash
from app.excel_service import StudentRecord


def test_stale_detection_and_caching(tmp_path: Path):
    config = Config(project_root=tmp_path)
    config.ensure_directories()

    # Create dummy photo
    photo_file = config.photos_dir / "S101.jpg"
    photo_file.write_bytes(b"FAKE_PHOTO_DATA_VERSION_1")

    # Create dummy students.xlsx
    config.students_file.write_bytes(b"FAKE_EXCEL_REGISTRY_V1")

    record = StudentRecord("S101", "Alice", photo_file, "photos/S101.jpg")
    mgr = EnrollmentManager(config=config)

    # 1. Manually create an index saved on disk
    fingerprint1 = mgr.calculate_registry_fingerprint([record])
    meta = {
        "model_name": config.model_name,
        "count": 1,
        "fingerprint": fingerprint1,
    }
    dummy_emb = np.ones((1, 512), dtype=np.float32)
    np.savez_compressed(
        config.embeddings_file,
        student_ids=np.array(["S101"]),
        embeddings=dummy_emb,
        metadata=json.dumps(meta),
    )

    # 2. Check is_index_up_to_date -> should be True
    assert mgr.is_index_up_to_date([record], fingerprint1) is True

    # 3. Simulate photo update on disk
    photo_file.write_bytes(b"FAKE_PHOTO_DATA_VERSION_2_MODIFIED")
    fingerprint2 = mgr.calculate_registry_fingerprint([record])

    # 4. Check is_index_up_to_date -> should now detect STALE and return False!
    assert mgr.is_index_up_to_date([record], fingerprint2) is False


def test_embedding_alignment(tmp_path: Path):
    config = Config(project_root=tmp_path)
    config.ensure_directories()

    ids = ["S101", "S102", "S103"]
    embs = np.random.RandomState(42).randn(3, 512).astype(np.float32)

    meta = {"model_name": "buffalo_s", "count": 3, "fingerprint": {}}
    np.savez_compressed(
        config.embeddings_file,
        student_ids=np.array(ids),
        embeddings=embs,
        metadata=json.dumps(meta),
    )

    # Load back and verify alignment and shapes
    loaded = np.load(config.embeddings_file, allow_pickle=True)
    assert list(loaded["student_ids"]) == ids
    assert loaded["embeddings"].shape == (3, 512)
    assert np.allclose(loaded["embeddings"], embs)

"""Enrollment module.

Handles:
1. Extracting 512-d facial embeddings from reference photos listed in students.xlsx.
2. Validating reference images (rejecting zero or multiple faces).
3. L2-normalizing embedding vectors.
4. Saving aligned student IDs and vectors to data/embeddings.npz.
5. Detecting stale embeddings via hash verification and caching in-memory.
6. Ensuring biometric privacy (no raw embedding logging).
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional
import cv2
import numpy as np

import threading

from app.config import Config
from app.excel_service import ExcelService, StudentRecord

logger = logging.getLogger(__name__)


class EnrollmentError(Exception):
    """Raised when enrollment fails."""


def compute_file_hash(path: Path) -> str:
    """Calculate SHA256 hash of a file for change detection."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class EnrollmentManager:
    """Manages reference embeddings extraction, storage, and caching."""

    def __init__(self, config: Config, face_app=None):
        self.config = config
        self._face_app = face_app
        self.student_ids: list[str] = []
        self.embeddings: Optional[np.ndarray] = None  # Shape: (N, 512)
        self.id_to_record: dict[str, StudentRecord] = {}
        self._lock = threading.Lock()

    def get_face_app(self):
        """Lazy loader for the InsightFace FaceAnalysis model."""
        if self._face_app is None:
            try:
                from insightface.app import FaceAnalysis

                logger.info(
                    "Initializing InsightFace FaceAnalysis (model: %s)...",
                    self.config.model_name,
                )
                app = FaceAnalysis(
                    name=self.config.model_name,
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=0, det_size=self.config.detection_size)
                self._face_app = app
                logger.info("InsightFace FaceAnalysis initialized successfully.")
            except Exception as exc:
                logger.error("Failed to initialize FaceAnalysis: %s", exc)
                raise EnrollmentError(f"Failed to initialize FaceAnalysis model: {exc}") from exc
        return self._face_app

    def calculate_registry_fingerprint(self, records: list[StudentRecord]) -> dict[str, str]:
        """Compute fingerprint of registry records and reference images."""
        fingerprint = {}
        if self.config.students_file.exists():
            fingerprint["__registry__"] = compute_file_hash(self.config.students_file)

        for rec in records:
            if rec.photo_path.exists():
                fingerprint[rec.student_id] = compute_file_hash(rec.photo_path)
            else:
                fingerprint[rec.student_id] = "MISSING"
        return fingerprint

    def is_index_up_to_date(
        self, records: list[StudentRecord], current_fingerprint: dict[str, str]
    ) -> bool:
        """Check if data/embeddings.npz exists and matches the current records fingerprint."""
        if not self.config.embeddings_file.exists():
            return False

        try:
            with np.load(self.config.embeddings_file, allow_pickle=True) as data:
                if "metadata" not in data:
                    return False
                cached_meta = json.loads(str(data["metadata"]))
                saved_fingerprint = cached_meta.get("fingerprint", {})

                if current_fingerprint != saved_fingerprint:
                    logger.info("Registry or reference photos have changed; embeddings index is stale.")
                    return False

                # Ensure all enrolled IDs match current records
                enrolled_ids = list(data["student_ids"])
                record_ids = [r.student_id for r in records]
                if set(enrolled_ids) != set(record_ids):
                    return False

                return True
        except Exception as exc:
            logger.warning("Error reading existing embeddings index: %s. Rebuilding required.", exc)
            return False

    def load_or_rebuild_index(
        self, records: list[StudentRecord], force_rebuild: bool = False
    ) -> tuple[int, list[str]]:
        """Load cached embeddings if valid, or extract and build index.

        Returns:
            (enrolled_count, errors): Number of successfully enrolled students and list of errors.
        """
        self.id_to_record = {r.student_id: r for r in records}
        errors: list[str] = []

        if not records:
            logger.warning("No valid student records provided for enrollment.")
            self.student_ids = []
            self.embeddings = np.zeros((0, 512), dtype=np.float32)
            return 0, ["No student records to enroll."]

        fingerprint = self.calculate_registry_fingerprint(records)

        # Check if existing index can be loaded
        if not force_rebuild and self.is_index_up_to_date(records, fingerprint):
            try:
                with np.load(self.config.embeddings_file, allow_pickle=True) as data:
                    self.student_ids = list(data["student_ids"])
                    self.embeddings = np.array(data["embeddings"], dtype=np.float32)
                logger.info(
                    "Loaded valid cached embeddings for %d students from %s",
                    len(self.student_ids),
                    self.config.embeddings_file.name,
                )
                return len(self.student_ids), []
            except Exception as exc:
                logger.warning("Failed to load cached index: %s. Rebuilding...", exc)

        # Rebuild embeddings from reference photos
        logger.info("Building embeddings index for %d student records...", len(records))
        app = self.get_face_app()

        valid_ids: list[str] = []
        valid_embeddings: list[np.ndarray] = []

        for rec in records:
            if not rec.photo_path.exists():
                errors.append(f"Student {rec.student_id} ({rec.name}): Photo file missing at '{rec.photo_path}'.")
                continue

            img = cv2.imread(str(rec.photo_path))
            if img is None or img.size == 0:
                errors.append(f"Student {rec.student_id} ({rec.name}): Unable to read image file.")
                continue

            # Detect faces using InsightFace
            try:
                faces = app.get(img)
            except Exception as exc:
                errors.append(f"Student {rec.student_id} ({rec.name}): Face detection failed ({exc}).")
                continue

            if len(faces) == 0:
                errors.append(
                    f"Student {rec.student_id} ({rec.name}): No face detected in reference photo "
                    f"'{rec.raw_photo_path}'."
                )
                continue
            if len(faces) > 1:
                errors.append(
                    f"Student {rec.student_id} ({rec.name}): Ambiguous photo - found {len(faces)} faces "
                    f"in reference photo '{rec.raw_photo_path}'. Exactly 1 face is required."
                )
                continue

            face = faces[0]
            embedding = face.embedding
            if embedding is None or len(embedding) == 0:
                errors.append(f"Student {rec.student_id} ({rec.name}): Failed to extract facial embedding.")
                continue

            # Normalize embedding vector (L2 norm)
            norm = np.linalg.norm(embedding)
            if norm == 0:
                errors.append(f"Student {rec.student_id} ({rec.name}): Zero norm embedding vector.")
                continue
            norm_embedding = (embedding / norm).astype(np.float32)

            valid_ids.append(rec.student_id)
            valid_embeddings.append(norm_embedding)

        if not valid_embeddings:
            self.student_ids = []
            self.embeddings = np.zeros((0, 512), dtype=np.float32)
            logger.error("No valid embeddings could be generated for any student.")
            return 0, errors

        # Convert to aligned numpy array
        self.student_ids = valid_ids
        self.embeddings = np.vstack(valid_embeddings)

        # Save to data/embeddings.npz
        self.config.ensure_directories()
        meta = {
            "model_name": self.config.model_name,
            "count": len(valid_ids),
            "fingerprint": fingerprint,
        }

        try:
            np.savez_compressed(
                self.config.embeddings_file,
                student_ids=np.array(valid_ids),
                embeddings=self.embeddings,
                metadata=json.dumps(meta),
            )
            logger.info(
                "Successfully generated and saved %d student embeddings to %s",
                len(valid_ids),
                self.config.embeddings_file.name,
            )
        except Exception as exc:
            err = f"Failed to save embeddings to {self.config.embeddings_file}: {exc}"
            logger.error(err)
            errors.append(err)

        return len(valid_ids), errors

    def enroll_single_student(
        self,
        student_id: str,
        name: str,
        image_input: Path | str | np.ndarray,
        excel_service: ExcelService,
    ) -> tuple[bool, str]:
        """Enroll a single student at runtime with transactional rollback.

        Validates input fields and image, extracts normalized 512-d embedding,
        saves photo to data/photos/, appends to students.xlsx, updates
        data/embeddings.npz, and updates the live in-memory index immediately under lock.

        Returns:
            (success, message): True and confirmation message, or False and error explanation.
        """
        sid_clean = str(student_id).strip()
        name_clean = str(name).strip()

        # 1. Validate fields
        if not sid_clean:
            return False, "Validation Error: Student ID cannot be empty."
        if not name_clean:
            return False, "Validation Error: Student Full Name cannot be empty."

        with self._lock:
            # Check for duplicate in live index
            if sid_clean in self.student_ids:
                return False, f"Validation Error: Student ID '{sid_clean}' is already enrolled."

        # 2. Validate and load image
        img: Optional[np.ndarray] = None
        if isinstance(image_input, np.ndarray):
            img = image_input.copy()
        elif isinstance(image_input, (str, Path)):
            img_path = Path(image_input)
            if not img_path.exists():
                return False, f"Validation Error: Image file does not exist at '{img_path}'."
            img = cv2.imread(str(img_path))

        if img is None or img.size == 0:
            return False, "Validation Error: Unable to read image or image is corrupted."

        # Detect face & generate embedding
        try:
            face_app = self.get_face_app()
            faces = face_app.get(img)
        except Exception as exc:
            return False, f"Face Detection Error: {exc}"

        if len(faces) == 0:
            return False, "Validation Error: No face detected in reference photo. Please provide a clear frontal photo."
        if len(faces) > 1:
            return False, (
                f"Validation Error: Multiple faces ({len(faces)}) detected. "
                "Reference photo must contain exactly one person."
            )

        face = faces[0]
        raw_emb = face.embedding
        if raw_emb is None or len(raw_emb) == 0:
            return False, "Biometric Error: Failed to generate face embedding."

        norm = np.linalg.norm(raw_emb)
        if norm == 0:
            return False, "Biometric Error: Zero-norm embedding generated."
        normalized_emb = (raw_emb / norm).astype(np.float32)

        # Tracking variables for transactional rollback
        saved_photo_path: Optional[Path] = None
        excel_row_added = False
        temp_npz_path: Optional[Path] = None

        self.config.ensure_directories()
        dest_filename = f"{sid_clean}.jpg"
        dest_photo_path = self.config.photos_dir / dest_filename
        rel_photo_path = f"photos/{dest_filename}"

        try:
            # 3. Save photo to data/photos/
            write_ok = cv2.imwrite(str(dest_photo_path), img)
            if not write_ok:
                raise IOError(f"Could not write reference photo to '{dest_photo_path}'.")
            saved_photo_path = dest_photo_path

            # 4. Append row to data/students.xlsx
            excel_ok, excel_err = excel_service.append_student_record(
                student_id=sid_clean,
                name=name_clean,
                photo_path_str=rel_photo_path,
            )
            if not excel_ok:
                raise RuntimeError(f"Excel registry update failed: {excel_err}")
            excel_row_added = True

            # 5. Add embedding + ID to data/embeddings.npz without overwriting existing
            with self._lock:
                current_ids = list(self.student_ids)
                current_embs = self.embeddings

                if current_embs is not None and len(current_embs) > 0:
                    new_ids = current_ids + [sid_clean]
                    new_embs = np.vstack([current_embs, normalized_emb.reshape(1, 512)])
                else:
                    new_ids = [sid_clean]
                    new_embs = normalized_emb.reshape(1, 512)

                # Build updated fingerprint
                records_list = list(self.id_to_record.values())
                new_record = StudentRecord(
                    student_id=sid_clean,
                    name=name_clean,
                    photo_path=dest_photo_path,
                    raw_photo_path=rel_photo_path,
                )
                records_list.append(new_record)
                fingerprint = self.calculate_registry_fingerprint(records_list)

                meta = {
                    "model_name": self.config.model_name,
                    "count": len(new_ids),
                    "fingerprint": fingerprint,
                }

                # Save via temporary file then replace
                temp_npz_path = self.config.embeddings_file.with_suffix(".tmp.npz")
                np.savez_compressed(
                    temp_npz_path,
                    student_ids=np.array(new_ids),
                    embeddings=new_embs,
                    metadata=json.dumps(meta),
                )

                # Atomically replace destination
                if temp_npz_path.exists():
                    temp_npz_path.replace(self.config.embeddings_file)
                temp_npz_path = None

                # 6. Update in-memory index immediately under lock (no restart)
                self.student_ids = new_ids
                self.embeddings = new_embs
                self.id_to_record[sid_clean] = new_record

            logger.info("Successfully enrolled student %s (%s) at runtime.", sid_clean, name_clean)
            return True, f"Student {name_clean} ({sid_clean}) enrolled successfully!"

        except Exception as exc:
            logger.error("Enrollment failed for student %s: %s. Initiating rollback...", sid_clean, exc)
            # Transactional Rollback: clean up all partial artifacts
            if temp_npz_path is not None and temp_npz_path.exists():
                try:
                    temp_npz_path.unlink()
                except Exception:
                    pass

            if excel_row_added:
                excel_service.remove_student_record(sid_clean)

            if saved_photo_path is not None and saved_photo_path.exists():
                try:
                    saved_photo_path.unlink()
                except Exception:
                    pass

            return False, f"Enrollment Failed: {exc}"

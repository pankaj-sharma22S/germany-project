"""Face Recognizer module.

Handles:
1. Detecting faces in video frames or static images.
2. Generating normalized embeddings for each detected face.
3. Comparing live embeddings against enrolled index using cosine similarity.
4. Thresholding and unknown-person rejection.
5. Ambiguity checks between top-scoring candidates.
"""

from dataclasses import dataclass
import logging
from typing import Optional
import numpy as np

from app.config import Config
from app.enrollment import EnrollmentManager

logger = logging.getLogger(__name__)


@dataclass
class FaceMatchResult:
    """Detection and recognition result for a single face in a frame."""

    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    student_id: Optional[str]
    name: str  # Student name or 'Unknown'
    similarity: float  # Cosine similarity score [-1.0, 1.0]
    is_known: bool
    is_ambiguous: bool = False
    det_score: float = 0.0


class FaceRecognizer:
    """Performs face detection, embedding extraction, and matching against enrolled students."""

    def __init__(self, config: Config, enrollment_mgr: EnrollmentManager):
        self.config = config
        self.enrollment_mgr = enrollment_mgr

    def process_frame(self, frame_bgr: np.ndarray) -> list[FaceMatchResult]:
        """Detect and recognize all faces in a BGR image frame.

        Returns:
            List of FaceMatchResult instances for each detected face.
        """
        results: list[FaceMatchResult] = []
        if frame_bgr is None or frame_bgr.size == 0:
            return results

        face_app = self.enrollment_mgr.get_face_app()

        try:
            detected_faces = face_app.get(frame_bgr)
        except Exception as exc:
            logger.error("Error during face detection in frame: %s", exc)
            return results

        with self.enrollment_mgr._lock:
            enrolled_ids = list(self.enrollment_mgr.student_ids)
            enrolled_embeddings = (
                self.enrollment_mgr.embeddings.copy()
                if self.enrollment_mgr.embeddings is not None and len(self.enrollment_mgr.embeddings) > 0
                else None
            )
            id_to_record = dict(self.enrollment_mgr.id_to_record)

        has_enrolled = (
            enrolled_ids is not None
            and len(enrolled_ids) > 0
            and enrolled_embeddings is not None
            and len(enrolled_embeddings) > 0
        )

        for face in detected_faces:
            # Check bounding box size
            bbox_raw = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox_raw[0], bbox_raw[1], bbox_raw[2], bbox_raw[3]
            width = x2 - x1
            height = y2 - y1

            if width < self.config.min_face_size_pixels or height < self.config.min_face_size_pixels:
                continue

            det_score = float(face.det_score) if hasattr(face, "det_score") else 1.0
            if det_score < self.config.det_thresh:
                continue

            embedding = face.embedding
            if embedding is None or len(embedding) == 0:
                continue

            # Normalize live embedding
            norm = np.linalg.norm(embedding)
            if norm == 0:
                continue
            norm_embedding = (embedding / norm).astype(np.float32)

            # Match against enrolled index
            if not has_enrolled:
                # No enrolled students in system
                results.append(
                    FaceMatchResult(
                        bbox=(x1, y1, x2, y2),
                        student_id=None,
                        name="Unknown",
                        similarity=0.0,
                        is_known=False,
                        is_ambiguous=False,
                        det_score=det_score,
                    )
                )
                continue

            # Cosine similarity matrix multiplication: (N, 512) dot (512,) -> (N,)
            scores = np.dot(enrolled_embeddings, norm_embedding)
            best_idx = int(np.argmax(scores))
            best_score = float(scores[best_idx])

            # Ambiguity check: if 2nd best candidate is very close to top candidate
            is_ambiguous = False
            if len(scores) > 1:
                sorted_indices = np.argsort(scores)[::-1]
                second_score = float(scores[sorted_indices[1]])
                # If both are above threshold and margin is less than 0.05
                if best_score >= self.config.recognition_threshold and (best_score - second_score) < 0.05:
                    is_ambiguous = True

            # Decide match based on calibrated threshold and ambiguity
            if best_score >= self.config.recognition_threshold and not is_ambiguous:
                matched_id = enrolled_ids[best_idx]
                matched_record = id_to_record.get(matched_id)
                matched_name = matched_record.name if matched_record else matched_id

                results.append(
                    FaceMatchResult(
                        bbox=(x1, y1, x2, y2),
                        student_id=matched_id,
                        name=matched_name,
                        similarity=best_score,
                        is_known=True,
                        is_ambiguous=False,
                        det_score=det_score,
                    )
                )
            else:
                # Reject as Unknown
                results.append(
                    FaceMatchResult(
                        bbox=(x1, y1, x2, y2),
                        student_id=None,
                        name="Unknown",
                        similarity=best_score,
                        is_known=False,
                        is_ambiguous=is_ambiguous,
                        det_score=det_score,
                    )
                )

        return results

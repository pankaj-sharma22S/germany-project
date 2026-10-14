"""Image Pipeline Runner.

Allows running face recognition and attendance logging on static image files
without requiring a live webcam (ideal for integration testing, CCTV frame processing,
and automated verification).
"""

from pathlib import Path
from typing import Optional
import cv2
import numpy as np

from app.attendance_manager import AttendanceManager
from app.config import Config
from app.enrollment import EnrollmentManager
from app.excel_service import ExcelService
from app.face_recognizer import FaceMatchResult, FaceRecognizer


class ImageAttendancePipeline:
    """End-to-end pipeline operating on still images instead of a camera."""

    def __init__(self, config: Config):
        self.config = config
        self.excel_service = ExcelService(
            project_root=config.project_root,
            registry_file=config.students_file,
            attendance_file=config.attendance_file,
        )
        self.enrollment_mgr = EnrollmentManager(config=config)
        self.face_recognizer = FaceRecognizer(
            config=config, enrollment_mgr=self.enrollment_mgr
        )
        self.attendance_mgr = AttendanceManager(
            config=config, excel_service=self.excel_service
        )

    def setup(self, force_rebuild: bool = False) -> int:
        """Initialize registry and enrollment index."""
        records, errors = self.excel_service.read_registry()
        count, enroll_errors = self.enrollment_mgr.load_or_rebuild_index(
            records, force_rebuild=force_rebuild
        )
        self.attendance_mgr.eligible_students = {r.student_id: r for r in records}
        self.attendance_mgr.start_worker()
        return count

    def process_image(
        self,
        image_path: Path,
        session_id: Optional[str] = None,
        simulate_confirmations: bool = True,
    ) -> tuple[np.ndarray, list[tuple[FaceMatchResult, str]]]:
        """Process a single image, recognize faces, and log attendance.

        Args:
            image_path: Path to image file.
            session_id: Optional session identifier.
            simulate_confirmations: If True, simulates meeting multi-frame confirmation
                                    requirement so a valid still photo marks attendance.

        Returns:
            (annotated_image, results_with_status)
        """
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot load image at '{image_path}'")

        if not self.attendance_mgr.is_session_active:
            self.attendance_mgr.start_session(session_id=session_id)

        raw_results = self.face_recognizer.process_frame(img)
        processed: list[tuple[FaceMatchResult, str]] = []

        for res in raw_results:
            if res.is_known and res.student_id:
                # If simulate_confirmations is set, loop confirmation frames
                repeat_count = (
                    self.config.confirmation_frames if simulate_confirmations else 1
                )
                att_status = "Verifying..."
                for _ in range(repeat_count):
                    att_status, _ = self.attendance_mgr.register_recognition(
                        student_id=res.student_id,
                        name=res.name,
                        similarity_score=res.similarity,
                    )
                processed.append((res, att_status))
            else:
                processed.append((res, "Unknown"))

        # Annotate image
        annotated = img.copy()
        for res, status in processed:
            x1, y1, x2, y2 = res.bbox
            color = (0, 200, 0) if res.is_known else (0, 0, 220)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f"{res.name} ({res.similarity:.2f}) [{status}]"
            cv2.putText(
                annotated,
                label,
                (x1, max(15, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
            )

        return annotated, processed

    def close(self) -> None:
        """Flush queue and release resources."""
        if self.attendance_mgr.is_session_active:
            self.attendance_mgr.stop_session(mark_absent=True)
        self.attendance_mgr.stop_worker()

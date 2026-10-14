"""Main application entry point.

Coordinates:
1. Configuration loading and directory setup.
2. Registry reading and validation.
3. Embeddings loading/rebuilding and live index updates.
4. Camera lifecycle, frame capture, and camera start/stop toggling.
5. Face tracking and movement dynamics (tracker.py).
6. Multi-frame stability decisions, timeout, and movement warnings (stability_manager.py).
7. Recognition with confirmed Excel persistence (attendance_manager.py).
8. Interactive UI with buttons, HUD overlays, and non-blocking Add Student form (ui.py).
9. Clean and safe resource shutdown.
"""

import argparse
import logging
from pathlib import Path
import sys
import time
from typing import Optional
import cv2
import numpy as np

from app.attendance_manager import AttendanceManager
from app.camera import VideoCamera
from app.config import Config, default_config
from app.enrollment import EnrollmentManager
from app.excel_service import ExcelService, StudentRecord
from app.face_recognizer import FaceMatchResult, FaceRecognizer
from app.stability_manager import FaceStabilityState, StabilityManager
from app.tracker import FaceTracker, TrackedFace
from app.ui import FaceRenderItem, UIOverlay


def setup_logging(level: str = "INFO") -> None:
    """Configure system-wide logging format."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command line options."""
    parser = argparse.ArgumentParser(description="Facial Attendance System (Working MVP)")
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="Webcam device index (default: 0)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.45,
        help="Recognition similarity threshold [0.0 - 1.0] (default: 0.45)",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Optional custom session identifier",
    )
    parser.add_argument(
        "--rebuild-embeddings",
        action="store_true",
        help="Force recomputation of reference embeddings",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without displaying OpenCV window (useful for automated testing)",
    )
    return parser.parse_args()


class AttendanceApp:
    """Master coordinator for the Facial Attendance System."""

    def __init__(self, config: Config, camera_index: int = 0, force_rebuild: bool = False):
        self.config = config
        self.config.camera_index = camera_index
        self.config.ensure_directories()
        self.force_rebuild = force_rebuild

        # Services & Managers
        self.excel_service = ExcelService(
            project_root=self.config.project_root,
            registry_file=self.config.students_file,
            attendance_file=self.config.attendance_file,
        )
        self.enrollment_mgr = EnrollmentManager(config=self.config)
        self.face_recognizer = FaceRecognizer(
            config=self.config, enrollment_mgr=self.enrollment_mgr
        )
        self.attendance_mgr = AttendanceManager(
            config=self.config, excel_service=self.excel_service
        )
        self.tracker = FaceTracker()
        self.stability_mgr = StabilityManager(config=self.config)

        self.camera = VideoCamera(
            camera_index=self.config.camera_index,
            width=self.config.camera_width,
            height=self.config.camera_height,
            fps=self.config.camera_fps,
            reconnect_attempts=self.config.camera_reconnect_attempts,
            reconnect_delay_sec=self.config.camera_reconnect_delay_sec,
        )
        self.camera_active = True

        self.ui = UIOverlay(config=self.config)
        self.records: list[StudentRecord] = []
        self.logger = logging.getLogger("AttendanceApp")

    def initialize(self) -> bool:
        """Load registry, enroll reference photos, and prepare camera."""
        self.logger.info("Initializing Facial Attendance System...")
        self.logger.info("Project Root: %s", self.config.project_root)
        self.logger.info("Session Timezone: %s", self.config.session_timezone)

        # 1. Read Registry
        self.records, errors = self.excel_service.read_registry()
        if errors:
            self.logger.warning("Registry validation warnings/errors:")
            for err in errors:
                self.logger.warning(" - %s", err)

        # 2. Load or Build Embeddings
        if self.records:
            count, enroll_errors = self.enrollment_mgr.load_or_rebuild_index(
                self.records, force_rebuild=self.force_rebuild
            )
            if enroll_errors:
                self.logger.warning("Enrollment issues encountered:")
                for err in enroll_errors:
                    self.logger.warning(" - %s", err)
            self.logger.info("Enrollment ready: %d students indexed.", count)
        else:
            self.logger.warning(
                "Registry has no valid records. Ensure %s exists with valid photos or use [Add Student].",
                self.config.students_file,
            )

        # 3. Start background persistence worker
        self.attendance_mgr.start_worker()
        return True

    def reload_registry(self) -> None:
        """Reload student registry and rebuild/refresh embeddings index."""
        self.logger.info("Reloading student registry and embeddings...")
        self.records, errors = self.excel_service.read_registry()
        if errors:
            for err in errors:
                self.logger.warning(" - %s", err)
        count, enroll_errors = self.enrollment_mgr.load_or_rebuild_index(
            self.records, force_rebuild=True
        )
        if self.attendance_mgr.is_session_active:
            self.attendance_mgr.eligible_students = {r.student_id: r for r in self.records}
        self.logger.info("Registry reloaded: %d students enrolled.", count)

    def _on_student_enrolled_runtime(self, student_id: str, name: str) -> None:
        """Callback when a new student is added via the runtime enrollment UI form."""
        self.logger.info("Runtime enrolled student: %s (%s)", name, student_id)
        # Update eligible students in active session immediately
        records, _ = self.excel_service.read_registry()
        self.records = records
        if self.attendance_mgr.is_session_active:
            self.attendance_mgr.eligible_students = {r.student_id: r for r in self.records}

    def run(self, initial_session_id: str | None = None, headless: bool = False) -> None:
        """Run the main capture and recognition loop."""
        if not self.initialize():
            self.logger.error("Initialization failed. Exiting.")
            return

        # Start camera
        if not self.camera.start():
            self.logger.error("Could not open camera device %s. Please check connection.", self.config.camera_index)
            self.camera_active = False
            if headless:
                self.shutdown()
                return

        if not headless:
            self.ui.setup_mouse_callback()

        # Start initial session automatically
        self.attendance_mgr.start_session(
            session_id=initial_session_id, eligible_records=self.records
        )

        status_msg: Optional[str] = "Session started. Press [Q] to exit."
        status_msg_time = time.time()

        self.logger.info("System loop starting. Press [Q] in UI to quit.")

        try:
            while True:
                # Clear status message after 5 seconds
                if status_msg and (time.time() - status_msg_time > 5.0):
                    status_msg = None

                # Check mouse button clicks
                clicked_action = self.ui.get_and_clear_action() if not headless else None

                frame: Optional[np.ndarray] = None

                if self.camera_active:
                    ret, frame = self.camera.read_frame()
                    if not ret or frame is None:
                        status_msg = "Camera disconnected. Retrying..."
                        status_msg_time = time.time()
                        time.sleep(0.08)
                        if headless:
                            break
                        # Provide a blank placeholder while reconnecting
                        frame = np.zeros((self.config.camera_height, self.config.camera_width, 3), dtype=np.uint8)
                        cv2.putText(
                            frame,
                            "Camera Reconnecting...",
                            (100, 300),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1.0,
                            (0, 0, 255),
                            2,
                        )
                else:
                    # Camera is intentionally stopped / paused
                    frame = np.zeros((self.config.camera_height, self.config.camera_width, 3), dtype=np.uint8)
                    cv2.putText(
                        frame,
                        "Camera Stopped. Click [Start Cam] or Press [C]",
                        (80, 340),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (180, 180, 180),
                        2,
                    )
                    time.sleep(0.04)

                # Track faces and evaluate stability if camera is active
                render_items: list[FaceRenderItem] = []

                if self.camera_active and frame is not None and frame.size > 0:
                    raw_results = self.face_recognizer.process_frame(frame)
                    bboxes = [r.bbox for r in raw_results]

                    # 1. Update temporal tracker
                    active_tracks = self.tracker.update(bboxes)
                    active_track_ids = [t.track_id for t in active_tracks]
                    self.stability_mgr.prune_lost_tracks(active_track_ids)

                    # Map bbox back to FaceMatchResult
                    bbox_to_match = {r.bbox: r for r in raw_results}

                    # 2. Evaluate stability per tracked face
                    for track in active_tracks:
                        decision = self.stability_mgr.update_face(track)
                        match_res = bbox_to_match.get(track.bbox)

                        # 3. Recognition & Confirmed Persistence trigger
                        if decision.ready_for_recognition:
                            if match_res and match_res.is_known and match_res.student_id:
                                # Submit event and WAIT for confirmed Excel write
                                att_msg, is_marked, err = self.attendance_mgr.confirm_and_write_attendance(
                                    student_id=match_res.student_id,
                                    name=match_res.name,
                                    similarity_score=match_res.similarity,
                                )
                                self.stability_mgr.mark_recognition_result(
                                    track_id=track.track_id,
                                    is_known=True,
                                    student_id=match_res.student_id,
                                    name=match_res.name,
                                    score=match_res.similarity,
                                    attendance_status=att_msg,
                                    error_msg=err,
                                )
                                if is_marked:
                                    status_msg = att_msg
                                    status_msg_time = time.time()
                            else:
                                # Unknown face
                                unknown_score = match_res.similarity if match_res else 0.0
                                self.stability_mgr.mark_recognition_result(
                                    track_id=track.track_id,
                                    is_known=False,
                                    student_id=None,
                                    name=None,
                                    score=unknown_score,
                                    attendance_status="Unknown face - attendance not marked",
                                )
                            # Refresh decision state after recognition
                            decision = self.stability_mgr.update_face(track)

                        render_items.append(
                            FaceRenderItem(
                                track_id=track.track_id,
                                bbox=track.bbox,
                                stability=decision,
                                match_result=match_res,
                            )
                        )

                if headless:
                    break

                # Render dashboard frame
                total_enrolled = len(self.enrollment_mgr.student_ids)
                display_frame = self.ui.create_dashboard_frame(
                    camera_frame=frame,
                    faces_to_render=render_items,
                    attendance_mgr=self.attendance_mgr,
                    total_enrolled=total_enrolled,
                    camera_active=self.camera_active,
                    status_msg=status_msg,
                )

                key = self.ui.show(display_frame)

                # Process keyboard and mouse inputs
                action = clicked_action
                if key in (ord("q"), ord("Q"), 27) or action == "exit":
                    self.logger.info("Exit command received.")
                    break
                elif key in (ord("a"), ord("A")) or action == "add_student":
                    self.ui.open_add_student_form(
                        enrollment_mgr=self.enrollment_mgr,
                        excel_service=self.excel_service,
                        on_enrolled_callback=self._on_student_enrolled_runtime,
                    )
                    status_msg = "Opened Add Student Enrollment dialog"
                    status_msg_time = time.time()
                elif key in (ord("c"), ord("C")) or action == "toggle_camera":
                    if self.camera_active:
                        self.camera.stop()
                        self.camera_active = False
                        self.tracker.reset()
                        self.stability_mgr.reset()
                        status_msg = "Camera stopped. Press [C] to restart."
                    else:
                        cam_ok = self.camera.start()
                        self.camera_active = cam_ok
                        status_msg = "Camera started." if cam_ok else "Failed to open camera."
                    status_msg_time = time.time()
                elif key in (ord("s"), ord("S")) or action == "start_session":
                    new_sess = self.attendance_mgr.start_session(eligible_records=self.records)
                    self.stability_mgr.reset()
                    status_msg = f"New session started: {new_sess}"
                    status_msg_time = time.time()
                elif key in (ord("p"), ord("P")) or action == "stop_session":
                    present, absent = self.attendance_mgr.stop_session(mark_absent=True)
                    self.stability_mgr.reset()
                    status_msg = f"Session stopped: {present} Present, {absent} Absent"
                    status_msg_time = time.time()
                elif key in (ord("r"), ord("R")) or action == "reload_registry":
                    self.reload_registry()
                    self.stability_mgr.reset()
                    status_msg = "Registry & Embeddings Reloaded"
                    status_msg_time = time.time()

        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Release camera, persist data, and destroy windows."""
        self.logger.info("Shutting down Facial Attendance System...")
        if self.attendance_mgr.is_session_active:
            self.attendance_mgr.stop_session(mark_absent=True)

        self.attendance_mgr.stop_worker(timeout_sec=3.0)
        self.camera.stop()
        self.ui.close()
        self.logger.info("All resources cleanly released. Goodbye!")


def main() -> None:
    args = parse_arguments()
    cfg = Config()
    cfg.recognition_threshold = args.threshold
    setup_logging(cfg.log_level)

    app = AttendanceApp(
        config=cfg,
        camera_index=args.camera,
        force_rebuild=args.rebuild_embeddings,
    )
    app.run(initial_session_id=args.session_id, headless=args.headless)


if __name__ == "__main__":
    main()

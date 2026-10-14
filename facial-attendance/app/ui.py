"""UI and Display Module.

Renders:
1. Webcam video feed with facial bounding boxes, landmarks, and status tags.
2. Color-coded bounding boxes per state:
   - Unknown (Red)
   - Recognized (Green)
   - Processing / Verifying / Movement warning (Gold/Yellow)
   - Attendance Confirmed (Bright Green)
3. Movement warnings ("Please stay still - face movement detected") and stability progress indicator.
4. Recognition loading indicator (driven by actual processing state).
5. Comprehensive real-time side dashboard:
   - Total enrolled students count
   - Session info, timezone, active state, camera state
   - Eligible, Present, Remaining counts
   - Recent attendance events feed with timestamps
   - Interactive buttons and hotkey guide ([A] Add Student, [C] Camera Toggle, [S] Start, [P] Stop, [Q] Quit)
6. Non-blocking Add Student runtime enrollment modal dialog with photo upload & validation.
"""

from dataclasses import dataclass
import threading
import time
from typing import Callable, Optional
import cv2
import numpy as np

from app.attendance_manager import AttendanceManager
from app.config import Config
from app.face_recognizer import FaceMatchResult
from app.stability_manager import FaceStabilityState, StabilityDecision


@dataclass
class FaceRenderItem:
    """Consolidated display data for a tracked face in a frame."""

    track_id: int
    bbox: tuple[int, int, int, int]
    stability: StabilityDecision
    match_result: Optional[FaceMatchResult] = None
    attendance_message: Optional[str] = None


class UIOverlay:
    """Renders video feed, side dashboard, and interactive controls."""

    COLOR_BG = (28, 30, 36)
    COLOR_PANEL_HEADER = (45, 52, 71)
    COLOR_TEXT = (240, 240, 240)
    COLOR_SUBTEXT = (180, 180, 180)
    COLOR_BTN_BG = (55, 65, 85)
    COLOR_BTN_HOVER = (70, 85, 115)
    COLOR_AMBER = (0, 215, 255)

    def __init__(self, config: Config):
        self.config = config
        self.window_name = "Facial Attendance System - Working MVP"
        self.panel_width = 400
        self.clicked_action: Optional[str] = None
        self._mouse_lock = threading.Lock()
        self._button_rects: dict[str, tuple[int, int, int, int]] = {}
        self._spinner_chars = ["|", "/", "-", "\\"]
        self._spinner_idx = 0
        self._last_spinner_time = time.time()
        self._is_dialog_open = False

    def setup_mouse_callback(self) -> None:
        """Register OpenCV mouse callback for clickable UI buttons."""
        try:
            cv2.namedWindow(self.window_name)
            cv2.setMouseCallback(self.window_name, self._on_mouse_click)
        except Exception:
            pass

    def _on_mouse_click(self, event: int, x: int, y: int, flags: int, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            with self._mouse_lock:
                for action, (bx1, by1, bx2, by2) in self._button_rects.items():
                    if bx1 <= x <= bx2 and by1 <= y <= by2:
                        self.clicked_action = action
                        break

    def get_and_clear_action(self) -> Optional[str]:
        """Retrieve and reset any button clicked via mouse."""
        with self._mouse_lock:
            act = self.clicked_action
            self.clicked_action = None
            return act

    def create_dashboard_frame(
        self,
        camera_frame: np.ndarray,
        faces_to_render: list[FaceRenderItem],
        attendance_mgr: AttendanceManager,
        total_enrolled: int,
        camera_active: bool = True,
        status_msg: Optional[str] = None,
    ) -> np.ndarray:
        """Compose annotated camera feed and telemetry panel side-by-side."""
        h, w = camera_frame.shape[:2]
        annotated_video = camera_frame.copy()

        # Update loading spinner
        if time.time() - self._last_spinner_time > 0.15:
            self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_chars)
            self._last_spinner_time = time.time()
        spinner = self._spinner_chars[self._spinner_idx]

        # 1. Annotate each face with stability and recognition info
        for item in faces_to_render:
            x1, y1, x2, y2 = item.bbox
            stab = item.stability
            match = item.match_result

            # Determine box color
            box_color = stab.box_color_bgr

            # Formulate top & bottom labels
            top_label = ""
            bot_label = ""

            if stab.state == FaceStabilityState.CONFIRMED:
                top_label = f"{match.name} ({match.student_id})" if match else "Confirmed"
                bot_label = f"Similarity: {match.similarity:.2f} | Confirmed" if match else "Attendance marked"
            elif stab.state == FaceStabilityState.ALREADY_MARKED:
                top_label = f"{match.name} ({match.student_id})" if match else "Already marked"
                bot_label = f"Similarity: {match.similarity:.2f} | Already marked" if match else "Already marked"
            elif stab.state == FaceStabilityState.UNKNOWN:
                top_label = "Unknown Face"
                score_str = f"Sim: {match.similarity:.2f}" if match else "No Match"
                bot_label = f"{score_str} (Below {self.config.recognition_threshold:.2f}) - Not marked"
            elif stab.state == FaceStabilityState.EXCESSIVE_MOVEMENT:
                top_label = "! Movement Detected !"
                bot_label = "Please stay still - face movement detected"
            elif stab.state == FaceStabilityState.TIMEOUT:
                top_label = "Stability Timeout"
                bot_label = "Please position yourself and stay still"
            elif stab.state in (FaceStabilityState.STABLE, FaceStabilityState.RECOGNIZING):
                top_label = f"Verifying Identity... [{spinner}]"
                bot_label = "Face stable - verifying identity..."
            else:  # STABILIZING / TRACKING
                percent = int(stab.progress * 100)
                # Text-based progress bar
                bar_len = 8
                filled = int(stab.progress * bar_len)
                bar_str = "=" * filled + ">" if filled < bar_len else "=" * bar_len
                top_label = f"Stabilizing [{bar_str:<9}] {percent}%"
                bot_label = "Stay still for verification..."

            # Draw bounding box
            cv2.rectangle(annotated_video, (x1, y1), (x2, y2), box_color, 2)

            # Top Badge
            badge_h = 24
            badge_y1 = max(0, y1 - badge_h)
            badge_y2 = y1
            cv2.rectangle(annotated_video, (x1, badge_y1), (x2, badge_y2), box_color, -1)
            cv2.putText(
                annotated_video,
                top_label,
                (x1 + 4, max(14, badge_y2 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 0, 0) if box_color == self.config.color_box_processing else (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

            # Bottom Subtext Banner
            cv2.rectangle(annotated_video, (x1, y2), (x2, y2 + 22), (20, 20, 20), -1)
            cv2.putText(
                annotated_video,
                bot_label,
                (x1 + 4, y2 + 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                (220, 220, 220),
                1,
                cv2.LINE_AA,
            )

        # 2. Build Side Panel
        panel = np.zeros((h, self.panel_width, 3), dtype=np.uint8)
        panel[:] = self.COLOR_BG

        # Panel Header
        cv2.rectangle(panel, (0, 0), (self.panel_width, 70), self.COLOR_PANEL_HEADER, -1)
        cv2.putText(
            panel,
            "ATTENDANCE SYSTEM",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            panel,
            f"Enrolled: {total_enrolled} | TZ: {self.config.session_timezone}",
            (15, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            self.COLOR_SUBTEXT,
            1,
            cv2.LINE_AA,
        )

        stats = attendance_mgr.get_stats()
        is_active = stats["is_active"]
        sess_id = stats["session_id"]

        # Session & Camera Status Line
        y_cursor = 95
        state_color = self.config.color_box_recognized if is_active else self.config.color_box_unknown
        cv2.putText(
            panel,
            f"SESSION: {'ACTIVE' if is_active else 'INACTIVE'}",
            (15, y_cursor),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            state_color,
            2,
            cv2.LINE_AA,
        )

        cam_text = "CAM: ON" if camera_active else "CAM: OFF"
        cam_color = self.config.color_box_recognized if camera_active else self.config.color_box_unknown
        cv2.putText(
            panel,
            cam_text,
            (self.panel_width - 100, y_cursor),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            cam_color,
            2,
            cv2.LINE_AA,
        )

        y_cursor += 20
        cv2.putText(
            panel,
            f"ID: {sess_id[:26]}",
            (15, y_cursor),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            self.COLOR_TEXT,
            1,
            cv2.LINE_AA,
        )

        # Metrics cards
        y_cursor += 30
        card_w = (self.panel_width - 40) // 3
        metrics = [
            ("ELIGIBLE", str(stats["eligible"]), (70, 70, 70)),
            ("PRESENT", str(stats["present"]), (35, 120, 70)),
            ("REMAINING", str(stats["remaining"]), (40, 70, 130)),
        ]

        for i, (m_label, m_val, m_bg) in enumerate(metrics):
            cx = 15 + i * (card_w + 5)
            cv2.rectangle(panel, (cx, y_cursor), (cx + card_w, y_cursor + 48), m_bg, -1)
            cv2.putText(
                panel,
                m_label,
                (cx + 6, y_cursor + 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (220, 220, 220),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                panel,
                m_val,
                (cx + 12, y_cursor + 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        # Interactive UI Buttons (Register rects for click handling)
        y_cursor += 65
        btn_h = 32
        half_w = (self.panel_width - 35) // 2

        # Button 1: Add Student
        b1_x1, b1_y1 = 15, y_cursor
        b1_x2, b1_y2 = 15 + half_w, y_cursor + btn_h
        cv2.rectangle(panel, (b1_x1, b1_y1), (b1_x2, b1_y2), (40, 110, 60), -1)
        cv2.putText(
            panel,
            "[A] Add Student",
            (b1_x1 + 10, b1_y1 + 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # Button 2: Camera Toggle
        b2_x1, b2_y1 = 20 + half_w, y_cursor
        b2_x2, b2_y2 = 20 + 2 * half_w, y_cursor + btn_h
        cam_btn_bg = (100, 40, 40) if camera_active else (40, 100, 40)
        cv2.rectangle(panel, (b2_x1, b2_y1), (b2_x2, b2_y2), cam_btn_bg, -1)
        cv2.putText(
            panel,
            "[C] Stop Cam" if camera_active else "[C] Start Cam",
            (b2_x1 + 10, b2_y1 + 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # Button 3 & 4: Start Session & Stop Session
        y_cursor += 38
        b3_x1, b3_y1 = 15, y_cursor
        b3_x2, b3_y2 = 15 + half_w, y_cursor + btn_h
        cv2.rectangle(panel, (b3_x1, b3_y1), (b3_x2, b3_y2), self.COLOR_BTN_BG, -1)
        cv2.putText(
            panel,
            "[S] Start Sess",
            (b3_x1 + 10, b3_y1 + 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        b4_x1, b4_y1 = 20 + half_w, y_cursor
        b4_x2, b4_y2 = 20 + 2 * half_w, y_cursor + btn_h
        cv2.rectangle(panel, (b4_x1, b4_y1), (b4_x2, b4_y2), self.COLOR_BTN_BG, -1)
        cv2.putText(
            panel,
            "[P] Stop Sess",
            (b4_x1 + 12, b4_y1 + 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # Update button bounds mapping (coordinates shifted by w for window space)
        with self._mouse_lock:
            self._button_rects = {
                "add_student": (w + b1_x1, b1_y1, w + b1_x2, b1_y2),
                "toggle_camera": (w + b2_x1, b2_y1, w + b2_x2, b2_y2),
                "start_session": (w + b3_x1, b3_y1, w + b3_x2, b3_y2),
                "stop_session": (w + b4_x1, b4_y1, w + b4_x2, b4_y2),
            }

        # Recent Marks Feed
        y_cursor += 50
        cv2.putText(
            panel,
            "RECENT MARKS (CONFIRMED ON DISK)",
            (15, y_cursor),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            self.COLOR_SUBTEXT,
            1,
            cv2.LINE_AA,
        )
        cv2.line(panel, (15, y_cursor + 6), (self.panel_width - 15, y_cursor + 6), (60, 60, 60), 1)

        y_cursor += 22
        recent = stats["recent_events"][:5]
        if not recent:
            cv2.putText(
                panel,
                "No marks recorded yet",
                (15, y_cursor),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                (120, 120, 120),
                1,
                cv2.LINE_AA,
            )
            y_cursor += 20
        else:
            for ev in recent:
                ev_str = f"[{ev.time_str}] {ev.student_id} {ev.name[:11]} ({ev.match_score:.2f})"
                color = self.config.color_box_recognized if ev.status == "Present" else self.config.color_box_unknown
                cv2.putText(
                    panel,
                    ev_str,
                    (15, y_cursor),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    color,
                    1,
                    cv2.LINE_AA,
                )
                y_cursor += 20

        # Status Message Banner
        if status_msg:
            y_cursor += 15
            cv2.rectangle(panel, (12, y_cursor - 14), (self.panel_width - 12, y_cursor + 18), (40, 40, 40), -1)
            cv2.putText(
                panel,
                status_msg[:44],
                (16, y_cursor + 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.40,
                self.COLOR_AMBER,
                1,
                cv2.LINE_AA,
            )

        # Bottom Key Controls
        ctrl_y = h - 85
        cv2.line(panel, (15, ctrl_y - 8), (self.panel_width - 15, ctrl_y - 8), (60, 60, 60), 1)
        controls = [
            "[A] Add Student  |  [C] Cam Toggle",
            "[S] Start Sess   |  [P] Stop Sess",
            "[R] Reload Index |  [Q] Exit App",
        ]
        for ctrl in controls:
            cv2.putText(
                panel,
                ctrl,
                (15, ctrl_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                (190, 190, 190),
                1,
                cv2.LINE_AA,
            )
            ctrl_y += 18

        combined = np.hstack([annotated_video, panel])
        return combined

    def open_add_student_form(
        self,
        enrollment_mgr,
        excel_service,
        on_enrolled_callback: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Launch the non-blocking Add Student GUI form in a background thread."""
        if self._is_dialog_open:
            return

        def _run_form():
            self._is_dialog_open = True
            try:
                import tkinter as tk
                from tkinter import filedialog, messagebox

                root = tk.Tk()
                root.title("Add Student - Runtime Enrollment")
                root.geometry("480x360")
                root.resizable(False, False)

                # Modern dark-ish styling
                root.configure(bg="#20222a")

                # Header
                header = tk.Label(
                    root,
                    text="Runtime Student Enrollment",
                    font=("Segoe UI", 13, "bold"),
                    fg="#ffffff",
                    bg="#20222a",
                )
                header.pack(pady=12)

                frame = tk.Frame(root, bg="#20222a")
                frame.pack(padx=24, pady=5, fill="x")

                # Student ID
                lbl_id = tk.Label(frame, text="Student ID:", fg="#d0d0d0", bg="#20222a", font=("Segoe UI", 10))
                lbl_id.grid(row=0, column=0, sticky="w", pady=6)
                entry_id = tk.Entry(frame, width=32, font=("Segoe UI", 10))
                entry_id.grid(row=0, column=1, pady=6, padx=8)

                # Full Name
                lbl_name = tk.Label(frame, text="Full Name:", fg="#d0d0d0", bg="#20222a", font=("Segoe UI", 10))
                lbl_name.grid(row=1, column=0, sticky="w", pady=6)
                entry_name = tk.Entry(frame, width=32, font=("Segoe UI", 10))
                entry_name.grid(row=1, column=1, pady=6, padx=8)

                # Photo Path
                lbl_photo = tk.Label(frame, text="Photo File:", fg="#d0d0d0", bg="#20222a", font=("Segoe UI", 10))
                lbl_photo.grid(row=2, column=0, sticky="w", pady=6)
                photo_frame = tk.Frame(frame, bg="#20222a")
                photo_frame.grid(row=2, column=1, pady=6, padx=8, sticky="w")

                entry_photo = tk.Entry(photo_frame, width=22, font=("Segoe UI", 10))
                entry_photo.pack(side="left")

                def _browse():
                    f = filedialog.askopenfilename(
                        title="Select Reference Image",
                        filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp *.webp")],
                    )
                    if f:
                        entry_photo.delete(0, tk.END)
                        entry_photo.insert(0, f)

                btn_browse = tk.Button(photo_frame, text="Browse...", command=_browse, bg="#455271", fg="#ffffff")
                btn_browse.pack(side="left", padx=4)

                # Feedback label
                lbl_feedback = tk.Label(
                    root,
                    text="",
                    fg="#ffcc00",
                    bg="#20222a",
                    font=("Segoe UI", 9),
                    wraplength=440,
                )
                lbl_feedback.pack(pady=10)

                # Buttons Frame
                btn_frame = tk.Frame(root, bg="#20222a")
                btn_frame.pack(pady=10)

                def _save():
                    sid = entry_id.get().strip()
                    name = entry_name.get().strip()
                    p_path = entry_photo.get().strip()

                    lbl_feedback.config(text="Extracting face & generating embedding...", fg="#00d7ff")
                    root.update()

                    success, msg = enrollment_mgr.enroll_single_student(
                        student_id=sid,
                        name=name,
                        image_input=p_path,
                        excel_service=excel_service,
                    )

                    if success:
                        lbl_feedback.config(text=f"Success: {msg}", fg="#2ecc71")
                        if on_enrolled_callback:
                            on_enrolled_callback(sid, name)
                        root.after(1600, root.destroy)
                    else:
                        lbl_feedback.config(text=f"Error: {msg}", fg="#ff4d4d")

                btn_save = tk.Button(
                    btn_frame,
                    text="Save & Enroll",
                    command=_save,
                    bg="#2ecc71",
                    fg="#ffffff",
                    font=("Segoe UI", 10, "bold"),
                    width=14,
                )
                btn_save.pack(side="left", padx=10)

                btn_cancel = tk.Button(
                    btn_frame,
                    text="Cancel",
                    command=root.destroy,
                    bg="#555555",
                    fg="#ffffff",
                    font=("Segoe UI", 10),
                    width=10,
                )
                btn_cancel.pack(side="left", padx=10)

                # Focus and run loop
                entry_id.focus_set()
                root.mainloop()
            except Exception as exc:
                print("Error opening Add Student dialog:", exc)
            finally:
                self._is_dialog_open = False

        threading.Thread(target=_run_form, daemon=True, name="AddStudentGUI").start()

    def show(self, frame: np.ndarray) -> int:
        """Display the frame and return pressed key code."""
        cv2.imshow(self.window_name, frame)
        return cv2.waitKey(1) & 0xFF

    def close(self) -> None:
        """Destroy UI windows."""
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

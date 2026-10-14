"""Application Configuration module.

Centralizes all filesystem paths, camera parameters, face recognition thresholds,
and session management settings.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import time


def get_default_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    # Assuming config.py is in <project_root>/app/
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    """Configuration settings for the facial attendance application."""

    # Project Root and Directories
    project_root: Path = field(default_factory=get_default_project_root)
    
    # Input and Output Paths (relative to project_root by default)
    data_dir_name: str = "data"
    students_file_name: str = "students.xlsx"
    photos_dir_name: str = "photos"
    embeddings_file_name: str = "embeddings.npz"
    attendance_file_name: str = "attendance.xlsx"

    # Camera Settings
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 30
    camera_reconnect_attempts: int = 3
    camera_reconnect_delay_sec: float = 1.0

    # Face Recognition Model Settings
    # InsightFace model pack: 'buffalo_s' (fast and lightweight) or 'buffalo_l' (high accuracy)
    model_name: str = "buffalo_s"
    detection_size: tuple[int, int] = (640, 640)
    det_thresh: float = 0.5
    # Recognition cosine similarity threshold: Matches >= threshold are accepted
    # InsightFace 512-d embeddings are normalized, so cosine similarity ranges [-1, 1].
    # Genuine pairs typically score > 0.45 - 0.50. Impostors typically score < 0.35.
    recognition_threshold: float = 0.45
    min_face_size_pixels: int = 45

    # Attendance Session & Confirmation Rules
    # Require face to be recognized consistently across multiple frames to avoid spurious triggers
    confirmation_frames: int = 3
    # Time window (seconds) within which confirmation frames must occur
    confirmation_window_sec: float = 3.0
    # Documented session timezone
    session_timezone: str = time.tzname[0] if time.tzname else "UTC"
    session_id_prefix: str = "SES_"

    # Stability and Movement Check Settings
    stability_duration_seconds: float = 1.0  # Minimum seconds face must remain stable
    max_center_movement_px: float = 28.0     # Max box-center shift in pixels between frames
    max_size_change_ratio: float = 0.18      # Max relative bounding box size change ratio
    stability_timeout_seconds: float = 8.0   # Max seconds allowed to reach stability before prompting
    required_stable_frames: int = 4          # Minimum consecutive stable observations

    # Box Colors per State (BGR)
    color_box_unknown: tuple[int, int, int] = (60, 60, 231)      # Red for unknown
    color_box_recognized: tuple[int, int, int] = (46, 204, 113)  # Green for recognized
    color_box_processing: tuple[int, int, int] = (0, 215, 255)   # Gold/Yellow for processing / verifying
    color_box_confirmed: tuple[int, int, int] = (0, 255, 0)      # Bright Green for confirmed attendance

    # Aliases for prompt uppercase compatibility
    @property
    def STABILITY_DURATION_SECONDS(self) -> float:
        return self.stability_duration_seconds

    @property
    def MAX_CENTER_MOVEMENT_PX(self) -> float:
        return self.max_center_movement_px

    @property
    def MAX_SIZE_CHANGE_RATIO(self) -> float:
        return self.max_size_change_ratio

    @property
    def STABILITY_TIMEOUT_SECONDS(self) -> float:
        return self.stability_timeout_seconds

    @property
    def REQUIRED_STABLE_FRAMES(self) -> int:
        return self.required_stable_frames

    # Logging and Threading
    log_level: str = "INFO"
    queue_timeout_sec: float = 0.5

    @property
    def data_dir(self) -> Path:
        return self.project_root / self.data_dir_name

    @property
    def students_file(self) -> Path:
        return self.data_dir / self.students_file_name

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / self.photos_dir_name

    @property
    def embeddings_file(self) -> Path:
        return self.data_dir / self.embeddings_file_name

    @property
    def attendance_file(self) -> Path:
        return self.data_dir / self.attendance_file_name

    def ensure_directories(self) -> None:
        """Create necessary project directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)


# Default global instance
default_config = Config()

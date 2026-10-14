"""Camera capture module.

Handles:
1. Thread-safe OpenCV video capture.
2. Graceful initialization and failure recovery.
3. Clean resource acquisition and release.
4. No Excel or recognition business logic.
"""

import logging
import threading
import time
from typing import Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraError(Exception):
    """Exception raised for camera hardware or capture errors."""


class VideoCamera:
    """Manages OpenCV VideoCapture with auto-reconnection and thread-safe frame reading."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        reconnect_attempts: int = 3,
        reconnect_delay_sec: float = 1.0,
    ):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.reconnect_attempts = reconnect_attempts
        self.reconnect_delay_sec = reconnect_delay_sec

        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._is_opened = False

    def start(self) -> bool:
        """Initialize and open the video capture device."""
        with self._lock:
            if self._cap is not None and self._cap.isOpened():
                return True

            logger.info("Opening camera device %s...", self.camera_index)
            # Try DirectShow first on Windows for faster initialization, then default
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera_index)

            if not cap.isOpened():
                logger.error("Failed to open camera index %s", self.camera_index)
                return False

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)

            self._cap = cap
            self._is_opened = True
            logger.info(
                "Camera %s opened successfully (target: %dx%d @ %d FPS)",
                self.camera_index,
                self.width,
                self.height,
                self.fps,
            )
            return True

    def read_frame(self) -> tuple[bool, Optional[np.ndarray]]:
        """Read a single frame from the camera.

        Attempts automatic reconnection if capture fails.

        Returns:
            (success, frame): True and BGR numpy array if captured, False and None otherwise.
        """
        with self._lock:
            if self._cap is None or not self._cap.isOpened():
                if not self._reconnect():
                    return False, None

            ret, frame = self._cap.read()
            if not ret or frame is None or frame.size == 0:
                logger.warning("Camera read returned empty frame. Attempting recovery...")
                if self._reconnect():
                    ret, frame = self._cap.read()
                    if ret and frame is not None:
                        return True, frame
                return False, None

            return True, frame

    def _reconnect(self) -> bool:
        """Attempt to re-initialize the camera device."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        for attempt in range(1, self.reconnect_attempts + 1):
            logger.info("Camera reconnection attempt %d/%d...", attempt, self.reconnect_attempts)
            time.sleep(self.reconnect_delay_sec)
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(self.camera_index)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self._cap = cap
                self._is_opened = True
                logger.info("Camera successfully reconnected.")
                return True

        self._is_opened = False
        logger.error("Failed to reconnect camera after %d attempts.", self.reconnect_attempts)
        return False

    def stop(self) -> None:
        """Release camera resources cleanly."""
        with self._lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception as exc:
                    logger.warning("Error releasing camera: %s", exc)
                self._cap = None
            self._is_opened = False
            logger.info("Camera device released.")

    def is_opened(self) -> bool:
        with self._lock:
            return self._cap is not None and self._cap.isOpened()

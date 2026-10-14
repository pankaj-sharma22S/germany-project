"""Stability Manager Module.

Manages stability decisions per tracked face:
1. Movement detection and counter/timer resets.
2. Stability progress evaluation (duration + frame count).
3. Timeout handling.
4. State transitions: Tracking -> Movement Warning -> Stable -> Recognition -> Confirmation.
"""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Optional

from app.config import Config
from app.tracker import TrackedFace


class FaceStabilityState(str, Enum):
    """Lifecycle states of a tracked face."""

    TRACKING = "tracking"
    EXCESSIVE_MOVEMENT = "excessive_movement"
    STABILIZING = "stabilizing"
    TIMEOUT = "timeout"
    STABLE = "stable"
    RECOGNIZING = "recognizing"
    CONFIRMED = "confirmed"
    ALREADY_MARKED = "already_marked"
    UNKNOWN = "unknown"
    WRITE_FAILED = "write_failed"


@dataclass
class StabilityDecision:
    """Evaluation result for a single tracked face."""

    track_id: int
    state: FaceStabilityState
    feedback_message: str
    stable_frames: int
    stable_duration: float
    progress: float  # 0.0 to 1.0
    ready_for_recognition: bool
    box_color_bgr: tuple[int, int, int]


class StabilityManager:
    """Monitors face stability dynamics and dictates recognition timing."""

    def __init__(self, config: Config):
        self.config = config
        # track_id -> dict of tracker stability attributes
        self._states: dict[int, dict] = {}

    def update_face(self, track: TrackedFace) -> StabilityDecision:
        """Evaluate stability for a tracked face in the current frame."""
        now = time.time()
        t_id = track.track_id

        if t_id not in self._states:
            # Initialize tracking state
            self._states[t_id] = {
                "first_seen_time": now,
                "streak_start_time": now,
                "stable_frames": 0,
                "state": FaceStabilityState.TRACKING,
                "last_message": "Tracking face...",
                "recognized_id": None,
                "recognized_name": None,
                "recognized_score": 0.0,
                "already_marked": False,
                "attendance_confirmed": False,
                "unknown_rejected": False,
                "write_error": None,
            }

        rec = self._states[t_id]

        # 1. If face is already confirmed, already marked, or marked unknown in this track, preserve terminal state
        if rec["attendance_confirmed"]:
            name = rec["recognized_name"] or rec["recognized_id"]
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.CONFIRMED,
                feedback_message=f"Attendance marked successfully - {name} ({rec['recognized_id']})",
                stable_frames=rec["stable_frames"],
                stable_duration=self.config.stability_duration_seconds,
                progress=1.0,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_confirmed,
            )

        if rec["already_marked"]:
            name = rec["recognized_name"] or rec["recognized_id"]
            name_suffix = f" - {name} ({rec['recognized_id']})" if name else ""
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.ALREADY_MARKED,
                feedback_message=f"Already marked present{name_suffix}",
                stable_frames=rec["stable_frames"],
                stable_duration=self.config.stability_duration_seconds,
                progress=1.0,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_confirmed,
            )

        if rec["unknown_rejected"]:
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.UNKNOWN,
                feedback_message="Unknown face - attendance not marked",
                stable_frames=rec["stable_frames"],
                stable_duration=self.config.stability_duration_seconds,
                progress=1.0,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_unknown,
            )

        if rec["write_error"]:
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.WRITE_FAILED,
                feedback_message=f"Write error: {rec['write_error']}",
                stable_frames=rec["stable_frames"],
                stable_duration=0.0,
                progress=0.0,
                ready_for_recognition=True,  # Allow retry
                box_color_bgr=self.config.color_box_unknown,
            )

        # 2. Check for excessive movement
        # Use both absolute pixel movement and normalized scale to allow natural minor breathing/head movement
        is_excessive_shift = (
            track.center_displacement_px > self.config.max_center_movement_px
            and track.normalized_movement > 0.16
        )
        is_excessive_scale = track.size_change_ratio > self.config.max_size_change_ratio

        if (is_excessive_shift or is_excessive_scale) and track.frames_tracked > 1:
            # Reset stability counters
            rec["streak_start_time"] = now
            rec["stable_frames"] = 0
            rec["state"] = FaceStabilityState.EXCESSIVE_MOVEMENT
            rec["last_message"] = "Please stay still - face movement detected"

            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.EXCESSIVE_MOVEMENT,
                feedback_message=rec["last_message"],
                stable_frames=0,
                stable_duration=0.0,
                progress=0.0,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_processing,
            )

        # 3. Movement is within acceptable threshold -> increment stable frames
        rec["stable_frames"] += 1
        stable_duration = now - rec["streak_start_time"]
        total_tracked_time = now - rec["first_seen_time"]

        # Check timeout
        if (
            total_tracked_time > self.config.stability_timeout_seconds
            and stable_duration < self.config.stability_duration_seconds
        ):
            rec["state"] = FaceStabilityState.TIMEOUT
            rec["last_message"] = (
                "Unable to stabilize face. Please position yourself and try again"
            )
            # Soft reset streak so user can stabilize
            rec["first_seen_time"] = now
            rec["streak_start_time"] = now
            rec["stable_frames"] = 0

            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.TIMEOUT,
                feedback_message=rec["last_message"],
                stable_frames=0,
                stable_duration=0.0,
                progress=0.0,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_processing,
            )

        # Compute progress towards stability (0.0 to 1.0)
        time_ratio = min(1.0, stable_duration / max(0.001, self.config.stability_duration_seconds))
        frame_ratio = min(1.0, rec["stable_frames"] / max(1, self.config.required_stable_frames))
        progress = (time_ratio + frame_ratio) / 2.0

        # Check if BOTH duration and frame-count requirements are satisfied
        if (
            stable_duration >= self.config.stability_duration_seconds
            and rec["stable_frames"] >= self.config.required_stable_frames
        ):
            rec["state"] = FaceStabilityState.STABLE
            rec["last_message"] = "Face stable - verifying identity..."
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.STABLE,
                feedback_message=rec["last_message"],
                stable_frames=rec["stable_frames"],
                stable_duration=stable_duration,
                progress=1.0,
                ready_for_recognition=True,
                box_color_bgr=self.config.color_box_processing,
            )
        else:
            rec["state"] = FaceStabilityState.STABILIZING
            percent = int(progress * 100)
            rec["last_message"] = f"Stabilizing face ({percent}%)... Stay still"
            return StabilityDecision(
                track_id=t_id,
                state=FaceStabilityState.STABILIZING,
                feedback_message=rec["last_message"],
                stable_frames=rec["stable_frames"],
                stable_duration=stable_duration,
                progress=progress,
                ready_for_recognition=False,
                box_color_bgr=self.config.color_box_processing,
            )

    def mark_recognition_result(
        self,
        track_id: int,
        is_known: bool,
        student_id: Optional[str],
        name: Optional[str],
        score: float,
        attendance_status: str,
        error_msg: Optional[str] = None,
    ) -> None:
        """Update stability record with the outcome of recognition & attendance write."""
        if track_id not in self._states:
            return

        rec = self._states[track_id]
        rec["recognized_id"] = student_id
        rec["recognized_name"] = name
        rec["recognized_score"] = score

        if not is_known or not student_id:
            rec["unknown_rejected"] = True
            rec["state"] = FaceStabilityState.UNKNOWN
        elif "already marked" in attendance_status.lower():
            rec["already_marked"] = True
            rec["state"] = FaceStabilityState.ALREADY_MARKED
        elif "marked successfully" in attendance_status.lower() or attendance_status == "Present":
            rec["attendance_confirmed"] = True
            rec["state"] = FaceStabilityState.CONFIRMED
        elif error_msg:
            rec["write_error"] = error_msg
            rec["state"] = FaceStabilityState.WRITE_FAILED

    def prune_lost_tracks(self, active_track_ids: list[int]) -> None:
        """Remove state for tracks that have disappeared from the frame."""
        active_set = set(active_track_ids)
        for t_id in list(self._states.keys()):
            if t_id not in active_set:
                del self._states[t_id]

    def reset(self) -> None:
        """Reset all stability records."""
        self._states.clear()

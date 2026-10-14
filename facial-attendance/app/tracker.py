"""Face Tracking Module.

Provides temporal face association across video frames using bounding box IoU
and centroid tracking, and computes frame-to-frame movement metrics.
"""

from dataclasses import dataclass
import math
import time
from typing import Optional


@dataclass
class TrackedFace:
    """Represents a tracked face instance across consecutive frames."""

    track_id: int
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    prev_bbox: Optional[tuple[int, int, int, int]] = None
    center_displacement_px: float = 0.0
    size_change_ratio: float = 0.0
    normalized_movement: float = 0.0
    frames_tracked: int = 1
    lost_frames: int = 0
    first_seen_time: float = 0.0
    last_seen_time: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    @property
    def width(self) -> int:
        return max(1, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> int:
        return max(1, self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> float:
        return float(self.width * self.height)


def compute_iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    """Compute Intersection-over-Union between two bounding boxes."""
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])

    inter_w = max(0, xb - xa)
    inter_h = max(0, yb - ya)
    inter_area = inter_w * inter_h

    area_a = max(1, (box_a[2] - box_a[0]) * (box_a[3] - box_a[1]))
    area_b = max(1, (box_b[2] - box_b[0]) * (box_b[3] - box_b[1]))

    union_area = float(area_a + area_b - inter_area)
    return float(inter_area) / union_area if union_area > 0 else 0.0


class FaceTracker:
    """Multi-face tracker maintaining persistent IDs and motion dynamics across frames."""

    def __init__(self, iou_threshold: float = 0.35, max_lost_frames: int = 5):
        self.iou_threshold = iou_threshold
        self.max_lost_frames = max_lost_frames
        self._next_track_id = 1
        self.tracks: dict[int, TrackedFace] = {}

    def update(self, detected_bboxes: list[tuple[int, int, int, int]]) -> list[TrackedFace]:
        """Update tracker with new detections from the current frame.

        Returns:
            List of actively matched or newly created TrackedFace instances for this frame.
        """
        now = time.time()
        active_track_ids = list(self.tracks.keys())
        matched_detections: set[int] = set()
        matched_tracks: set[int] = set()

        # Build cost matrix with hybrid IoU and centroid proximity
        matches: list[tuple[float, int, int]] = []  # (score, track_id, det_idx)
        for t_id in active_track_ids:
            track = self.tracks[t_id]
            tcx, tcy = track.center
            ref_dim = max(track.width, track.height, 1)
            for d_idx, d_box in enumerate(detected_bboxes):
                iou = compute_iou(track.bbox, d_box)
                dcx = (d_box[0] + d_box[2]) / 2.0
                dcy = (d_box[1] + d_box[3]) / 2.0
                dist = math.sqrt((dcx - tcx) ** 2 + (dcy - tcy) ** 2)

                # Match if significant IoU or within neighborhood radius
                if iou >= self.iou_threshold or dist < (ref_dim * 1.2):
                    score = (iou * 2.0) + max(0.0, 1.0 - (dist / (ref_dim * 2.0)))
                    matches.append((score, t_id, d_idx))

        # Greedy match by highest IoU first
        matches.sort(key=lambda x: x[0], reverse=True)
        for iou, t_id, d_idx in matches:
            if t_id in matched_tracks or d_idx in matched_detections:
                continue

            matched_tracks.add(t_id)
            matched_detections.add(d_idx)

            # Update existing track
            track = self.tracks[t_id]
            prev_box = track.bbox
            prev_cx, prev_cy = track.center
            prev_area = track.area

            track.prev_bbox = prev_box
            track.bbox = detected_bboxes[d_idx]
            new_cx, new_cy = track.center
            new_area = track.area

            # Displacement
            disp_px = math.sqrt((new_cx - prev_cx) ** 2 + (new_cy - prev_cy) ** 2)
            track.center_displacement_px = disp_px

            # Size change
            area_diff = abs(new_area - prev_area)
            track.size_change_ratio = area_diff / max(prev_area, 1.0)

            # Normalized movement relative to face scale
            ref_scale = min(track.width, track.height)
            track.normalized_movement = disp_px / max(ref_scale, 1.0)

            track.frames_tracked += 1
            track.lost_frames = 0
            track.last_seen_time = now

        # Add new tracks for unmatched detections
        current_frame_tracks: list[TrackedFace] = []
        for d_idx, d_box in enumerate(detected_bboxes):
            if d_idx in matched_detections:
                continue

            new_track = TrackedFace(
                track_id=self._next_track_id,
                bbox=d_box,
                prev_bbox=None,
                center_displacement_px=0.0,
                size_change_ratio=0.0,
                normalized_movement=0.0,
                frames_tracked=1,
                lost_frames=0,
                first_seen_time=now,
                last_seen_time=now,
            )
            self.tracks[self._next_track_id] = new_track
            self._next_track_id += 1
            current_frame_tracks.append(new_track)

        # Include matched tracks in active list
        for t_id in matched_tracks:
            current_frame_tracks.append(self.tracks[t_id])

        # Increment lost frames for unmatched existing tracks and prune
        tracks_to_delete = []
        for t_id in active_track_ids:
            if t_id not in matched_tracks:
                self.tracks[t_id].lost_frames += 1
                if self.tracks[t_id].lost_frames > self.max_lost_frames:
                    tracks_to_delete.append(t_id)

        for t_id in tracks_to_delete:
            del self.tracks[t_id]

        return current_frame_tracks

    def reset(self) -> None:
        """Clear all active tracks."""
        self.tracks.clear()
        self._next_track_id = 1

"""Attendance Manager module.

Handles:
1. Multi-frame recognition stability confirmation.
2. In-memory session tracking and duplicate-attendance prevention.
3. Thread-safe event queue and asynchronous single-writer Excel worker.
4. Session lifecycle (start, stop, optional absent marking).
5. Clean resource shutdown and queue flushing.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import logging
from queue import Empty, Queue
import threading
import time
from typing import Optional

from app.config import Config
from app.excel_service import AttendanceEvent, ExcelService, StudentRecord

logger = logging.getLogger(__name__)


@dataclass
class RecognitionObservation:
    """Tracks recent frame detections of a student for temporal stability."""

    student_id: str
    timestamp: float
    score: float


class AttendanceManager:
    """Coordinates session state, stability confirmation, and Excel persistence."""

    def __init__(self, config: Config, excel_service: ExcelService):
        self.config = config
        self.excel_service = excel_service

        # Session State
        self.session_id: Optional[str] = None
        self.is_session_active: bool = False
        self.session_start_time: Optional[datetime] = None
        self.eligible_students: dict[str, StudentRecord] = {}
        self.present_student_ids: set[str] = set()

        # Stability Tracking: student_id -> list of timestamps
        self._observations: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

        # Thread-safe queue for Excel writes
        self._event_queue: Queue[AttendanceEvent] = Queue(maxsize=1000)
        self._stop_worker_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Recent events for UI display
        self.recent_events: list[AttendanceEvent] = []

    def start_worker(self) -> None:
        """Start the background Excel writer worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._stop_worker_event.clear()
        self._worker_thread = threading.Thread(
            target=self._excel_writer_worker,
            name="ExcelWriterWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("Background Excel writer thread started.")

    def stop_worker(self, timeout_sec: float = 3.0) -> None:
        """Stop worker and flush any pending events."""
        self._stop_worker_event.set()
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=timeout_sec)
            self._worker_thread = None
        # Drain remaining items if any
        self._flush_remaining_queue()
        logger.info("Background Excel writer thread stopped.")

    def _excel_writer_worker(self) -> None:
        """Background thread consuming attendance events from queue and writing to Excel."""
        batch: list[AttendanceEvent] = []

        while not self._stop_worker_event.is_set():
            try:
                # Wait for an event with timeout
                event = self._event_queue.get(timeout=self.config.queue_timeout_sec)
                batch.append(event)
                # Drain any additional queued events into the batch
                while not self._event_queue.empty() and len(batch) < 50:
                    try:
                        batch.append(self._event_queue.get_nowait())
                    except Empty:
                        break

                if batch:
                    written, errors = self.excel_service.write_attendance_batch(batch)
                    if errors:
                        logger.error("Errors during Excel batch write: %s", errors)
                    batch.clear()

            except Empty:
                continue
            except Exception as exc:
                logger.error("Unexpected error in Excel worker: %s", exc)
                batch.clear()

        # Process any leftovers before exiting
        self._flush_remaining_queue()

    def _flush_remaining_queue(self) -> None:
        """Flush any pending events synchronously."""
        leftovers: list[AttendanceEvent] = []
        while not self._event_queue.empty():
            try:
                leftovers.append(self._event_queue.get_nowait())
            except Empty:
                break
        if leftovers:
            logger.info("Flushing %d leftover attendance events to Excel...", len(leftovers))
            self.excel_service.write_attendance_batch(leftovers)

    def start_session(
        self,
        session_id: Optional[str] = None,
        eligible_records: Optional[list[StudentRecord]] = None,
    ) -> str:
        """Start a new attendance session."""
        with self._lock:
            now = datetime.now()
            if session_id:
                self.session_id = session_id.strip()
            else:
                self.session_id = f"{self.config.session_id_prefix}{now.strftime('%Y%m%d_%H%M%S')}"

            self.session_start_time = now
            self.is_session_active = True
            self.present_student_ids.clear()
            self._observations.clear()

            if eligible_records is not None:
                self.eligible_students = {r.student_id: r for r in eligible_records}

            # Check if this session already has recorded rows in the workbook
            existing_df = self.excel_service.load_existing_attendance()
            if not existing_df.empty and "session_id" in existing_df.columns:
                existing_session_rows = existing_df[
                    existing_df["session_id"].astype(str) == self.session_id
                ]
                for _, row in existing_session_rows.iterrows():
                    sid = str(row.get("student_id", "")).strip()
                    if sid:
                        self.present_student_ids.add(sid)

            logger.info(
                "Started session '%s'. Total eligible: %d, Already present from history: %d",
                self.session_id,
                len(self.eligible_students),
                len(self.present_student_ids),
            )
            return self.session_id

    def stop_session(self, mark_absent: bool = True) -> tuple[int, int]:
        """Stop the active session and optionally mark remaining eligible students as Absent.

        Returns:
            (total_present, total_absent)
        """
        with self._lock:
            if not self.is_session_active or not self.session_id:
                logger.warning("No active session to stop.")
                return len(self.present_student_ids), 0

            current_session = self.session_id
            now = datetime.now()
            date_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")

            absent_events: list[AttendanceEvent] = []
            if mark_absent and self.eligible_students:
                for sid, record in self.eligible_students.items():
                    if sid not in self.present_student_ids:
                        absent_events.append(
                            AttendanceEvent(
                                session_id=current_session,
                                student_id=sid,
                                name=record.name,
                                date_str=date_str,
                                time_str=time_str,
                                status="Absent",
                                match_score=0.0,
                            )
                        )

            # Enqueue absent events
            for ev in absent_events:
                self._event_queue.put(ev)

            # Flush queue to disk
            self._flush_remaining_queue()

            total_present = len(self.present_student_ids)
            total_absent = len(absent_events)

            self.is_session_active = False
            self.session_id = None
            self._observations.clear()

            logger.info(
                "Stopped session '%s'. Summary: %d Present, %d Absent.",
                current_session,
                total_present,
                total_absent,
            )
            return total_present, total_absent

    def register_recognition(
        self, student_id: str, name: str, similarity_score: float
    ) -> tuple[str, bool]:
        """Process a raw face match with temporal confirmation and duplicate prevention.

        Returns:
            (status_message, is_newly_marked):
                status_message: 'Present', 'Already marked', 'Verifying...', or 'Session inactive'
                is_newly_marked: True if this call marked attendance for the first time
        """
        now = time.time()

        with self._lock:
            if not self.is_session_active or not self.session_id:
                return "Session inactive", False

            # Check if student is already marked in this session
            if student_id in self.present_student_ids:
                return "Already marked", False

            # Temporal Confirmation Window
            obs = self._observations[student_id]
            # Prune observations older than confirmation_window_sec
            obs = [t for t in obs if (now - t) <= self.config.confirmation_window_sec]
            obs.append(now)
            self._observations[student_id] = obs

            # Check if threshold number of confirmations reached
            if len(obs) >= self.config.confirmation_frames:
                dt_now = datetime.now()
                event = AttendanceEvent(
                    session_id=self.session_id,
                    student_id=student_id,
                    name=name,
                    date_str=dt_now.strftime("%Y-%m-%d"),
                    time_str=dt_now.strftime("%H:%M:%S"),
                    status="Present",
                    match_score=similarity_score,
                )
                # Synchronously write to Excel to guarantee confirmed persistence before marking Present
                written, errors = self.excel_service.write_attendance_batch([event])
                if errors or written == 0:
                    err_text = errors[0] if errors else "Excel write returned 0 rows"
                    logger.error("Failed to persist attendance for %s: %s", student_id, err_text)
                    return f"Write failure: {err_text}", False

                # Confirmed write succeeded! Now mark Present
                self.present_student_ids.add(student_id)
                self._observations.pop(student_id, None)

                # Keep in recent events list for UI
                self.recent_events.insert(0, event)
                if len(self.recent_events) > 10:
                    self.recent_events.pop()

                logger.info(
                    "Confirmed attendance for Student %s (%s) persisted to Excel with score %.3f in session %s",
                    student_id,
                    name,
                    similarity_score,
                    self.session_id,
                )
                return f"Attendance marked successfully - {name} ({student_id})", True
            else:
                progress = f"Verifying ({len(obs)}/{self.config.confirmation_frames})"
                return progress, False

    def confirm_and_write_attendance(
        self, student_id: str, name: str, similarity_score: float
    ) -> tuple[str, bool, Optional[str]]:
        """Wait for confirmed Excel write before marking student Present.

        Enforces Section 3 attendance ordering:
        - Submit event and WAIT for confirmed Excel write.
        - Only upon successful write is student marked Present and confirmed message returned.
        - If write fails, returns error and does NOT mark Present, allowing safe duplicate-free retry.

        Returns:
            (status_message, is_marked, error_msg)
        """
        sid_clean = str(student_id).strip()
        name_clean = str(name).strip()

        with self._lock:
            if not self.is_session_active or not self.session_id:
                return "Session inactive", False, "No active session."

            if sid_clean in self.present_student_ids:
                return "Already marked", True, None

            dt_now = datetime.now()
            event = AttendanceEvent(
                session_id=self.session_id,
                student_id=sid_clean,
                name=name_clean,
                date_str=dt_now.strftime("%Y-%m-%d"),
                time_str=dt_now.strftime("%H:%M:%S"),
                status="Present",
                match_score=similarity_score,
            )

        # Write to Excel and wait for confirmed result
        written, errors = self.excel_service.write_attendance_batch([event])
        if errors or written == 0:
            err_msg = errors[0] if errors else "Excel persistence failed"
            logger.error("Excel write failure for %s: %s", sid_clean, err_msg)
            return f"Write failure: {err_msg}", False, err_msg

        with self._lock:
            self.present_student_ids.add(sid_clean)
            self.recent_events.insert(0, event)
            if len(self.recent_events) > 10:
                self.recent_events.pop()

        success_msg = f"Attendance marked successfully - {name_clean} ({sid_clean})"
        logger.info(success_msg)
        return success_msg, True, None

    def get_stats(self) -> dict:
        """Return real-time statistics for the UI."""
        with self._lock:
            total_eligible = len(self.eligible_students)
            total_present = len(self.present_student_ids)
            remaining = max(0, total_eligible - total_present)
            return {
                "session_id": self.session_id or "None",
                "is_active": self.is_session_active,
                "eligible": total_eligible,
                "present": total_present,
                "remaining": remaining,
                "recent_events": list(self.recent_events),
            }

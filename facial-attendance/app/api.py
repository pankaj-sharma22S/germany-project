"""Local Python API Layer.

Bridges the existing facial attendance services (camera, tracker, stability manager,
recognizer, attendance manager, excel service, enrollment) with the React frontend.

Key characteristics:
1. Binds to 127.0.0.1 only; restricted CORS.
2. OpenCV VideoCapture stays strictly within Python.
3. Frames processed in background worker thread and broadcast via WebSockets.
4. Slow clients drop frames without blocking the recognition pipeline.
5. REST endpoints for camera, session, student enrollment, and attendance records.
"""

import asyncio
import base64
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time
from typing import Optional
import cv2
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
from pydantic import BaseModel

from app.attendance_manager import AttendanceManager
from app.camera import VideoCamera
from app.config import Config, default_config
from app.enrollment import EnrollmentManager
from app.excel_service import AttendanceEvent, ExcelService, StudentRecord
from app.face_recognizer import FaceMatchResult, FaceRecognizer
from app.stability_manager import FaceStabilityState, StabilityDecision, StabilityManager
from app.tracker import FaceTracker, TrackedFace

logger = logging.getLogger("AttendanceAPI")


class SessionStartRequest(BaseModel):
    session_id: Optional[str] = None


class SystemServices:
    """Singleton holder for shared backend instances."""

    def __init__(self, config: Config = default_config):
        self.config = config
        self.config.ensure_directories()

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
        self.camera = VideoCamera(
            camera_index=config.camera_index,
            width=config.camera_width,
            height=config.camera_height,
            fps=config.camera_fps,
            reconnect_attempts=config.camera_reconnect_attempts,
            reconnect_delay_sec=config.camera_reconnect_delay_sec,
        )
        self.tracker = FaceTracker()
        self.stability_mgr = StabilityManager(config=config)

        self.camera_active = False
        self.records: list[StudentRecord] = []
        self._lock = threading.Lock()

        # WebSocket broadcaster state
        self.connected_websockets: set[WebSocket] = set()
        self.client_queues: dict[WebSocket, Queue] = {}
        self._streaming_thread: Optional[threading.Thread] = None
        self._stop_streaming = threading.Event()

    def initialize(self) -> None:
        """Initialize registry and enrollment index."""
        with self._lock:
            self.records, errors = self.excel_service.read_registry()
            if self.records:
                self.enrollment_mgr.load_or_rebuild_index(self.records, force_rebuild=False)
            self.attendance_mgr.start_worker()

            # Start active session by default
            self.attendance_mgr.start_session(eligible_records=self.records)

    def start_camera(self) -> bool:
        with self._lock:
            if not self.camera_active:
                ok = self.camera.start()
                self.camera_active = ok
                return ok
            return True

    def stop_camera(self) -> None:
        with self._lock:
            if self.camera_active:
                self.camera.stop()
                self.camera_active = False
                self.tracker.reset()
                self.stability_mgr.reset()

    def start_streaming_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """Launch background camera & recognition worker thread."""
        if self._streaming_thread is not None and self._streaming_thread.is_alive():
            return
        self._stop_streaming.clear()
        self._streaming_thread = threading.Thread(
            target=self._streaming_loop,
            args=(loop,),
            name="VideoStreamingWorker",
            daemon=True,
        )
        self._streaming_thread.start()

    def stop_streaming_worker(self) -> None:
        self._stop_streaming.set()
        if self._streaming_thread is not None:
            self._streaming_thread.join(timeout=2.0)
            self._streaming_thread = None

    def _streaming_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Continuous pipeline: read camera -> track -> stabilize -> recognize -> broadcast."""
        while not self._stop_streaming.is_set():
            time.sleep(0.04)  # ~25 FPS ceiling

            if not self.camera_active:
                # If camera is inactive, send periodic heartbeat state if clients are connected
                if self.connected_websockets:
                    payload = self._build_empty_frame_payload("Camera Stopped")
                    self._dispatch_payload_to_clients(payload, loop)
                continue

            ret, frame = self.camera.read_frame()
            if not ret or frame is None or frame.size == 0:
                payload = self._build_empty_frame_payload("Camera Disconnected")
                self._dispatch_payload_to_clients(payload, loop)
                continue

            h, w = frame.shape[:2]

            # 1. Detect faces
            raw_results = self.face_recognizer.process_frame(frame)
            bboxes = [r.bbox for r in raw_results]

            # 2. Update tracker
            active_tracks = self.tracker.update(bboxes)
            active_track_ids = [t.track_id for t in active_tracks]
            self.stability_mgr.prune_lost_tracks(active_track_ids)

            bbox_to_match = {r.bbox: r for r in raw_results}
            faces_metadata = []
            frame_message = "Looking for faces..." if not active_tracks else "Tracking face..."

            # 3. Evaluate stability and trigger confirmed attendance
            for track in active_tracks:
                decision = self.stability_mgr.update_face(track)
                match_res = bbox_to_match.get(track.bbox)

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
                        frame_message = att_msg
                    else:
                        unknown_score = match_res.similarity if match_res else 0.0
                        self.stability_mgr.mark_recognition_result(
                            track_id=track.track_id,
                            is_known=False,
                            student_id=None,
                            name=None,
                            score=unknown_score,
                            attendance_status="Unknown face - attendance not marked",
                        )
                        frame_message = "Unknown face - attendance not marked"
                    # Refresh decision
                    decision = self.stability_mgr.update_face(track)
                else:
                    frame_message = decision.feedback_message

                # Normalize bounding box [x1/w, y1/h, x2/w, y2/h]
                bx1, by1, bx2, by2 = track.bbox
                norm_box = [
                    round(float(bx1) / w, 4),
                    round(float(by1) / h, 4),
                    round(float(bx2) / w, 4),
                    round(float(by2) / h, 4),
                ]

                # Map state to unified state string for UI
                state_str = decision.state.value
                student_name = match_res.name if match_res and match_res.is_known else None
                student_id = match_res.student_id if match_res and match_res.is_known else None
                sim_score = round(float(match_res.similarity), 3) if match_res else 0.0

                faces_metadata.append(
                    {
                        "track_id": track.track_id,
                        "normalized_box": norm_box,
                        "state": state_str,
                        "name": student_name,
                        "student_id": student_id,
                        "similarity": sim_score,
                        "stability_progress": round(float(decision.progress), 3),
                        "message": decision.feedback_message,
                    }
                )

            # 4. Encode JPEG frame
            # Downscale slightly for smooth WebSocket delivery if full 1280x720
            target_w = 800 if w > 800 else w
            target_h = int(h * (target_w / w))
            resized_frame = cv2.resize(frame, (target_w, target_h))

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
            ok, buf = cv2.imencode(".jpg", resized_frame, encode_param)
            if not ok:
                continue

            jpeg_b64 = "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")

            # 5. Build consolidated atomic message
            stats = self.attendance_mgr.get_stats()
            enrolled_count = len(self.enrollment_mgr.student_ids)

            payload = {
                "frame": jpeg_b64,
                "frame_size": [target_w, target_h],
                "faces": faces_metadata,
                "message": frame_message,
                "counts": {
                    "enrolled": enrolled_count,
                    "eligible": stats["eligible"],
                    "present": stats["present"],
                    "remaining": stats["remaining"],
                },
                "camera_active": self.camera_active,
                "session_active": self.attendance_mgr.is_session_active,
                "session_id": self.attendance_mgr.session_id or "None",
                "error": None,
            }

            self._dispatch_payload_to_clients(payload, loop)

    def _build_empty_frame_payload(self, message: str) -> dict:
        """Create a state payload without a live video frame."""
        stats = self.attendance_mgr.get_stats()
        enrolled_count = len(self.enrollment_mgr.student_ids)
        return {
            "frame": None,
            "frame_size": [800, 450],
            "faces": [],
            "message": message,
            "counts": {
                "enrolled": enrolled_count,
                "eligible": stats["eligible"],
                "present": stats["present"],
                "remaining": stats["remaining"],
            },
            "camera_active": self.camera_active,
            "session_active": self.attendance_mgr.is_session_active,
            "session_id": self.attendance_mgr.session_id or "None",
            "error": None,
        }

    def _dispatch_payload_to_clients(self, payload: dict, loop: asyncio.AbstractEventLoop) -> None:
        """Dispatch message to each connected client's single-item drop-oldest queue."""
        with self._lock:
            clients = list(self.connected_websockets)

        for ws in clients:
            q = self.client_queues.get(ws)
            if q is None:
                continue
            # Drop older pending frame if client hasn't consumed it yet
            if q.full():
                try:
                    q.get_nowait()
                except Empty:
                    pass
            try:
                q.put_nowait(payload)
            except Full:
                pass


# Global services container
services = SystemServices()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan to manage service startup and teardown."""
    loop = asyncio.get_running_loop()
    services.initialize()
    services.start_streaming_worker(loop)
    yield
    services.stop_streaming_worker()
    services.stop_camera()
    services.attendance_mgr.stop_worker(timeout_sec=2.0)


# Initialize FastAPI application
app = FastAPI(title="Facial Attendance System API", lifespan=lifespan)

# Restrict CORS to local development origins on 127.0.0.1
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def get_status():
    """Retrieve current system state, camera state, session status, and counts."""
    stats = services.attendance_mgr.get_stats()
    enrolled_count = len(services.enrollment_mgr.student_ids)
    return {
        "camera_active": services.camera_active,
        "session_active": services.attendance_mgr.is_session_active,
        "session_id": services.attendance_mgr.session_id,
        "timezone": services.config.session_timezone,
        "counts": {
            "enrolled": enrolled_count,
            "eligible": stats["eligible"],
            "present": stats["present"],
            "remaining": stats["remaining"],
        },
    }


@app.post("/api/camera/start")
async def start_camera():
    """Start video capture."""
    ok = services.start_camera()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to open camera hardware.")
    return {"success": True, "message": "Camera started."}


@app.post("/api/camera/stop")
async def stop_camera():
    """Stop video capture."""
    services.stop_camera()
    return {"success": True, "message": "Camera stopped."}


@app.post("/api/session/start")
async def start_session(req: Optional[SessionStartRequest] = None):
    """Start or restart attendance session."""
    session_id = req.session_id if req else None
    sess = services.attendance_mgr.start_session(
        session_id=session_id, eligible_records=services.records
    )
    services.stability_mgr.reset()
    return {"success": True, "session_id": sess}


@app.post("/api/session/stop")
async def stop_session():
    """Stop active session and mark absentees."""
    present, absent = services.attendance_mgr.stop_session(mark_absent=True)
    services.stability_mgr.reset()
    return {"success": True, "present": present, "absent": absent}


@app.get("/api/students")
async def get_students():
    """List all enrolled students (ID and Name only)."""
    with services.enrollment_mgr._lock:
        ids = list(services.enrollment_mgr.student_ids)
        students = []
        for sid in ids:
            rec = services.enrollment_mgr.id_to_record.get(sid)
            students.append({"student_id": sid, "name": rec.name if rec else sid})
    return {"count": len(students), "students": students}


@app.post("/api/students")
async def enroll_student(
    student_id: str = Form(...),
    name: str = Form(...),
    image: UploadFile = File(...),
):
    """Runtime enrollment of a single student with image validation and transactional rollback."""
    # Read image bytes
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid or readable image.",
        )

    success, message = services.enrollment_mgr.enroll_single_student(
        student_id=student_id,
        name=name,
        image_input=img,
        excel_service=services.excel_service,
    )

    if not success:
        # Return real failure reason
        raise HTTPException(status_code=400, detail=message)

    # Update eligible list in active session
    records, _ = services.excel_service.read_registry()
    services.records = records
    if services.attendance_mgr.is_session_active:
        services.attendance_mgr.eligible_students = {r.student_id: r for r in records}

    return {"success": True, "message": message, "student_id": student_id, "name": name}


@app.get("/api/attendance/recent")
async def get_recent_attendance():
    """Retrieve recent confirmed attendance records for active session."""
    stats = services.attendance_mgr.get_stats()
    events = stats["recent_events"]
    result = [
        {
            "session_id": ev.session_id,
            "student_id": ev.student_id,
            "name": ev.name,
            "date": ev.date_str,
            "time": ev.time_str,
            "status": ev.status,
            "match_score": round(float(ev.match_score), 4),
        }
        for ev in events
    ]
    return {"recent": result}


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket stream sending JPEG frames and consolidated metadata per frame."""
    await websocket.accept()

    # Queue with capacity 1 to ensure latest frame delivery and drop older frames
    client_queue: Queue = Queue(maxsize=1)
    with services._lock:
        services.connected_websockets.add(websocket)
        services.client_queues[websocket] = client_queue

    try:
        while True:
            # Poll from client queue in a non-blocking asyncio loop
            try:
                payload = client_queue.get_nowait()
                await websocket.send_json(payload)
            except Empty:
                await asyncio.sleep(0.02)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception as exc:
        logger.debug("WebSocket client closed: %s", exc)
    finally:
        with services._lock:
            services.connected_websockets.discard(websocket)
            services.client_queues.pop(websocket, None)

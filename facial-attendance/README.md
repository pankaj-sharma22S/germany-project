# Facial Attendance System (Working MVP with React UI)

An end-to-end facial recognition attendance management system built with Python, OpenCV, InsightFace (ArcFace embeddings with ONNX Runtime), FastAPI, Excel automation via Pandas and openpyxl, and a modern **React (JSX) web interface**.

---

## Architecture Overview

```text
  Browser (React UI on http://127.0.0.1:5173)
     │  HTTP (REST API)               WebSocket (/ws/stream)
     ▼                                ▲
  Local Python API Layer (FastAPI on http://127.0.0.1:8000)
     │
     ▼
  Core Engine (camera, tracker, stability manager, face recognizer,
               attendance manager, excel service, enrollment manager)
```

- **Camera Ownership**: Python retains exclusive ownership of `cv2.VideoCapture`; the browser never accesses camera hardware directly.
- **Atomic WebSocket Frames**: Each message contains a base64 JPEG frame and synchronized metadata (`faces`, normalized bounding boxes, state, similarity score, stability progress, counts, and messages).
- **Non-Blocking Dropping**: Worker threads process frames; slow browser clients drop old frames without stalling the recognition pipeline.
- **Biometric Security**: Raw 512-d embeddings are never transmitted to the browser.
- **Localhost Only**: Binds strictly to `127.0.0.1`.

---

## Directory Structure

```text
facial-attendance/
|-- data/
|   |-- students.xlsx              # INPUT: Student registry (appended on enrollment)
|   |-- photos/                    # INPUT: Reference photos (saved on enrollment)
|   |-- embeddings.npz             # OUTPUT: Aligned student IDs + embedding vectors
|   `-- attendance.xlsx            # OUTPUT: Attendance workbook with timestamps & scores
|-- app/
|   |-- __init__.py
|   |-- api.py                     # [NEW] FastAPI REST & WebSocket streaming layer
|   |-- config.py                  # Dataclass config (paths, camera, thresholds, stability)
|   |-- camera.py                  # OpenCV VideoCapture wrapper with auto-reconnection
|   |-- excel_service.py           # Registry validation, row appending & Excel persistence
|   |-- enrollment.py              # Batch & single-student runtime enrollment with rollback
|   |-- tracker.py                 # Face tracking & frame-to-frame movement metrics
|   |-- stability_manager.py       # Stability state machine, countdowns & warnings
|   |-- face_recognizer.py         # Face detection, cosine similarity, unknown rejection
|   |-- attendance_manager.py      # Session lifecycle, confirmed persistence ordering, retry
|   |-- ui.py                      # Standalone OpenCV HUD overlay (kept for fallback)
|   |-- image_runner.py            # Static image attendance pipeline runner
|   |-- create_template.py         # Helper to generate starter students.xlsx
|   `-- main.py                    # OpenCV entry point
|-- frontend/                      # [NEW] React (JSX) + Vite Application
|   |-- package.json
|   |-- vite.config.js             # Vite dev server configuration (127.0.0.1:5173)
|   |-- index.html
|   `-- src/
|       |-- main.jsx               # React entry point
|       |-- App.jsx                # Layout, top-level state & WebSocket coordination
|       |-- api/client.js          # HTTP REST API client
|       |-- hooks/useStream.js     # WebSocket connection, reconnection & stream state
|       |-- constants/faceStates.js# Single source of truth for face states & box colors
|       |-- components/
|       |   |-- VideoPanel.jsx     # Live JPEG feed + Canvas overlay with bounding boxes
|       |   |-- StatusBanner.jsx   # Feedback messages, movement warnings & alerts
|       |   |-- StabilityIndicator.jsx # Stability countdown & percentage bar
|       |   |-- LoadingSpinner.jsx # Real-time spinner shown only during verification
|       |   |-- Controls.jsx       # Camera, Session, and Add Student controls
|       |   |-- AddStudentModal.jsx# Runtime student enrollment form with image preview
|       |   |-- StatsPanel.jsx     # Enrolled, Eligible, Present, Remaining counts
|       |   `-- RecentAttendance.jsx # Real-time feed of confirmed attendance marks
|       |-- styles/App.css         # Modern dark-mode responsive theme
|       `-- tests/components.test.jsx # Automated component tests
|-- tests/                         # Backend unit & integration test suite (33 tests)
|-- requirements.txt
|-- README.md
`-- .gitignore
```

---

## API Contract

### REST Endpoints (`http://127.0.0.1:8000`)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/status` | Returns `{ camera_active, session_active, session_id, counts: { enrolled, eligible, present, remaining }, timezone }` |
| `POST` | `/api/camera/start` | Activates camera capture |
| `POST` | `/api/camera/stop` | Pauses camera capture |
| `POST` | `/api/session/start` | Starts new attendance session (optional `session_id`) |
| `POST` | `/api/session/stop` | Finalizes session and logs `"Absent"` records in Excel |
| `GET` | `/api/students` | Lists all enrolled students (`student_id`, `name`) |
| `POST` | `/api/students` | Multipart form (`student_id`, `name`, `image`). Validates 1 face, extracts embedding, saves photo, appends Excel, updates index with full rollback. |
| `GET` | `/api/attendance/recent` | Recent confirmed attendance marks for active session |

### WebSocket (`ws://127.0.0.1:8000/ws/stream`)
Broadcasts atomic frame packets at ~25 FPS:
```json
{
  "frame": "data:image/jpeg;base64,...",
  "frame_size": [800, 450],
  "faces": [
    {
      "track_id": 1,
      "normalized_box": [0.25, 0.20, 0.55, 0.60],
      "state": "confirmed",
      "name": "Rahul Sharma",
      "student_id": "S101",
      "similarity": 0.742,
      "stability_progress": 1.0,
      "message": "Attendance marked successfully"
    }
  ],
  "message": "Attendance marked successfully - Rahul Sharma (S101)",
  "counts": { "enrolled": 10, "eligible": 10, "present": 1, "remaining": 9 },
  "camera_active": true,
  "session_active": true,
  "session_id": "SES_20261014_143000",
  "error": null
}
```

---

## Face States & Visual Indication

| State | Box Color | Canvas / Banner Tag |
|---|---|---|
| **Tracking / Stabilizing** | Gold / Amber (`#f39c12`) | `Stabilizing [====>  ] 65% - Stay still...` |
| **Movement Detected** | Red-Orange (`#e74c3c`) | `! Movement Detected ! - Please stay still - face movement detected` |
| **Face Stable / Verifying**| Purple (`#9b59b6`) | `Verifying Identity... [Spinner] - Face stable - verifying identity...` |
| **Unknown Face** | Crimson Red (`#e74c3c`) | `Unknown Face (Sim: 0.28) - Unknown face - attendance not marked` |
| **Confirmed Present** | Bright Green (`#2ecc71`)| `Attendance marked successfully - <Name> (<ID>)` |
| **Already Marked** | Emerald Green (`#27ae60`)| `<Name> (<ID>) - Already marked` |

---

## How to Run the System

### Step 1: Start Backend API (Terminal 1)
```powershell
cd e:\german\facial-attendance
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

### Step 2: Start React Frontend (Terminal 2)
```powershell
cd e:\german\facial-attendance\frontend
npm run dev
```

Open **`http://127.0.0.1:5173`** in your browser to access the live dashboard.

---

## Automated Tests

### 1. Backend Python Tests (33 Passed)
```powershell
cd e:\german\facial-attendance
pytest tests/ -v
```

### 2. Frontend React Component Tests (14 Passed)
```powershell
cd e:\german\facial-attendance\frontend
npm test
```

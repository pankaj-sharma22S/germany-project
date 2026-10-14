# Facial Attendance System (Working MVP with React UI & ID Card Details)

An end-to-end facial recognition attendance management system built with Python, OpenCV, InsightFace (ArcFace embeddings with ONNX Runtime), FastAPI, Excel automation via Pandas and openpyxl, and a modern **React (JSX) web interface** featuring live webcam capture, runtime enrollment with ID cards, and a dedicated student detail & verification page.

---

## Architecture Overview

```text
  Browser (React UI on http://127.0.0.1:8000 or http://127.0.0.1:5173)
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
- **Biometric Security**: Raw 512-d embeddings are never transmitted to the browser or returned in API responses.
- **ID Card Document Security**: Sensitive ID cards are served strictly through authenticated/protected endpoints with path traversal protection; images are never served via public static directories.
- **Localhost Only**: Binds strictly to `127.0.0.1`.

---

## Directory Structure

```text
facial-attendance/
|-- data/
|   |-- students.xlsx              # INPUT: Student registry (student_id, name, photo_path, id_card_path)
|   |-- photos/                    # INPUT: Reference face photos (protected, gitignored)
|   |-- id_cards/                  # INPUT: Stored ID card images (protected, gitignored)
|   |-- embeddings.npz             # OUTPUT: Aligned student IDs + 512-d ArcFace embedding vectors
|   `-- attendance.xlsx            # OUTPUT: Attendance workbook with timestamps & scores
|-- app/
|   |-- __init__.py
|   |-- api.py                     # FastAPI REST & WebSocket streaming layer + SPA fallback
|   |-- config.py                  # Dataclass config (paths, camera, thresholds, stability, ID cards)
|   |-- camera.py                  # OpenCV VideoCapture wrapper with auto-reconnection
|   |-- excel_service.py           # Registry validation, row appending, query helpers & Excel persistence
|   |-- enrollment.py              # Batch & single-student runtime enrollment with ID card & rollback
|   |-- tracker.py                 # Face tracking & frame-to-frame movement metrics
|   |-- stability_manager.py       # Stability state machine, countdowns & movement warnings
|   |-- face_recognizer.py         # Face detection, cosine similarity, unknown rejection
|   |-- attendance_manager.py      # Session lifecycle, confirmed persistence ordering, duplicate guard
|   |-- ui.py                      # Standalone OpenCV HUD overlay (kept for desktop fallback)
|   |-- image_runner.py            # Static image attendance pipeline runner
|   |-- create_template.py         # Helper to generate starter students.xlsx
|   `-- main.py                    # OpenCV entry point
|-- frontend/                      # React (JSX) + Vite Application
|   |-- package.json
|   |-- vite.config.js             # Vite dev server configuration (127.0.0.1:5173)
|   |-- index.html
|   `-- src/
|       |-- main.jsx               # React entry point
|       |-- App.jsx                # Layout, client-side routing (BrowserRouter)
|       |-- pages/
|       |   |-- LiveAttendancePage.jsx # Live camera capture, statistics, and controls
|       |   `-- StudentDetailPage.jsx  # Student details, photo, ID card & session record
|       |-- api/client.js          # HTTP REST API client with ID card & detail endpoints
|       |-- hooks/useStream.js     # WebSocket connection, reconnection & stream state
|       |-- constants/faceStates.js# Single source of truth for face states & box colors
|       |-- components/
|       |   |-- VideoPanel.jsx     # Live JPEG feed + Canvas overlay with bounding boxes
|       |   |-- StatusBanner.jsx   # Feedback messages, movement warnings & alerts
|       |   |-- StabilityIndicator.jsx # Stability countdown & percentage bar
|       |   |-- LoadingSpinner.jsx # Real-time spinner shown only during verification
|       |   |-- Controls.jsx       # Camera, Session, and Add Student controls
|       |   |-- AddStudentModal.jsx# Runtime enrollment form with photo & ID card preview
|       |   |-- StatsPanel.jsx     # Enrolled, Eligible, Present, Remaining counts
|       |   |-- RecentAttendance.jsx # Real-time feed of confirmed attendance + "View details" button
|       |   `-- ImageCard.jsx      # Image with loading, placeholder, error & click-to-enlarge
|       |-- styles/App.css         # Modern dark-mode responsive theme
|       `-- tests/components.test.jsx # Automated component tests
|-- tests/                         # Complete pytest automated test suite (44 tests)
|   |-- test_id_card_and_detail.py # ID card enrollment, details endpoint, and security tests
|   |-- test_api.py                # REST API lifecycle tests
|   |-- test_attendance_manager.py # Stability and duplicate prevention tests
|   |-- test_enrollment.py         # Batch ArcFace embedding generation tests
|   |-- test_excel_service.py      # Spreadsheet validation & persistence tests
|   |-- test_face_recognizer.py    # Cosine similarity and unknown rejection tests
|   |-- test_image_pipeline.py     # Image runner test
|   `-- test_upgrades.py           # Tracking, movement, and rollback tests
|-- run_web_ui.py                  # User-friendly Python launcher with auto browser open
|-- run_ui.bat                     # Windows one-click batch launcher
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
| `POST` | `/api/students` | Multipart form (`student_id`, `name`, `photo`, optional `id_card`). Validates face, extracts embedding, saves photo & ID card, appends Excel, updates index with full transactional rollback. |
| `GET` | `/api/students/{student_id}` | Student bio details, ID card presence, and attendance record (with optional `?session_id=<id>`). **Never returns embeddings.** |
| `GET` | `/api/students/{student_id}/photo` | Streams protected reference face photo (path traversal guarded). |
| `GET` | `/api/students/{student_id}/id-card` | Streams protected ID card image (path traversal guarded). |
| `GET` | `/api/attendance/recent` | Recent confirmed attendance marks for active session |

---

## Configuration Settings (`app/config.py`)

| Setting | Default Value | Description |
|---|---|---|
| `ID_CARD_DIR` | `data/id_cards` | Directory storing sensitive ID card images |
| `ID_CARD_ALLOWED_TYPES` | `(".jpg", ".jpeg", ".png", ".webp")` | Permitted image extensions for ID cards |
| `ID_CARD_MAX_MB` | `5.0` | Maximum allowed upload size in megabytes |
| `ID_CARD_REQUIRED` | `False` (configurable) | Whether new runtime enrollments enforce ID card upload |
| `STABILITY_DURATION_SECONDS` | `1.0` | Minimum duration (sec) a face must remain still |
| `REQUIRED_STABLE_FRAMES` | `4` | Minimum consecutive stable frames before recognition |
| `MAX_CENTER_MOVEMENT_PX` | `28.0` | Maximum pixel movement before stability reset |
| `RECOGNITION_THRESHOLD` | `0.45` | Cosine similarity threshold for genuine match |

---

## How to Run the System

### Option 1: Web UI Launcher (Recommended)
From `facial-attendance`:
```powershell
python run_web_ui.py
```
This starts the backend server, hosts the compiled React UI at `http://127.0.0.1:8000/`, and automatically launches your default web browser.

### Option 2: Windows Batch Script
Double-click or run:
```cmd
run_ui.bat
```

### Option 3: Vite Dev Server (for UI Development)
In Terminal 1 (Backend):
```powershell
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```
In Terminal 2 (React Vite Dev):
```powershell
cd frontend
npm run dev
```
Open **`http://127.0.0.1:5173`**.

---

## Automated Verification & Test Results

### 1. Backend Python Tests (44 Passed)
Run from `facial-attendance`:
```powershell
pytest tests/ -v
```
**Results:** `44 passed in 6.39s`
- Enrollment with ID card: success, wrong type rollback, oversized file rollback, corrupted image rollback.
- Legacy `students.xlsx` compatibility: loads without `id_card_path` column; legacy students report no ID card.
- Detail endpoint: valid student, 404 unknown student, 404 missing file, security verification (no embeddings).
- Path traversal rejection.
- Confirmed persistence ordering, stability dynamics, and duplicate prevention.

### 2. Frontend React Component Tests (18 Passed)
Run from `frontend/`:
```powershell
npm test
```
**Results:** `18 passed in 1.91s`
- "View details" button navigation with session ID.
- `StudentDetailPage`: renders photo, ID card, bio, attendance record, and missing/placeholder/error states.
- `ImageCard`: loading state, placeholder text, image thumbnail, click-to-enlarge lightbox modal.
- `AddStudentModal`: client-side validation and ID card requirement enforcement.

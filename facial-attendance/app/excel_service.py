"""Excel Service module.

Handles:
1. Reading and validating the student registry from data/students.xlsx.
2. Creating and updating the data/attendance.xlsx workbook.
3. Thread-safe single-writer persistence with error recovery.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import threading
from typing import Optional
import cv2
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class StudentRecord:
    """Represents a validated student record from the registry."""

    student_id: str
    name: str
    photo_path: Path
    raw_photo_path: str
    id_card_path: Optional[Path] = None
    raw_id_card_path: Optional[str] = None


@dataclass
class AttendanceEvent:
    """Represents an attendance record to be written to Excel."""

    session_id: str
    student_id: str
    name: str
    date_str: str  # YYYY-MM-DD
    time_str: str  # HH:MM:SS (in session timezone)
    status: str  # 'Present' or 'Absent'
    match_score: float  # Similarity score (0.0 to 1.0)


class ExcelService:
    """Single-writer thread-safe service for Excel operations."""

    REQUIRED_REGISTRY_COLUMNS = ["student_id", "name", "photo_path"]
    ATTENDANCE_COLUMNS = [
        "session_id",
        "student_id",
        "name",
        "date",
        "time",
        "status",
        "match_score",
    ]

    def __init__(
        self,
        project_root: Path,
        registry_file: Path,
        attendance_file: Path,
        attendance_mode: str = "session",
    ):
        self.project_root = Path(project_root).resolve()
        self.registry_file = Path(registry_file).resolve()
        self.attendance_file = Path(attendance_file).resolve()
        self.attendance_mode = attendance_mode
        self._write_lock = threading.Lock()

    def resolve_photo_path(self, raw_path: str) -> Path:
        """Resolve a photo path string to an absolute Path."""
        raw_p = Path(raw_path.strip().replace("\\", "/"))
        if raw_p.is_absolute():
            return raw_p

        candidates = [
            self.project_root / raw_p,
            self.project_root / "data" / raw_p,
            self.project_root / "data" / "photos" / raw_p,
            self.registry_file.parent / raw_p,
        ]

        for cand in candidates:
            if cand.is_file():
                return cand.resolve()

        # If not found yet, default to project_root / raw_p
        return (self.project_root / raw_p).resolve()

    def resolve_id_card_path(self, raw_path: str) -> Path:
        """Resolve an ID card path string to an absolute Path."""
        raw_p = Path(raw_path.strip().replace("\\", "/"))
        if raw_p.is_absolute():
            return raw_p

        candidates = [
            self.project_root / raw_p,
            self.project_root / "data" / raw_p,
            self.project_root / "data" / "id_cards" / raw_p,
            self.registry_file.parent / raw_p,
            self.registry_file.parent / "id_cards" / raw_p,
        ]

        for cand in candidates:
            if cand.is_file():
                return cand.resolve()

        return (self.project_root / raw_p).resolve()

    def read_registry(self) -> tuple[list[StudentRecord], list[str]]:
        """Read and validate the student registry.

        Returns:
            (records, errors): List of valid StudentRecord instances, and
                               list of human-readable error descriptions.
        """
        errors: list[str] = []
        records: list[StudentRecord] = []

        if not self.registry_file.exists():
            errors.append(f"Registry file not found at: {self.registry_file}")
            return records, errors

        try:
            df = pd.read_excel(self.registry_file, engine="openpyxl")
        except Exception as exc:
            errors.append(f"Failed to open registry spreadsheet: {exc}")
            return records, errors

        # Strip whitespace from column names and string values
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Check required columns
        missing_cols = [c for c in self.REQUIRED_REGISTRY_COLUMNS if c not in df.columns]
        if missing_cols:
            errors.append(
                f"Missing required columns in {self.registry_file.name}: {missing_cols}. "
                f"Expected: {self.REQUIRED_REGISTRY_COLUMNS}"
            )
            return records, errors

        if len(df) == 0:
            errors.append(f"Registry spreadsheet {self.registry_file.name} is empty (0 records).")
            return records, errors

        seen_ids: set[str] = set()

        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed row number in Excel including header

            # Validate student_id
            sid_val = row.get("student_id")
            if pd.isna(sid_val) or str(sid_val).strip() == "":
                errors.append(f"Row {row_num}: Missing 'student_id'.")
                continue
            student_id = str(sid_val).strip()

            if student_id in seen_ids:
                errors.append(f"Row {row_num}: Duplicate 'student_id' '{student_id}'.")
                continue
            seen_ids.add(student_id)

            # Validate name
            name_val = row.get("name")
            if pd.isna(name_val) or str(name_val).strip() == "":
                errors.append(f"Row {row_num} (Student {student_id}): Missing 'name'.")
                continue
            name = str(name_val).strip()

            # Validate photo_path
            path_val = row.get("photo_path")
            if pd.isna(path_val) or str(path_val).strip() == "":
                errors.append(f"Row {row_num} (Student {student_id}): Missing 'photo_path'.")
                continue
            raw_photo_path = str(path_val).strip()
            resolved_photo = self.resolve_photo_path(raw_photo_path)

            if not resolved_photo.exists():
                errors.append(
                    f"Row {row_num} (Student {student_id}): Reference photo file does not exist at "
                    f"'{resolved_photo}' (configured as '{raw_photo_path}')."
                )
                continue

            # Verify image file is readable by OpenCV
            img_test = cv2.imread(str(resolved_photo))
            if img_test is None or img_test.size == 0:
                errors.append(
                    f"Row {row_num} (Student {student_id}): Reference photo at '{resolved_photo}' "
                    f"is corrupted or in an unsupported format."
                )
                continue

            # Optional id_card_path
            resolved_id_card: Optional[Path] = None
            raw_id_card: Optional[str] = None
            if "id_card_path" in df.columns:
                id_card_val = row.get("id_card_path")
                if not pd.isna(id_card_val) and str(id_card_val).strip() != "":
                    raw_id_card = str(id_card_val).strip()
                    resolved_cand = self.resolve_id_card_path(raw_id_card)
                    if resolved_cand.exists():
                        resolved_id_card = resolved_cand

            records.append(
                StudentRecord(
                    student_id=student_id,
                    name=name,
                    photo_path=resolved_photo,
                    raw_photo_path=raw_photo_path,
                    id_card_path=resolved_id_card,
                    raw_id_card_path=raw_id_card,
                )
            )

        logger.info(
            "Read registry: %d valid records, %d errors encountered.",
            len(records),
            len(errors),
        )
        return records, errors

    def load_existing_attendance(self) -> pd.DataFrame:
        """Load existing attendance history or return an empty DataFrame with proper schema."""
        with self._write_lock:
            if not self.attendance_file.exists():
                return pd.DataFrame(columns=self.ATTENDANCE_COLUMNS)

            try:
                df = pd.read_excel(self.attendance_file, sheet_name="Attendance", engine="openpyxl")
                # Normalize column names
                df.columns = [str(c).strip().lower() for c in df.columns]
                return df
            except Exception as exc:
                logger.warning("Could not read existing attendance file: %s. Starting fresh.", exc)
                return pd.DataFrame(columns=self.ATTENDANCE_COLUMNS)

    def write_attendance_batch(self, events: list[AttendanceEvent]) -> tuple[int, list[str]]:
        """Safely append attendance events to the Excel workbook.

        Ensures no duplicates per (session_id, student_id).
        Thread-safe single writer with file integrity verification.

        Returns:
            (written_count, errors): Number of rows successfully written, and error messages.
        """
        if not events:
            return 0, []

        errors: list[str] = []
        written_count = 0

        with self._write_lock:
            self.attendance_file.parent.mkdir(parents=True, exist_ok=True)

            wb: openpyxl.Workbook
            ws: openpyxl.worksheet.worksheet.Worksheet

            # 1. Load or create workbook
            if self.attendance_file.exists():
                try:
                    wb = openpyxl.load_workbook(self.attendance_file)
                    if "Attendance" in wb.sheetnames:
                        ws = wb["Attendance"]
                    else:
                        ws = wb.create_sheet("Attendance")
                        self._write_header(ws)
                except Exception as exc:
                    logger.error("Error opening %s: %s. Creating new backup/fresh file.", self.attendance_file, exc)
                    errors.append(f"Error opening existing workbook: {exc}")
                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = "Attendance"
                    self._write_header(ws)
            else:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Attendance"
                self._write_header(ws)

            # 2. Write or update records according to attendance_mode
            if self.attendance_mode == "daily":
                # In daily mode: enforce exactly 1 record per student per date.
                # If a record already exists for (date, student_id):
                #   - If incoming event is "Present": update existing row in-place
                #     with latest session_id, time, match_score, status="Present", and green styling.
                #   - If incoming event is "Absent": NEVER overwrite or downgrade "Present".
                # If no record exists for (date, student_id): append new row.
                date_student_to_row: dict[tuple[str, str], int] = {}
                for r in range(2, ws.max_row + 1):
                    d_cell = ws.cell(row=r, column=4).value
                    sid_cell = ws.cell(row=r, column=2).value
                    if d_cell and sid_cell:
                        key = (str(d_cell).strip(), str(sid_cell).strip().lower())
                        date_student_to_row[key] = r

                for ev in events:
                    key = (str(ev.date_str).strip(), str(ev.student_id).strip().lower())
                    if key in date_student_to_row:
                        row_idx = date_student_to_row[key]
                        current_status = str(ws.cell(row=row_idx, column=6).value or "").strip().lower()
                        if ev.status == "Present":
                            existing_sess = str(ws.cell(row=row_idx, column=1).value or "").strip()
                            if existing_sess == ev.session_id and current_status == "present":
                                logger.debug(
                                    "Skipping already recorded attendance for %s in %s",
                                    ev.student_id,
                                    ev.session_id,
                                )
                                continue

                            # In-place update of the single existing daily record
                            ws.cell(row=row_idx, column=1).value = ev.session_id
                            ws.cell(row=row_idx, column=2).value = ev.student_id
                            if ev.name:
                                ws.cell(row=row_idx, column=3).value = ev.name
                            ws.cell(row=row_idx, column=4).value = ev.date_str
                            ws.cell(row=row_idx, column=5).value = ev.time_str
                            ws.cell(row=row_idx, column=6).value = "Present"
                            ws.cell(row=row_idx, column=7).value = round(float(ev.match_score), 4)

                            for col_idx in range(1, len(self.ATTENDANCE_COLUMNS) + 1):
                                cell = ws.cell(row=row_idx, column=col_idx)
                                cell.alignment = Alignment(horizontal="center" if col_idx in (1, 2, 4, 5, 6) else "left")
                                cell.fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")

                            written_count += 1
                            logger.info(
                                "Updated existing daily attendance for student %s (%s) on %s to Present at %s (score: %.4f)",
                                ev.student_id,
                                ev.name,
                                ev.date_str,
                                ev.time_str,
                                ev.match_score,
                            )
                        else:
                            # ev.status == "Absent"
                            if current_status == "present":
                                logger.debug(
                                    "Skipping Absent status for %s on %s: already marked Present.",
                                    ev.student_id,
                                    ev.date_str,
                                )
                                continue
                            # If already Absent, no need to update
                            continue
                    else:
                        row_idx = ws.max_row + 1
                        row_values = [
                            ev.session_id,
                            ev.student_id,
                            ev.name,
                            ev.date_str,
                            ev.time_str,
                            ev.status,
                            round(float(ev.match_score), 4),
                        ]
                        ws.append(row_values)

                        for col_idx in range(1, len(row_values) + 1):
                            cell = ws.cell(row=row_idx, column=col_idx)
                            cell.alignment = Alignment(horizontal="center" if col_idx in (1, 2, 4, 5, 6) else "left")
                            if ev.status == "Present":
                                cell.fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")
                            elif ev.status == "Absent":
                                cell.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

                        date_student_to_row[key] = row_idx
                        written_count += 1
            else:
                # Session mode (backward compatible session-scoped records)
                existing_pairs: set[tuple[str, str]] = set()
                for r in range(2, ws.max_row + 1):
                    sess_cell = ws.cell(row=r, column=1).value
                    sid_cell = ws.cell(row=r, column=2).value
                    if sess_cell and sid_cell:
                        existing_pairs.add((str(sess_cell).strip(), str(sid_cell).strip().lower()))

                for ev in events:
                    pair = (ev.session_id.strip(), ev.student_id.strip().lower())
                    if pair in existing_pairs:
                        logger.debug("Skipping already recorded attendance for %s in %s", ev.student_id, ev.session_id)
                        continue

                    row_idx = ws.max_row + 1
                    row_values = [
                        ev.session_id,
                        ev.student_id,
                        ev.name,
                        ev.date_str,
                        ev.time_str,
                        ev.status,
                        round(float(ev.match_score), 4),
                    ]
                    ws.append(row_values)

                    for col_idx in range(1, len(row_values) + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        cell.alignment = Alignment(horizontal="center" if col_idx in (1, 2, 4, 5, 6) else "left")
                        if ev.status == "Present":
                            cell.fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")
                        elif ev.status == "Absent":
                            cell.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

                    existing_pairs.add(pair)
                    written_count += 1

            # 4. Save and verify readability
            try:
                # Save to a temporary swap path first, then replace to prevent file corruption
                temp_file = self.attendance_file.with_suffix(".tmp.xlsx")
                wb.save(temp_file)
                wb.close()

                # Verify temporary file is readable
                verify_wb = openpyxl.load_workbook(temp_file, read_only=True)
                verify_wb.close()

                # Atomically replace destination
                if temp_file.exists():
                    temp_file.replace(self.attendance_file)
                logger.info("Persisted %d attendance events to %s", written_count, self.attendance_file.name)
            except Exception as exc:
                err_msg = f"Failed to persist attendance to {self.attendance_file}: {exc}"
                logger.error(err_msg)
                errors.append(err_msg)

        return written_count, errors

    def _write_header(self, ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
        """Write and style the attendance header row."""
        ws.delete_rows(1, ws.max_row)
        ws.append(self.ATTENDANCE_COLUMNS)

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_align = Alignment(horizontal="center", vertical="center")

        for col_idx in range(1, len(self.ATTENDANCE_COLUMNS) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            # Column widths
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 18

    def append_student_record(
        self,
        student_id: str,
        name: str,
        photo_path_str: str,
        id_card_path_str: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """Append a new student record to data/students.xlsx atomically under lock.

        Returns:
            (success, error_message)
        """
        sid_clean = str(student_id).strip()
        name_clean = str(name).strip()
        path_clean = str(photo_path_str).strip()
        card_clean = str(id_card_path_str).strip() if id_card_path_str else ""

        if not sid_clean or not name_clean or not path_clean:
            return False, "Student ID, Name, and Photo path must not be empty."

        with self._write_lock:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            wb: openpyxl.Workbook
            ws: openpyxl.worksheet.worksheet.Worksheet

            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")

            if self.registry_file.exists():
                try:
                    wb = openpyxl.load_workbook(self.registry_file)
                    ws = wb.active
                except Exception as exc:
                    return False, f"Failed to open registry file: {exc}"
            else:
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = "Students"
                cols = self.REQUIRED_REGISTRY_COLUMNS + (["id_card_path"] if card_clean else [])
                ws.append(cols)
                for c in range(1, len(cols) + 1):
                    cell = ws.cell(row=1, column=c)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                    ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 24

            # Ensure id_card_path header exists if we have an ID card
            has_id_card_col = False
            for c in range(1, ws.max_column + 1):
                val = ws.cell(row=1, column=c).value
                if val and str(val).strip().lower() == "id_card_path":
                    has_id_card_col = True
                    break

            if card_clean and not has_id_card_col:
                new_col = ws.max_column + 1
                cell = ws.cell(row=1, column=new_col, value="id_card_path")
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")
                ws.column_dimensions[openpyxl.utils.get_column_letter(new_col)].width = 24
                has_id_card_col = True

            # Verify uniqueness of student_id
            for r in range(2, ws.max_row + 1):
                existing_sid = ws.cell(row=r, column=1).value
                if existing_sid and str(existing_sid).strip().lower() == sid_clean.lower():
                    wb.close()
                    return False, f"Student ID '{sid_clean}' already exists in registry."

            # Append new record
            row_idx = ws.max_row + 1
            if has_id_card_col:
                ws.append([sid_clean, name_clean, path_clean, card_clean])
                num_cols = 4
            else:
                ws.append([sid_clean, name_clean, path_clean])
                num_cols = 3

            for col_idx in range(1, num_cols + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.alignment = Alignment(horizontal="center" if col_idx == 1 else "left")

            # Save atomically to temp file first
            temp_file = self.registry_file.with_suffix(".tmp.xlsx")
            try:
                wb.save(temp_file)
                wb.close()
                # Verify readability
                v_wb = openpyxl.load_workbook(temp_file, read_only=True)
                v_wb.close()
                if temp_file.exists():
                    temp_file.replace(self.registry_file)
                logger.info("Successfully appended student %s to %s", sid_clean, self.registry_file.name)
                return True, None
            except Exception as exc:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
                logger.error("Failed to save registry file: %s", exc)
                return False, f"Failed to save updated registry workbook: {exc}"

    def get_student_by_id(self, student_id: str) -> Optional[StudentRecord]:
        """Fetch a single student record by student_id from registry."""
        sid_clean = str(student_id).strip().lower()
        records, _ = self.read_registry()
        for rec in records:
            if rec.student_id.strip().lower() == sid_clean:
                return rec
        return None

    def get_attendance_record(self, session_id: str, student_id: str) -> Optional[dict]:
        """Fetch one attendance record by session_id and student_id from attendance.xlsx."""
        if not session_id or not student_id:
            return None
        sess_clean = str(session_id).strip().lower()
        sid_clean = str(student_id).strip().lower()

        df = self.load_existing_attendance()
        if df.empty or "session_id" not in df.columns or "student_id" not in df.columns:
            return None

        match = df[
            (df["session_id"].astype(str).str.strip().str.lower() == sess_clean)
            & (df["student_id"].astype(str).str.strip().str.lower() == sid_clean)
        ]
        if match.empty:
            return None

        row = match.iloc[0]
        return {
            "session_id": str(row.get("session_id", "")),
            "student_id": str(row.get("student_id", "")),
            "name": str(row.get("name", "")),
            "date": str(row.get("date", "")),
            "time": str(row.get("time", "")),
            "status": str(row.get("status", "")),
            "match_score": float(row.get("match_score", 0.0)),
        }

    def remove_student_record(self, student_id: str) -> bool:
        """Remove a student row from data/students.xlsx (used for transactional rollback)."""
        sid_clean = str(student_id).strip().lower()
        with self._write_lock:
            if not self.registry_file.exists():
                return False

            try:
                wb = openpyxl.load_workbook(self.registry_file)
                ws = wb.active
                row_to_delete = None
                for r in range(2, ws.max_row + 1):
                    val = ws.cell(row=r, column=1).value
                    if val and str(val).strip().lower() == sid_clean:
                        row_to_delete = r
                        break

                if row_to_delete:
                    ws.delete_rows(row_to_delete, 1)
                    temp_file = self.registry_file.with_suffix(".tmp.xlsx")
                    wb.save(temp_file)
                    wb.close()
                    if temp_file.exists():
                        temp_file.replace(self.registry_file)
                    logger.info("Rolled back student %s from %s", student_id, self.registry_file.name)
                    return True
                wb.close()
                return False
            except Exception as exc:
                logger.error("Error during student record rollback: %s", exc)
                return False

    def get_sheet_data(self, sheet_type: str = "attendance") -> dict:
        """Read live Excel data from disk and return structured rows, columns, and metrics."""
        with self._write_lock:
            if sheet_type == "attendance":
                target_file = self.attendance_file
                default_cols = self.ATTENDANCE_COLUMNS
            else:
                target_file = self.registry_file
                default_cols = ["student_id", "name", "photo_path", "id_card_path"]

            if not target_file.exists():
                return {
                    "file_name": target_file.name,
                    "exists": False,
                    "last_modified": None,
                    "file_size_bytes": 0,
                    "columns": default_cols,
                    "rows": [],
                    "summary": {"total_rows": 0},
                }

            try:
                wb = openpyxl.load_workbook(target_file, data_only=True)
                ws = wb.active

                # Read headers from row 1
                headers = []
                for c in range(1, ws.max_column + 1):
                    val = ws.cell(row=1, column=c).value
                    if val is not None:
                        headers.append(str(val).strip())
                    elif c <= len(default_cols):
                        headers.append(default_cols[c - 1])

                if not headers:
                    headers = list(default_cols)

                rows = []
                for r in range(2, ws.max_row + 1):
                    row_dict = {}
                    has_val = False
                    for c, h in enumerate(headers, start=1):
                        val = ws.cell(row=r, column=c).value
                        if val is not None:
                            has_val = True
                            if isinstance(val, (int, float)):
                                row_dict[h] = val
                            else:
                                row_dict[h] = str(val).strip()
                        else:
                            row_dict[h] = ""
                    if has_val:
                        rows.append(row_dict)

                wb.close()

                stat = target_file.stat()
                from datetime import datetime

                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                summary = {"total_rows": len(rows)}
                if sheet_type == "attendance":
                    present_cnt = sum(
                        1 for row in rows if str(row.get("status", "")).strip().lower() == "present"
                    )
                    absent_cnt = sum(
                        1 for row in rows if str(row.get("status", "")).strip().lower() == "absent"
                    )
                    unique_students = len(
                        {str(row.get("student_id", "")).strip() for row in rows if row.get("student_id")}
                    )
                    unique_dates = len(
                        {str(row.get("date", "")).strip() for row in rows if row.get("date")}
                    )
                    summary.update(
                        {
                            "present_count": present_cnt,
                            "absent_count": absent_cnt,
                            "unique_students": unique_students,
                            "unique_dates": unique_dates,
                            "rate_percent": round((present_cnt / len(rows) * 100), 1) if rows else 0.0,
                        }
                    )
                else:
                    with_photos = sum(1 for row in rows if bool(row.get("photo_path")))
                    with_cards = sum(1 for row in rows if bool(row.get("id_card_path")))
                    summary.update(
                        {
                            "total_students": len(rows),
                            "with_photo": with_photos,
                            "with_id_card": with_cards,
                        }
                    )

                return {
                    "file_name": target_file.name,
                    "exists": True,
                    "last_modified": mod_time,
                    "file_size_bytes": stat.st_size,
                    "columns": headers,
                    "rows": rows,
                    "summary": summary,
                }
            except Exception as exc:
                logger.error("Failed to read sheet data from %s: %s", target_file, exc)
                return {
                    "file_name": target_file.name,
                    "exists": True,
                    "error": str(exc),
                    "columns": default_cols,
                    "rows": [],
                    "summary": {"total_rows": 0},
                }

    def clear_all_data(self) -> tuple[bool, str]:
        """Clear all student records from students.xlsx and attendance records from attendance.xlsx.

        Re-initializes both workbooks with clean headers.
        """
        with self._write_lock:
            try:
                # 1. Clear students.xlsx
                wb_s = openpyxl.Workbook()
                ws_s = wb_s.active
                ws_s.title = "Students"
                s_cols = ["student_id", "name", "photo_path", "id_card_path"]
                ws_s.append(s_cols)

                header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
                for c in range(1, len(s_cols) + 1):
                    cell = ws_s.cell(row=1, column=c)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                    ws_s.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 24

                self.registry_file.parent.mkdir(parents=True, exist_ok=True)
                wb_s.save(self.registry_file)
                wb_s.close()

                # 2. Clear attendance.xlsx
                wb_a = openpyxl.Workbook()
                ws_a = wb_a.active
                ws_a.title = "Attendance"
                self._write_header(ws_a)
                wb_a.save(self.attendance_file)
                wb_a.close()

                logger.info("Cleared students and attendance workbooks to fresh state.")
                return True, "Workbooks successfully cleared."
            except Exception as exc:
                logger.error("Failed to clear workbooks: %s", exc)
                return False, f"Failed to clear workbooks: {exc}"

    def deduplicate_attendance(self) -> int:
        """Deduplicate existing rows in attendance.xlsx, keeping 1 row per student per date."""
        with self._write_lock:
            if not self.attendance_file.exists():
                return 0

            try:
                wb = openpyxl.load_workbook(self.attendance_file)
                if "Attendance" not in wb.sheetnames:
                    wb.close()
                    return 0
                ws = wb["Attendance"]

                rows_data = []
                for r in range(2, ws.max_row + 1):
                    row_vals = [ws.cell(row=r, column=c).value for c in range(1, 8)]
                    if any(v is not None for v in row_vals):
                        rows_data.append(row_vals)

                if not rows_data:
                    wb.close()
                    return 0

                grouped: dict[tuple[str, str], list[list]] = {}
                for row in rows_data:
                    sess_id, sid, name, dt, tm, status, score = row
                    key = (str(dt).strip() if dt else "", str(sid).strip().lower() if sid else "")
                    if key not in grouped:
                        grouped[key] = []
                    grouped[key].append(row)

                initial_count = len(rows_data)
                consolidated: list[list] = []

                for key, items in grouped.items():
                    if len(items) == 1:
                        consolidated.append(items[0])
                        continue

                    def sort_key(item):
                        status = str(item[5] or "").strip().lower()
                        status_rank = 1 if status == "present" else 0
                        time_str = str(item[4] or "").strip()
                        return (status_rank, time_str)

                    best_item = max(items, key=sort_key)
                    consolidated.append(best_item)

                removed_count = initial_count - len(consolidated)
                if removed_count == 0:
                    wb.close()
                    return 0

                ws.delete_rows(2, ws.max_row)
                for row_values in consolidated:
                    ws.append(row_values)
                    row_idx = ws.max_row
                    status = str(row_values[5] or "").strip()
                    for col_idx in range(1, len(row_values) + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        cell.alignment = Alignment(horizontal="center" if col_idx in (1, 2, 4, 5, 6) else "left")
                        if status == "Present":
                            cell.fill = PatternFill(start_color="E2F0D9", end_color="E2F0D9", fill_type="solid")
                        elif status == "Absent":
                            cell.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")

                temp_file = self.attendance_file.with_suffix(".tmp.xlsx")
                wb.save(temp_file)
                wb.close()
                if temp_file.exists():
                    temp_file.replace(self.attendance_file)

                logger.info(
                    "Deduplicated %s: removed %d redundant rows, %d rows remain.",
                    self.attendance_file.name,
                    removed_count,
                    len(consolidated),
                )
                return removed_count
            except Exception as exc:
                logger.error("Failed to deduplicate %s: %s", self.attendance_file, exc)
                return 0

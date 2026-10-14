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

    def __init__(self, project_root: Path, registry_file: Path, attendance_file: Path):
        self.project_root = Path(project_root).resolve()
        self.registry_file = Path(registry_file).resolve()
        self.attendance_file = Path(attendance_file).resolve()
        self._write_lock = threading.Lock()

    def resolve_photo_path(self, raw_path: str) -> Path:
        """Resolve a photo path string to an absolute Path.

        Checks:
        1. As absolute path if already absolute.
        2. Relative to project root.
        3. Relative to data directory.
        4. Relative to data/photos directory.
        """
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

            records.append(
                StudentRecord(
                    student_id=student_id,
                    name=name,
                    photo_path=resolved_photo,
                    raw_photo_path=raw_photo_path,
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

            # 2. Collect existing session_id + student_id pairs to enforce strict uniqueness
            existing_pairs: set[tuple[str, str]] = set()
            for r in range(2, ws.max_row + 1):
                sess_cell = ws.cell(row=r, column=1).value
                sid_cell = ws.cell(row=r, column=2).value
                if sess_cell and sid_cell:
                    existing_pairs.add((str(sess_cell).strip(), str(sid_cell).strip()))

            # 3. Append new records
            for ev in events:
                pair = (ev.session_id.strip(), ev.student_id.strip())
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

                # Format row cells
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
        self, student_id: str, name: str, photo_path_str: str
    ) -> tuple[bool, Optional[str]]:
        """Append a new student record to data/students.xlsx atomically under lock.

        Returns:
            (success, error_message)
        """
        sid_clean = str(student_id).strip()
        name_clean = str(name).strip()
        path_clean = str(photo_path_str).strip()

        if not sid_clean or not name_clean or not path_clean:
            return False, "Student ID, Name, and Photo path must not be empty."

        with self._write_lock:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            wb: openpyxl.Workbook
            ws: openpyxl.worksheet.worksheet.Worksheet

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
                ws.append(self.REQUIRED_REGISTRY_COLUMNS)
                header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
                for c in range(1, len(self.REQUIRED_REGISTRY_COLUMNS) + 1):
                    cell = ws.cell(row=1, column=c)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = Alignment(horizontal="center")
                    ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = 24

            # Verify uniqueness of student_id
            for r in range(2, ws.max_row + 1):
                existing_sid = ws.cell(row=r, column=1).value
                if existing_sid and str(existing_sid).strip().lower() == sid_clean.lower():
                    wb.close()
                    return False, f"Student ID '{sid_clean}' already exists in registry."

            # Append new record
            row_idx = ws.max_row + 1
            ws.append([sid_clean, name_clean, path_clean])
            for col_idx in range(1, 4):
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

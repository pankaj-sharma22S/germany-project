"""Template Generator.

Generates a formatted data/students.xlsx template file without fabricating
data or overwriting any existing registry.
"""

from pathlib import Path
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from app.config import Config, default_config


def create_students_template(target_path: Path | None = None, overwrite: bool = False) -> Path:
    """Create a formatted students.xlsx file with required columns."""
    cfg = default_config
    file_path = Path(target_path) if target_path else cfg.students_file

    if file_path.exists() and not overwrite:
        print(f"File already exists at: {file_path}. Skipping creation to prevent data loss.")
        return file_path

    file_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Students"

    columns = ["student_id", "name", "photo_path"]
    ws.append(columns)

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")

    for col_idx in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 24

    # Add explanatory comment row or hint row
    sample_hint = ["S101", "Full Name", "photos/S101.jpg"]
    ws.append(sample_hint)
    for col_idx in range(1, len(sample_hint) + 1):
        cell = ws.cell(row=2, column=col_idx)
        cell.font = Font(name="Calibri", size=10, italic=True, color="7F7F7F")
        cell.alignment = Alignment(horizontal="center" if col_idx == 1 else "left")

    wb.save(file_path)
    wb.close()
    print(f"Created student registry template at: {file_path}")
    return file_path


if __name__ == "__main__":
    create_students_template()

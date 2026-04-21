"""Excel formatting package — styling rules, data-sheet styling, notes-sheet generation.

Public entry points:
    apply_formatting(file_path, profile)     — styling.py
    add_notes_sheet_to_ledger(path, stype)   — notes.py
"""

from .styling import apply_formatting
from .notes import add_notes_sheet_to_ledger

__all__ = ["apply_formatting", "add_notes_sheet_to_ledger"]

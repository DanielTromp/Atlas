"""Export skill for generating downloadable files (xlsx, csv, txt, docx).

This skill allows agents to export data to files that can be
uploaded to chat platforms for users to download.

IMPORTANT: Data must be passed explicitly to each export call.
The export tools do NOT remember data from previous calls.
"""

from __future__ import annotations

import json
from typing import Any

from infrastructure_atlas.ai.tools.export_handlers import (
    cleanup_old_exports,
    generate_csv,
    generate_docx,
    generate_export,
    generate_txt,
    generate_xlsx,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill, SkillConfig

logger = get_logger(__name__)


class ExportSkill(BaseSkill):
    """Skill for exporting data to downloadable files.

    Supports:
    - Excel (.xlsx) - formatted spreadsheets with styling
    - CSV (.csv) - comma-separated values for data exchange
    - Text (.txt) - plain text with tabular formatting
    - Word (.docx) - formatted document with table
    
    IMPORTANT: Each export call requires the full data to be passed.
    Data is NOT stored between calls.
    """

    name = "export"
    category = "export"
    description = "Export data to downloadable files (Excel, CSV, Text, Word)"

    SUPPORTED_FORMATS = ["xlsx", "csv", "txt", "docx"]

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config)

    def initialize(self) -> None:
        """Initialize the export skill and register actions."""
        self.register_action(
            name="to_file",
            func=self._export_to_file,
            description="""Export data to a downloadable file. Supports multiple formats.

CRITICAL: You MUST pass the full data array every time you call this tool.
Data is NOT stored between export calls. If user asks to "export to txt" after
you already exported to xlsx, you must include the SAME data array again.

Use this when the user wants to export data. Choose format based on user request:
- "export to excel" / "xlsx" / "spreadsheet" → format="xlsx"
- "export to csv" / "comma separated" → format="csv"  
- "export to text" / "txt" / "plain text" → format="txt"
- "export to word" / "docx" / "document" → format="docx"

Default format is xlsx (Excel) if not specified.

REQUIRED parameters:
- data: List of dictionaries (MUST be provided every call, NOT optional)
- filename: Base filename without extension

Example call:
{
  "data": [
    {"Ticket": "ESD-123", "Summary": "Server down", "Status": "Open"},
    {"Ticket": "ESD-124", "Summary": "Network issue", "Status": "Closed"}
  ],
  "filename": "My_Export",
  "file_format": "txt"
}

The file will be automatically uploaded to the chat for the user to download.""",
            is_destructive=False,
            requires_confirmation=False,
        )

        # Keep backward compatibility with to_xlsx
        self.register_action(
            name="to_xlsx",
            func=self._export_to_xlsx,
            description="""Export data to an Excel (.xlsx) file for download.

CRITICAL: You MUST pass the full data array every time. Data is NOT stored between calls.

REQUIRED parameters:
- data: List of dictionaries (MUST be provided, NOT optional)
- filename: Base filename without extension

Example:
{
  "data": [{"Ticket": "ESD-123", "Summary": "Issue", "Status": "Open"}],
  "filename": "My_Tickets"
}""",
            is_destructive=False,
            requires_confirmation=False,
        )

        self.register_action(
            name="to_csv",
            func=self._export_to_csv,
            description="""Export data to a CSV file for download.

CRITICAL: You MUST pass the full data array every time. Data is NOT stored between calls.

REQUIRED parameters:
- data: List of dictionaries (MUST be provided, NOT optional)
- filename: Base filename without extension""",
            is_destructive=False,
            requires_confirmation=False,
        )

        self.register_action(
            name="to_txt",
            func=self._export_to_txt,
            description="""Export data to a plain text file with tabular formatting.

CRITICAL: You MUST pass the full data array every time. Data is NOT stored between calls.

REQUIRED parameters:
- data: List of dictionaries (MUST be provided, NOT optional)
- filename: Base filename without extension""",
            is_destructive=False,
            requires_confirmation=False,
        )

        self.register_action(
            name="to_docx",
            func=self._export_to_docx,
            description="""Export data to a Word document (.docx) with a formatted table.

CRITICAL: You MUST pass the full data array every time. Data is NOT stored between calls.

REQUIRED parameters:
- data: List of dictionaries (MUST be provided, NOT optional)
- filename: Base filename without extension""",
            is_destructive=False,
            requires_confirmation=False,
        )

        logger.info("Export skill initialized with formats: " + ", ".join(self.SUPPORTED_FORMATS))

    def _normalize_data(self, data: Any) -> list[dict[str, Any]] | None:
        """Normalize data input - handles JSON strings, lists, etc.
        
        The agent sometimes passes data as a JSON string instead of a list.
        This method handles that case.
        
        Returns:
            Normalized list of dicts, or None if invalid
        """
        if data is None:
            return None
            
        # If it's already a list, return as-is
        if isinstance(data, list):
            return data
            
        # If it's a string, try to parse as JSON
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                if isinstance(parsed, list):
                    logger.debug(f"Parsed JSON string to list with {len(parsed)} items")
                    return parsed
                else:
                    logger.warning(f"JSON string parsed to non-list: {type(parsed)}")
                    return None
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse data string as JSON: {e}")
                return None
        
        logger.warning(f"Unexpected data type: {type(data)}")
        return None

    def _validate_and_normalize_data(self, data: Any, format_name: str) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Validate and normalize export data.
        
        Returns:
            Tuple of (normalized_data, error_message)
            If valid: (data, None)
            If invalid: (None, error_message)
        """
        if data is None:
            return None, f"ERROR: 'data' parameter is required for {format_name} export. You must pass the full data array."
        
        # Normalize data (handles JSON strings)
        normalized = self._normalize_data(data)
        
        if normalized is None:
            return None, f"ERROR: 'data' must be a list of dictionaries. Got {type(data).__name__}. If passing JSON, ensure it's a valid array."
        
        if len(normalized) == 0:
            return None, f"ERROR: 'data' list is empty. Nothing to export to {format_name}."
        
        return normalized, None

    def _export_to_file(
        self,
        data: list[dict[str, Any]] | str,
        filename: str,
        file_format: str = "xlsx",
        sheet_name: str = "Data",
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export data to a file in the specified format.

        Args:
            data: List of dictionaries to export (or JSON string) - REQUIRED
            filename: Base filename for the export (without extension) - REQUIRED
            file_format: Output format: xlsx, csv, txt, or docx (default: xlsx)
            sheet_name: Name for the worksheet (xlsx only, default: "Data")
            title: Optional title for the document

        Returns:
            Dictionary with file_path, filename, file_type, row_count, and message
        """
        # Validate and normalize data
        normalized_data, error = self._validate_and_normalize_data(data, file_format)
        if error:
            logger.error(f"Export validation failed: {error}")
            return {"success": False, "error": error}

        logger.info(f"Exporting {len(normalized_data)} rows to {file_format}: {filename}")

        result = generate_export(
            data=normalized_data,
            filename=filename,
            file_format=file_format,
            title=title,
            sheet_name=sheet_name,
        )

        if result.get("success"):
            logger.info(f"Export successful: {result.get('file_path')}")
        else:
            logger.error(f"Export failed: {result.get('error')}")

        return result

    def _export_to_xlsx(
        self,
        data: list[dict[str, Any]] | str,
        filename: str,
        sheet_name: str = "Data",
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export data to an Excel file.

        Args:
            data: List of dictionaries to export (or JSON string) - REQUIRED
            filename: Base filename for the export (without extension) - REQUIRED
            sheet_name: Name for the worksheet (default: "Data")
            title: Optional title row at the top of the spreadsheet

        Returns:
            Dictionary with file_path, filename, file_type, row_count, and message
        """
        # Validate and normalize data
        normalized_data, error = self._validate_and_normalize_data(data, "xlsx")
        if error:
            logger.error(f"Excel export validation failed: {error}")
            return {"success": False, "error": error}

        logger.info(f"Exporting {len(normalized_data)} rows to Excel: {filename}")

        result = generate_xlsx(
            data=normalized_data,
            filename=filename,
            sheet_name=sheet_name,
            title=title,
        )

        if result.get("success"):
            logger.info(f"Excel export successful: {result.get('file_path')}")
        else:
            logger.error(f"Excel export failed: {result.get('error')}")

        return result

    def _export_to_csv(
        self,
        data: list[dict[str, Any]] | str,
        filename: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export data to a CSV file.

        Args:
            data: List of dictionaries to export (or JSON string) - REQUIRED
            filename: Base filename for the export (without extension) - REQUIRED
            title: Optional title (added as comment)

        Returns:
            Dictionary with file_path, filename, file_type, row_count, and message
        """
        # Validate and normalize data
        normalized_data, error = self._validate_and_normalize_data(data, "csv")
        if error:
            logger.error(f"CSV export validation failed: {error}")
            return {"success": False, "error": error}

        logger.info(f"Exporting {len(normalized_data)} rows to CSV: {filename}")

        result = generate_csv(
            data=normalized_data,
            filename=filename,
            title=title,
        )

        if result.get("success"):
            logger.info(f"CSV export successful: {result.get('file_path')}")
        else:
            logger.error(f"CSV export failed: {result.get('error')}")

        return result

    def _export_to_txt(
        self,
        data: list[dict[str, Any]] | str,
        filename: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export data to a plain text file.

        Args:
            data: List of dictionaries to export (or JSON string) - REQUIRED
            filename: Base filename for the export (without extension) - REQUIRED
            title: Optional title

        Returns:
            Dictionary with file_path, filename, file_type, row_count, and message
        """
        # Validate and normalize data
        normalized_data, error = self._validate_and_normalize_data(data, "txt")
        if error:
            logger.error(f"TXT export validation failed: {error}")
            return {"success": False, "error": error}

        logger.info(f"Exporting {len(normalized_data)} rows to TXT: {filename}")

        result = generate_txt(
            data=normalized_data,
            filename=filename,
            title=title,
        )

        if result.get("success"):
            logger.info(f"TXT export successful: {result.get('file_path')}")
        else:
            logger.error(f"TXT export failed: {result.get('error')}")

        return result

    def _export_to_docx(
        self,
        data: list[dict[str, Any]] | str,
        filename: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Export data to a Word document.

        Args:
            data: List of dictionaries to export (or JSON string) - REQUIRED
            filename: Base filename for the export (without extension) - REQUIRED
            title: Optional document title

        Returns:
            Dictionary with file_path, filename, file_type, row_count, and message
        """
        # Validate and normalize data
        normalized_data, error = self._validate_and_normalize_data(data, "docx")
        if error:
            logger.error(f"DOCX export validation failed: {error}")
            return {"success": False, "error": error}

        logger.info(f"Exporting {len(normalized_data)} rows to DOCX: {filename}")

        result = generate_docx(
            data=normalized_data,
            filename=filename,
            title=title,
        )

        if result.get("success"):
            logger.info(f"DOCX export successful: {result.get('file_path')}")
        else:
            logger.error(f"DOCX export failed: {result.get('error')}")

        return result

    def health_check(self) -> dict[str, Any]:
        """Check export skill health."""
        # Also cleanup old exports during health check
        try:
            cleaned = cleanup_old_exports()
        except Exception:
            cleaned = 0

        return {
            "status": "healthy",
            "skill": self.name,
            "actions": len(self._actions),
            "supported_formats": self.SUPPORTED_FORMATS,
            "cleaned_files": cleaned,
        }

"""Shared CSV rendering for the export endpoints.

One writer for every CSV FleetBox hands out — the backup exports and the cost
report — so they agree on quoting, line endings and the download headers.
Values are written in machine format (ISO dates, ``.`` as the decimal
separator) rather than the localised display format, because these files are
meant to be read back by spreadsheets and by FleetBox's own import.
"""

from __future__ import annotations

import csv
import io

from fastapi.responses import Response


def csv_text(columns: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()


def csv_response(filename: str, columns: list[str], rows: list[list]) -> Response:
    return Response(
        content=csv_text(columns, rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

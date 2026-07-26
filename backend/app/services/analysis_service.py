import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models.file import File

SUPPORTED_ANALYSIS_TYPES = {"csv", "xlsx"}


class FileAnalysisError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def analyze_file(db: Session, file_record: File) -> File:
    file_type = (file_record.file_type or "").lower()
    file_path = Path(file_record.file_path)

    if file_type not in SUPPORTED_ANALYSIS_TYPES:
        raise FileAnalysisError("当前文件类型不支持数据分析，仅支持 CSV 和 Excel 文件")

    if not file_path.exists():
        raise FileAnalysisError("文件不存在，无法分析")

    try:
        analysis_result = _analyze_by_type(file_type, file_path)
    except Exception as exc:
        raise FileAnalysisError(f"数据分析失败：{exc}") from exc

    schema = _load_existing_schema(file_record.schema_json)
    schema["analysis_result"] = analysis_result
    file_record.schema_json = json.dumps(schema, ensure_ascii=False)
    if file_record.status == "pending":
        file_record.status = "parsed"

    db.commit()
    db.refresh(file_record)
    return file_record


def _analyze_by_type(file_type: str, file_path: Path) -> dict[str, Any]:
    if file_type == "csv":
        dataframe = pd.read_csv(file_path)
        result = _build_analysis_result(dataframe)
        result["file_type"] = "csv"
        return result

    with pd.ExcelFile(file_path) as workbook:
        sheet_name = workbook.sheet_names[0]
        dataframe = pd.read_excel(workbook, sheet_name=sheet_name)

    result = _build_analysis_result(dataframe)
    result["file_type"] = "xlsx"
    result["sheet_name"] = sheet_name
    return result


def _build_analysis_result(dataframe: pd.DataFrame) -> dict[str, Any]:
    date_columns = _detect_date_columns(dataframe)
    numeric_columns = dataframe.select_dtypes(include=["number"]).columns.tolist()
    text_columns = [
        column
        for column in dataframe.columns.tolist()
        if column not in numeric_columns and column not in date_columns
    ]

    return {
        "row_count": int(dataframe.shape[0]),
        "column_count": int(dataframe.shape[1]),
        "columns": dataframe.columns.tolist(),
        "column_types": {column: str(dataframe[column].dtype) for column in dataframe.columns},
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "date_columns": date_columns,
        "missing_values": {column: int(dataframe[column].isna().sum()) for column in dataframe.columns},
        "numeric_statistics": _build_numeric_statistics(dataframe, numeric_columns),
        "text_top_values": _build_text_top_values(dataframe, text_columns),
        "preview_rows": _to_preview_rows(dataframe),
    }


def _build_numeric_statistics(dataframe: pd.DataFrame, numeric_columns: list[str]) -> dict[str, dict[str, Any]]:
    statistics: dict[str, dict[str, Any]] = {}

    for column in numeric_columns:
        series = dataframe[column]
        statistics[column] = {
            "count": _to_json_value(series.count()),
            "mean": _to_json_value(series.mean()),
            "min": _to_json_value(series.min()),
            "max": _to_json_value(series.max()),
            "sum": _to_json_value(series.sum()),
        }

    return statistics


def _build_text_top_values(dataframe: pd.DataFrame, text_columns: list[str]) -> dict[str, list[dict[str, Any]]]:
    top_values: dict[str, list[dict[str, Any]]] = {}

    for column in text_columns:
        value_counts = dataframe[column].dropna().astype(str).value_counts().head(5)
        top_values[column] = [
            {
                "value": value,
                "count": int(count),
            }
            for value, count in value_counts.items()
        ]

    return top_values


def _detect_date_columns(dataframe: pd.DataFrame) -> list[str]:
    date_columns: list[str] = []

    for column in dataframe.columns:
        series = dataframe[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            date_columns.append(column)
            continue

        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            continue

        non_empty = series.dropna()
        if non_empty.empty:
            continue

        parsed = pd.to_datetime(non_empty, errors="coerce", format="mixed")

        if parsed.notna().sum() / len(non_empty) >= 0.8:
            date_columns.append(column)

    return date_columns


def _to_preview_rows(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for record in dataframe.head(5).to_dict(orient="records"):
        rows.append({key: _to_json_value(value) for key, value in record.items()})
    return rows


def _to_json_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        return value.item()

    return value


def _load_existing_schema(schema_json: str | None) -> dict[str, Any]:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    if isinstance(data, dict):
        return data

    return {}

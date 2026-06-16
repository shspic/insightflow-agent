import json
import os
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR, settings
from app.models.file import File
from app.services.analysis_service import _detect_date_columns

matplotlib_cache_dir = BACKEND_DIR / "data" / "matplotlib-cache"
matplotlib_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache_dir))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

SUPPORTED_CHART_TYPES = {"csv", "xlsx"}


class FileChartError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def generate_charts(db: Session, file_record: File) -> File:
    file_type = (file_record.file_type or "").lower()
    file_path = Path(file_record.file_path)

    if file_type not in SUPPORTED_CHART_TYPES:
        raise FileChartError("当前文件类型不支持图表生成，仅支持 CSV 和 Excel 文件")

    if not file_path.exists():
        raise FileChartError("文件不存在，无法生成图表")

    try:
        dataframe = _read_table_file(file_type, file_path)
        charts = _build_charts(file_record.id, dataframe, _resolve_chart_dir())
    except Exception as exc:
        raise FileChartError(f"图表生成失败：{exc}") from exc

    schema = _load_existing_schema(file_record.schema_json)
    schema["charts"] = charts
    file_record.schema_json = json.dumps(schema, ensure_ascii=False)
    if file_record.status == "pending":
        file_record.status = "parsed"

    db.commit()
    db.refresh(file_record)
    return file_record


def _read_table_file(file_type: str, file_path: Path) -> pd.DataFrame:
    if file_type == "csv":
        return pd.read_csv(file_path)

    with pd.ExcelFile(file_path) as workbook:
        sheet_name = workbook.sheet_names[0]
        return pd.read_excel(workbook, sheet_name=sheet_name)


def _resolve_chart_dir() -> Path:
    chart_dir = Path(settings.chart_dir)
    if not chart_dir.is_absolute():
        chart_dir = BACKEND_DIR / chart_dir
    chart_dir.mkdir(parents=True, exist_ok=True)
    return chart_dir


def _build_charts(file_id: int, dataframe: pd.DataFrame, chart_dir: Path) -> list[dict]:
    return [
        _create_missing_values_chart(file_id, dataframe, chart_dir),
        _create_numeric_chart(file_id, dataframe, chart_dir),
        _create_text_chart(file_id, dataframe, chart_dir),
    ]


def _create_missing_values_chart(file_id: int, dataframe: pd.DataFrame, chart_dir: Path) -> dict:
    missing_values = dataframe.isna().sum().astype(int)
    return _save_bar_chart(
        file_id=file_id,
        chart_type="missing_values",
        title="缺失值统计",
        labels=[str(label) for label in missing_values.index],
        values=missing_values.tolist(),
        chart_dir=chart_dir,
        description="展示每个字段的缺失值数量；没有缺失值时数值为 0。",
    )


def _create_numeric_chart(file_id: int, dataframe: pd.DataFrame, chart_dir: Path) -> dict:
    numeric_columns = dataframe.select_dtypes(include=["number"]).columns.tolist()
    if not numeric_columns:
        return _skipped_chart(
            chart_type="numeric_summary",
            title="数值列统计",
            description="未检测到数值列，已跳过数值列统计图。",
        )

    column = numeric_columns[0]
    series = dataframe[column]
    labels = ["count", "mean", "min", "max", "sum"]
    values = [
        float(series.count()),
        float(series.mean()) if series.count() else 0,
        float(series.min()) if series.count() else 0,
        float(series.max()) if series.count() else 0,
        float(series.sum()) if series.count() else 0,
    ]

    return _save_bar_chart(
        file_id=file_id,
        chart_type="numeric_summary",
        title=f"数值列统计：{column}",
        labels=labels,
        values=values,
        chart_dir=chart_dir,
        description=f"展示数值列「{column}」的 count、mean、min、max、sum。",
    )


def _create_text_chart(file_id: int, dataframe: pd.DataFrame, chart_dir: Path) -> dict:
    date_columns = _detect_date_columns(dataframe)
    numeric_columns = dataframe.select_dtypes(include=["number"]).columns.tolist()
    text_columns = [
        column
        for column in dataframe.columns.tolist()
        if column not in numeric_columns and column not in date_columns
    ]

    if not text_columns:
        return _skipped_chart(
            chart_type="category_top5",
            title="分类字段 Top 5",
            description="未检测到文本列，已跳过分类字段 Top 5 图。",
        )

    column = text_columns[0]
    value_counts = dataframe[column].dropna().astype(str).value_counts().head(5)
    if value_counts.empty:
        return _skipped_chart(
            chart_type="category_top5",
            title=f"分类字段 Top 5：{column}",
            description=f"文本列「{column}」没有可统计的非空值，已跳过分类图。",
        )

    return _save_bar_chart(
        file_id=file_id,
        chart_type="category_top5",
        title=f"分类字段 Top 5：{column}",
        labels=[str(label) for label in value_counts.index],
        values=value_counts.astype(int).tolist(),
        chart_dir=chart_dir,
        description=f"展示文本列「{column}」出现次数最多的前 5 个值。",
    )


def _save_bar_chart(
    file_id: int,
    chart_type: str,
    title: str,
    labels: list[str],
    values: list[float],
    chart_dir: Path,
    description: str,
) -> dict:
    filename = f"file_{file_id}_{chart_type}_{uuid4().hex}.png"
    output_path = chart_dir / filename

    figure, axis = plt.subplots(figsize=(9, 4.8))
    axis.bar(labels, values, color="#0A9396")
    axis.set_title(title)
    axis.set_ylabel("数量")
    axis.tick_params(axis="x", labelrotation=30)
    figure.tight_layout()
    figure.savefig(output_path, dpi=140)
    plt.close(figure)

    return {
        "chart_type": chart_type,
        "title": title,
        "file_path": f"storage/charts/{filename}",
        "url_path": f"/static/charts/{filename}",
        "description": description,
        "skipped": False,
    }


def _skipped_chart(chart_type: str, title: str, description: str) -> dict:
    return {
        "chart_type": chart_type,
        "title": title,
        "file_path": None,
        "url_path": None,
        "description": description,
        "skipped": True,
    }


def _load_existing_schema(schema_json: str | None) -> dict:
    if not schema_json:
        return {}

    try:
        data = json.loads(schema_json)
    except json.JSONDecodeError:
        return {}

    if isinstance(data, dict):
        return data

    return {}

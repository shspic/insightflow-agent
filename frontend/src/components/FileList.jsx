import { Fragment } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function formatDate(value) {
  if (!value) {
    return "-";
  }

  return new Date(value).toLocaleString("zh-CN");
}

function parseSchema(schemaJson) {
  if (!schemaJson) {
    return null;
  }

  try {
    return JSON.parse(schemaJson);
  } catch {
    return null;
  }
}

function renderList(values) {
  if (!values || values.length === 0) {
    return "-";
  }

  return values.join("，");
}

function isAnalyzable(file) {
  return file.file_type === "csv" || file.file_type === "xlsx";
}

function isPdf(file) {
  return file.file_type === "pdf";
}

function isImage(file) {
  return file.file_type === "png" || file.file_type === "jpg" || file.file_type === "jpeg";
}

function ParseResult({ file }) {
  const schema = parseSchema(file.schema_json);

  if (!file.summary && !schema) {
    return <p className="parse-empty">尚未解析</p>;
  }

  if (!schema) {
    return <p className="parse-summary">{file.summary}</p>;
  }

  if (schema.file_type === "csv" || schema.file_type === "xlsx") {
    return (
      <div className="parse-result">
        <p className="parse-summary">{file.summary}</p>
        <div className="parse-grid">
          {schema.sheet_name && <span>Sheet：{schema.sheet_name}</span>}
          <span>行数：{schema.row_count}</span>
          <span>列数：{schema.column_count}</span>
          <span>字段：{renderList(schema.columns)}</span>
          <span>数值列：{renderList(schema.numeric_columns)}</span>
          <span>文本列：{renderList(schema.text_columns)}</span>
          <span>日期列：{renderList(schema.date_columns)}</span>
        </div>
        <div className="missing-values">
          <strong>缺失值统计：</strong>
          {Object.entries(schema.missing_values ?? {}).map(([column, count]) => (
            <span key={column}>
              {column}: {count}
            </span>
          ))}
        </div>
        <PreviewTable rows={schema.preview_rows ?? []} columns={schema.columns ?? []} />
        <AnalysisResult analysis={schema.analysis_result} />
        <ChartResult charts={schema.charts ?? []} />
      </div>
    );
  }

  if (schema.file_type === "pdf") {
    const ragIndex = schema.rag_index ?? schema.indexed;

    return (
      <div className="parse-result">
        <p>页数：{schema.page_count}</p>
        {ragIndex && (
          <p>
            索引：{ragIndex.chunk_count} 个片段，检索方式：
            {ragIndex.retrieval_mode ?? ragIndex.type ?? "keyword"}，chunk：
            {ragIndex.chunk_size ?? "-"}，overlap：{ragIndex.chunk_overlap ?? "-"}
          </p>
        )}
        <p className="parse-summary">{file.summary}</p>
      </div>
    );
  }

  return (
    <div className="parse-result">
      <p className="parse-summary">{file.summary}</p>
      <div className="parse-grid">
        <span>文件名：{schema.filename}</span>
        <span>类型：{schema.file_type}</span>
        <span>大小：{schema.file_size} 字节</span>
        <span>OCR：{schema.ocr_result ? "已执行" : "未执行"}</span>
      </div>
      {schema.ocr_result && (
        <div className="analysis-result">
          <h3>OCR 识别结果</h3>
          <p className="parse-summary">{schema.ocr_result.text || "未识别到明显文字。"}</p>
        </div>
      )}
    </div>
  );
}

function AnalysisResult({ analysis }) {
  if (!analysis) {
    return null;
  }

  return (
    <div className="analysis-result">
      <h3>数据分析结果</h3>
      <div className="parse-grid">
        {analysis.sheet_name && <span>Sheet：{analysis.sheet_name}</span>}
        <span>行数：{analysis.row_count}</span>
        <span>列数：{analysis.column_count}</span>
        <span>字段：{renderList(analysis.columns)}</span>
        <span>字段类型：{renderKeyValueMap(analysis.column_types)}</span>
        <span>数值列：{renderList(analysis.numeric_columns)}</span>
        <span>文本列：{renderList(analysis.text_columns)}</span>
        <span>日期列：{renderList(analysis.date_columns)}</span>
      </div>

      <div className="missing-values">
        <strong>缺失值统计：</strong>
        {Object.entries(analysis.missing_values ?? {}).map(([column, count]) => (
          <span key={column}>
            {column}: {count}
          </span>
        ))}
      </div>

      <NumericStatsTable statistics={analysis.numeric_statistics ?? {}} />
      <TextTopValues topValues={analysis.text_top_values ?? {}} />
      <PreviewTable rows={analysis.preview_rows ?? []} columns={analysis.columns ?? []} />
    </div>
  );
}

function ChartResult({ charts }) {
  if (!charts || charts.length === 0) {
    return null;
  }

  return (
    <div className="chart-result">
      <h3>图表结果</h3>
      <div className="chart-grid">
        {charts.map((chart) => (
          <div className="chart-item" key={chart.chart_type}>
            <h4>{chart.title}</h4>
            <p>{chart.description}</p>
            {chart.skipped ? (
              <p className="parse-empty">未生成：{chart.description}</p>
            ) : (
              <img src={`${API_BASE_URL}${chart.url_path}`} alt={chart.title} />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function renderKeyValueMap(values) {
  if (!values || Object.keys(values).length === 0) {
    return "-";
  }

  return Object.entries(values)
    .map(([key, value]) => `${key}: ${value}`)
    .join("，");
}

function NumericStatsTable({ statistics }) {
  const entries = Object.entries(statistics);
  if (entries.length === 0) {
    return <p className="parse-empty">暂无数值列统计</p>;
  }

  return (
    <div className="preview-table-wrap">
      <table className="preview-table">
        <thead>
          <tr>
            <th>字段</th>
            <th>count</th>
            <th>mean</th>
            <th>min</th>
            <th>max</th>
            <th>sum</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([column, stats]) => (
            <tr key={column}>
              <td>{column}</td>
              <td>{formatNumber(stats.count)}</td>
              <td>{formatNumber(stats.mean)}</td>
              <td>{formatNumber(stats.min)}</td>
              <td>{formatNumber(stats.max)}</td>
              <td>{formatNumber(stats.sum)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TextTopValues({ topValues }) {
  const entries = Object.entries(topValues);
  if (entries.length === 0) {
    return <p className="parse-empty">暂无文本列高频值</p>;
  }

  return (
    <div className="top-values">
      <strong>文本列高频值：</strong>
      {entries.map(([column, values]) => (
        <div key={column}>
          <span>{column}：</span>
          <span>
            {values.length === 0
              ? "-"
              : values.map((item) => `${item.value} (${item.count})`).join("，")}
          </span>
        </div>
      ))}
    </div>
  );
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "-";
  }

  if (typeof value === "number") {
    return Number.isInteger(value) ? value : value.toFixed(2);
  }

  return value;
}

function PreviewTable({ rows, columns }) {
  if (rows.length === 0 || columns.length === 0) {
    return null;
  }

  return (
    <div className="preview-table-wrap">
      <table className="preview-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column}>{row[column] ?? "-"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FileList({
  files,
  isLoading,
  error,
  parsingFileIds,
  analyzingFileIds,
  chartingFileIds,
  indexingFileIds,
  ocrFileIds,
  onParse,
  onAnalyze,
  onGenerateCharts,
  onIndexPdf,
  onRunOcr,
  onRefresh,
}) {
  if (isLoading) {
    return <p className="table-state">正在加载文件列表</p>;
  }

  if (error) {
    return (
      <div className="table-state table-state--error">
        <p>{error}</p>
        <button type="button" onClick={onRefresh}>
          重试
        </button>
      </div>
    );
  }

  if (files.length === 0) {
    return <p className="table-state">还没有上传文件</p>;
  }

  return (
    <div className="file-table-wrap">
      <table className="file-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>文件名</th>
            <th>类型</th>
            <th>状态</th>
            <th>上传时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => (
            <Fragment key={file.id}>
              <tr>
                <td>{file.id}</td>
                <td>{file.filename}</td>
                <td>{file.file_type}</td>
                <td>{file.status}</td>
                <td>{formatDate(file.created_at)}</td>
                <td>
                  <div className="row-actions">
                    <button
                      type="button"
                      onClick={() => onParse(file.id)}
                      disabled={parsingFileIds.includes(file.id)}
                    >
                      {parsingFileIds.includes(file.id) ? "解析中" : "解析"}
                    </button>
                    {isAnalyzable(file) ? (
                      <>
                        <button
                          type="button"
                          onClick={() => onAnalyze(file.id)}
                          disabled={analyzingFileIds.includes(file.id)}
                        >
                          {analyzingFileIds.includes(file.id) ? "分析中" : "分析"}
                        </button>
                        <button
                          type="button"
                          onClick={() => onGenerateCharts(file.id)}
                          disabled={chartingFileIds.includes(file.id)}
                        >
                          {chartingFileIds.includes(file.id) ? "生成中" : "生成图表"}
                        </button>
                      </>
                    ) : (
                      <span className="unsupported-action">不支持分析 / 图表</span>
                    )}
                    {isPdf(file) && (
                      <button
                        type="button"
                        onClick={() => onIndexPdf(file.id)}
                        disabled={indexingFileIds.includes(file.id)}
                      >
                        {indexingFileIds.includes(file.id) ? "索引中" : "索引 PDF"}
                      </button>
                    )}
                    {isImage(file) && (
                      <button
                        type="button"
                        onClick={() => onRunOcr(file.id)}
                        disabled={ocrFileIds.includes(file.id)}
                      >
                        {ocrFileIds.includes(file.id) ? "识别中" : "执行 OCR"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
              <tr>
                <td colSpan="6">
                  <ParseResult file={file} />
                </td>
              </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default FileList;

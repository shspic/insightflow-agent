import { Fragment } from "react";

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
      </div>
    );
  }

  if (schema.file_type === "pdf") {
    return (
      <div className="parse-result">
        <p>页数：{schema.page_count}</p>
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
        <span>OCR：暂未实现</span>
      </div>
    </div>
  );
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

function FileList({ files, isLoading, error, parsingFileIds, onParse, onRefresh }) {
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
                  <button
                    type="button"
                    onClick={() => onParse(file.id)}
                    disabled={parsingFileIds.includes(file.id)}
                  >
                    {parsingFileIds.includes(file.id) ? "解析中" : "解析"}
                  </button>
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

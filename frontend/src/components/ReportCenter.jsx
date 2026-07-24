import { useEffect, useMemo, useState } from "react";
import {
  createReportFeedback,
  deleteReportVersion,
  exportReport,
  fetchReportTemplates,
  fetchReportVersions,
  regenerateReport,
  reportDownloadUrl,
  setCurrentReportVersion,
} from "../api/reports";

const FEEDBACK_TYPES = [
  ["like", "有帮助"],
  ["dislike", "没帮助"],
  ["wrong_number", "数字错误"],
  ["wrong_citation", "引用错误"],
  ["missing_content", "缺少内容"],
  ["other", "其他"],
];

export default function ReportCenter({ workspaceId, taskId }) {
  const [reports, setReports] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [templateKey, setTemplateKey] = useState("comprehensive_analysis");
  const [feedbackType, setFeedbackType] = useState("like");
  const [comment, setComment] = useState("");
  const [rerunAnalysis, setRerunAnalysis] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const selected = useMemo(
    () => reports.find((item) => item.id === selectedId) || reports[0],
    [reports, selectedId],
  );

  async function load() {
    if (!taskId) return;
    try {
      const [versions, templateList] = await Promise.all([
        fetchReportVersions(workspaceId, taskId),
        fetchReportTemplates(),
      ]);
      setReports(versions);
      setTemplates(templateList);
      const current = versions.find((item) => item.is_current) || versions[0];
      setSelectedId((value) => value || current?.id || null);
      setTemplateKey(current?.template_key || "comprehensive_analysis");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    setSelectedId(null);
    load();
  }, [workspaceId, taskId]);

  async function run(name, action) {
    setBusy(name);
    try {
      await action();
      await load();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function handleExport(format) {
    if (!selected) return;
    await run(`export-${format}`, async () => {
      const result = await exportReport(workspaceId, taskId, selected.id, format);
      window.location.assign(reportDownloadUrl(result.download_url));
    });
  }

  if (!taskId) return null;
  return (
    <section className="panel report-center">
      <div className="section-heading">
        <div>
          <h3>报告中心</h3>
          <p>版本、导出、引用资产与反馈均以服务端记录为准。</p>
        </div>
        <button type="button" onClick={load}>刷新</button>
      </div>
      {error && <p className="form-message form-message--error">{error}</p>}
      {reports.length === 0 ? (
        <p className="table-state">当前任务还没有 V2-05 报告版本。</p>
      ) : (
        <>
          <div className="report-version-list">
            {reports.map((report) => (
              <button
                type="button"
                className={report.id === selected?.id ? "is-active" : ""}
                key={report.id}
                onClick={() => setSelectedId(report.id)}
              >
                v{report.version} · {report.template_key}
                {report.is_current ? " · 当前" : ""}
                <small>{report.quality_status} · {new Date(report.created_at).toLocaleString("zh-CN")}</small>
              </button>
            ))}
          </div>
          <div className="row-actions">
            {["markdown", "docx", "pdf"].map((format) => (
              <button
                type="button"
                key={format}
                disabled={Boolean(busy)}
                onClick={() => handleExport(format)}
              >
                {busy === `export-${format}` ? "导出中…" : `导出 ${format.toUpperCase()}`}
              </button>
            ))}
            {!selected?.is_current && (
              <>
                <button
                  type="button"
                  disabled={Boolean(busy)}
                  onClick={() => run("current", () =>
                    setCurrentReportVersion(workspaceId, taskId, selected.id))}
                >
                  设为当前版本
                </button>
                <button
                  type="button"
                  disabled={Boolean(busy)}
                  onClick={() => run("delete", () =>
                    deleteReportVersion(workspaceId, taskId, selected.id))}
                >
                  删除历史版本
                </button>
              </>
            )}
          </div>
          <details>
            <summary>引用清单与资产</summary>
            <ul>
              {selected?.assets.map((asset) => (
                <li key={asset.id}>
                  {asset.asset_type} · {asset.display_name} · {asset.status}
                  {asset.download_url && (
                    <> · <a href={reportDownloadUrl(asset.download_url)}>下载</a></>
                  )}
                </li>
              ))}
            </ul>
          </details>
          <article className="report-content">
            <pre>{selected?.markdown_content}</pre>
          </article>
          <div className="report-feedback">
            <h4>反馈与重新生成</h4>
            <label>
              反馈类型
              <select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)}>
                {FEEDBACK_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>
              简短说明
              <textarea rows="3" maxLength="2000" value={comment}
                onChange={(event) => setComment(event.target.value)} />
            </label>
            <label>
              报告模板
              <select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
                {templates.map((item) => (
                  <option key={item.template_key} value={item.template_key}>{item.display_name}</option>
                ))}
              </select>
            </label>
            <label className="task-file-option">
              <input type="checkbox" checked={rerunAnalysis}
                onChange={(event) => setRerunAnalysis(event.target.checked)} />
              重新运行相关分析（关闭时复用已完成分析与检索结果）
            </label>
            <div className="row-actions">
              <button type="button" disabled={Boolean(busy)} onClick={() =>
                run("feedback", () => createReportFeedback(workspaceId, taskId, {
                  report_id: selected.id,
                  feedback_type: feedbackType,
                  comment: comment || null,
                  issue_category: feedbackType,
                  correction: ["wrong_number", "wrong_citation"].includes(feedbackType)
                    ? { statement: comment || "用户标记了需要纠正的内容" }
                    : null,
                }))}>
                提交反馈
              </button>
              <button type="button" disabled={Boolean(busy)} onClick={() =>
                run("regenerate", () => regenerateReport(workspaceId, taskId, {
                  report_id: selected.id,
                  template_key: templateKey,
                  correction_note: comment || null,
                  rerun_analysis: rerunAnalysis,
                }))}>
                {busy === "regenerate" ? "处理中…" : "重新生成"}
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

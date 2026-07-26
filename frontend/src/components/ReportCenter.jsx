import { useEffect, useMemo, useState } from "react";
import { downloadResource } from "../api/client";
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
import { useFeedback } from "../context/FeedbackContext";
import { formatDate, sortReportVersions } from "../utils/ui";
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  FormField,
  Select,
  Skeleton,
  StatusBadge,
  Textarea,
} from "./common";
import SafeMarkdown, { extractMarkdownHeadings } from "./common/SafeMarkdown";

const FEEDBACK_TYPES = [
  ["like", "有帮助"],
  ["dislike", "没帮助"],
  ["wrong_number", "数字错误"],
  ["wrong_citation", "引用错误"],
  ["missing_content", "缺少内容"],
  ["other", "其他"],
];

const QUALITY_STATUS = {
  passed: ["质量检查通过", "success"],
  passed_with_warnings: ["通过，有警告", "warning"],
  retry_required: ["需要重试", "warning"],
  failed: ["质量检查失败", "danger"],
};

export default function ReportCenter({ workspaceId, taskId }) {
  const [reports, setReports] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [templateKey, setTemplateKey] = useState("comprehensive_analysis");
  const [feedbackType, setFeedbackType] = useState("");
  const [comment, setComment] = useState("");
  const [rerunAnalysis, setRerunAnalysis] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [assetOpen, setAssetOpen] = useState(null);
  const { confirm, toast } = useFeedback();
  const orderedReports = useMemo(() => sortReportVersions(reports), [reports]);
  const selected = useMemo(
    () => orderedReports.find((item) => item.id === selectedId) || orderedReports[0],
    [orderedReports, selectedId],
  );
  const headings = useMemo(
    () => extractMarkdownHeadings(selected?.markdown_content || "").filter((item) => item.level <= 3),
    [selected?.markdown_content],
  );

  async function load(preserveSelection = true) {
    if (!taskId) return;
    setIsLoading(true);
    try {
      const [versions, templateList] = await Promise.all([
        fetchReportVersions(workspaceId, taskId),
        fetchReportTemplates(),
      ]);
      setReports(versions);
      setTemplates(templateList);
      const current = versions.find((item) => item.is_current) || versions[0];
      setSelectedId((value) => preserveSelection && versions.some((item) => item.id === value)
        ? value : current?.id || null);
      setTemplateKey(current?.template_key || "comprehensive_analysis");
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    setSelectedId(null);
    setFeedbackType("");
    setComment("");
    load(false);
  }, [workspaceId, taskId]);

  async function run(name, action, successMessage) {
    setBusy(name);
    try {
      await action();
      await load();
      if (successMessage) toast(successMessage);
      setError("");
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
      await downloadResource(result.download_url, `${selected.title}.${format === "markdown" ? "md" : format}`);
    }, `${format.toUpperCase()} 导出已下载`);
  }

  async function handleDelete() {
    if (!selected) return;
    const accepted = await confirm({
      title: `删除报告 v${selected.version}？`,
      description: "当前版本或唯一可用版本不能删除。删除历史版本不会影响其他版本，资产会等待服务端清理策略处理。",
      confirmLabel: "删除历史版本",
    });
    if (accepted) {
      await run("delete", () => deleteReportVersion(workspaceId, taskId, selected.id), "历史报告版本已删除");
    }
  }

  async function handleFeedback() {
    if (!feedbackType || !selected) return;
    await run("feedback", () => createReportFeedback(workspaceId, taskId, {
      report_id: selected.id,
      feedback_type: feedbackType,
      comment: comment || null,
      issue_category: feedbackType,
      correction: ["wrong_number", "wrong_citation"].includes(feedbackType)
        ? { statement: comment || "用户标记了需要核对的内容" }
        : null,
    }), "反馈已提交");
    setFeedbackOpen(false);
  }

  async function handleRegenerate() {
    if (!selected) return;
    const accepted = await confirm({
      title: "生成新的报告版本？",
      description: rerunAnalysis
        ? "将重新执行受控分析链路，消耗任务、工具及可能的模型预算；原报告版本会保留。"
        : "将复用已完成的分析、引用与图表，消耗 1 次报告生成和相应导出配额；原报告版本会保留。",
      confirmLabel: "确认生成新版本",
      tone: "warning",
    });
    if (!accepted) return;
    await run("regenerate", () => regenerateReport(workspaceId, taskId, {
      report_id: selected.id,
      template_key: templateKey,
      correction_note: comment || null,
      rerun_analysis: rerunAnalysis,
    }), rerunAnalysis ? "分析重试请求已入队" : "新报告版本已生成");
    setFeedbackOpen(false);
  }

  if (!taskId) return null;
  if (isLoading) return <section className="panel"><Skeleton lines={7} /></section>;
  if (!reports.length) {
    return <EmptyState title="当前任务还没有报告" description="任务完成并生成初始报告后，可在这里阅读、导出、反馈和切换版本。" />;
  }

  return (
    <section className="report-center">
      <div className="section-heading">
        <div>
          <p className="eyebrow">任务 #{taskId} 的最终交付物</p>
          <h2>{selected?.title || "报告中心"}</h2>
          <p className="muted">v{selected?.version} · {formatDate(selected?.created_at)} · {selected?.template_key}</p>
        </div>
        <div className="row-actions">
          {["markdown", "docx", "pdf"].map((format) => (
            <Button type="button" variant={format === "pdf" ? "primary" : "secondary"} key={format}
              loading={busy === `export-${format}`} disabled={Boolean(busy)}
              onClick={() => handleExport(format)}>
              下载 {format.toUpperCase()}
            </Button>
          ))}
          <Button variant="secondary" onClick={() => setFeedbackOpen(true)}>反馈与重新生成</Button>
        </div>
      </div>
      {error && <Alert title="报告操作未完成" tone="danger">{error}</Alert>}
      <div className="report-layout">
        <aside className="report-sidebar" aria-label="报告目录与版本">
          <Card>
            <h3>报告版本</h3>
            <div className="report-version-list">
              {orderedReports.map((report) => (
                <button type="button" className={report.id === selected?.id ? "is-active" : ""}
                  key={report.id} onClick={() => setSelectedId(report.id)}>
                  <span>v{report.version} · {report.is_current ? "当前" : "历史"}</span>
                  <small>{formatDate(report.created_at)}</small>
                </button>
              ))}
            </div>
            {!selected?.is_current && (
              <div className="row-actions">
                <Button size="sm" onClick={() => run("current", () =>
                  setCurrentReportVersion(workspaceId, taskId, selected.id), "当前报告版本已切换")}>
                  设为当前
                </Button>
                <Button size="sm" variant="danger" onClick={handleDelete}>删除版本</Button>
              </div>
            )}
          </Card>
          <Card>
            <h3>章节目录</h3>
            <nav className="report-toc">
              {headings.map((heading) => <a key={heading.id} className={`level-${heading.level}`}
                href={`#${heading.id}`}>{heading.label}</a>)}
            </nav>
          </Card>
        </aside>
        <main className="report-document">
          <SafeMarkdown content={selected?.markdown_content} />
        </main>
        <aside className="report-aside" aria-label="质量、引用和资产">
          <Card>
            <h3>质量状态</h3>
            <StatusBadge status={selected?.quality_status || "passed_with_warnings"} dictionary={QUALITY_STATUS} />
            {selected?.warnings?.length > 0 ? (
              <ul>{selected.warnings.map((warning, index) => <li key={index}>
                {typeof warning === "string" ? warning : JSON.stringify(warning)}
              </li>)}</ul>
            ) : <p className="muted">没有记录警告。</p>}
            {selected?.quality_summary && (
              <details><summary>质量检查摘要</summary><pre>{JSON.stringify(selected.quality_summary, null, 2)}</pre></details>
            )}
          </Card>
          <Card>
            <h3>引用与资产</h3>
            <div className="asset-list">
              {selected?.assets.map((asset, index) => (
                <div key={asset.id} id={`citation-${index + 1}`}>
                  <Badge tone={asset.status === "ready" ? "success" : "warning"}>{asset.status}</Badge>
                  <strong>{asset.display_name}</strong>
                  <small>{asset.asset_type} · {asset.format}</small>
                  {asset.download_url && (
                    <Button size="sm" variant="ghost" onClick={() => {
                      if (asset.mime_type?.startsWith("image/")) setAssetOpen(asset);
                      else downloadResource(asset.download_url, asset.display_name).catch((requestError) =>
                        setError(requestError.message));
                    }}>{asset.mime_type?.startsWith("image/") ? "预览" : "下载"}</Button>
                  )}
                </div>
              ))}
              {!selected?.assets.length && <p className="muted">没有独立资产。</p>}
            </div>
          </Card>
        </aside>
      </div>
      <Dialog open={feedbackOpen} busy={Boolean(busy)} onClose={() => setFeedbackOpen(false)} title="反馈与重新生成"
        description="先选择问题类型，再补充简短说明。反馈不会修改 Prompt、工具或已有报告版本。"
        footer={(
          <>
            <Button variant="secondary" onClick={() => setFeedbackOpen(false)}>取消</Button>
            <Button variant="secondary" loading={busy === "feedback"} disabled={!feedbackType}
              onClick={handleFeedback}>只提交反馈</Button>
            <Button loading={busy === "regenerate"} disabled={!feedbackType}
              onClick={handleRegenerate}>提交并重新生成</Button>
          </>
        )}>
        <div className="report-feedback">
          <FormField label="问题类型" required>
            <Select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)}>
              <option value="">请选择</option>
              {FEEDBACK_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Select>
          </FormField>
          <FormField label="简短说明" hint={`${comment.length} / 2000`}>
            <Textarea rows="4" maxLength="2000" value={comment}
              onChange={(event) => setComment(event.target.value)} />
          </FormField>
          <FormField label="新版本模板">
            <Select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
              {templates.map((item) => <option key={item.template_key}
                value={item.template_key}>{item.display_name}</option>)}
            </Select>
          </FormField>
          <label className="ui-choice">
            <input type="checkbox" checked={rerunAnalysis}
              onChange={(event) => setRerunAnalysis(event.target.checked)} />
            <span><strong>重新运行相关分析</strong>
              <small>关闭时复用既有分析、检索、图表和引用；开启后会进入受控重试队列。</small></span>
          </label>
          <Alert title="版本与配额" tone="info">
            原报告版本会保留。复用分析主要消耗报告生成配额；重新分析还会消耗任务、工具及可能的模型预算。
          </Alert>
        </div>
      </Dialog>
      <Dialog open={Boolean(assetOpen)} onClose={() => setAssetOpen(null)}
        title={assetOpen?.display_name || "资产预览"} size="lg">
        {assetOpen && <figure className="asset-preview">
          <img src={reportDownloadUrl(assetOpen.download_url)} alt={`报告图表：${assetOpen.display_name}`} />
          <figcaption>{assetOpen.display_name}。图表中的具体数据请结合报告正文与引用核对。</figcaption>
        </figure>}
      </Dialog>
    </section>
  );
}

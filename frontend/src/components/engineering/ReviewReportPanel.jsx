import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  downloadReviewReportAsset,
  fetchReviewReports,
  generateReviewReport,
} from "../../api/engineeringReviews";
import { fetchPublicSite } from "../../api/site";
import {
  Alert,
  Button,
  Card,
  EmptyState,
  SectionHeader,
  Skeleton,
  StatusBadge,
} from "../common";
import {
  REPORT_STATUS,
  REPORT_WARNING_CODES,
  canGenerateReport,
  formatFileSize,
  getReportErrorSuggestion,
  getReportGenerationState,
  hasBothReportAssets,
  missingReportAssets,
  sortReviewReports,
} from "../../utils/engineeringReview";
import { formatDate } from "../../utils/ui";

const PRODUCT_BOUNDARY = (
  "当前工程审查规则包属于合成演示规则。"
  + "本报告仅用于辅助审查、风险提示和证据定位，"
  + "不构成自动合规判断或投标有效性认定，"
  + "最终由专业人员确认。"
);

function ReportWarningItem({ warning }) {
  const code = warning.code || "";
  const message = warning.message || "";
  const explanation = REPORT_WARNING_CODES[code] || null;
  const findingIds = warning.finding_ids || [];
  const evidenceIds = warning.evidence_ids || [];
  return (
    <li className="report-warning-item">
      <div><code>{code}</code></div>
      <p>{explanation ? `${explanation}。` : ""}{message}</p>
      {findingIds.length > 0 && (
        <p className="muted">关联 Finding ID：{findingIds.join("、")}</p>
      )}
      {evidenceIds.length > 0 && (
        <p className="muted">关联 Evidence ID：{evidenceIds.join("、")}</p>
      )}
    </li>
  );
}

function ReportVersionList({ reports, selectedReportId, onSelect }) {
  if (!reports.length) {
    return (
      <EmptyState
        title="当前 ReviewRun 尚未生成审查报告"
        description="完成审查后，可生成当前审查状态的不可变报告快照。"
      />
    );
  }
  const sorted = sortReviewReports(reports);
  return (
    <div className="report-version-list">
      <p className="muted" style={{ marginBottom: "var(--space-2)" }}>
        历史报告版本是不可变快照，不会随当前 Finding 状态自动变化。
      </p>
      <div className="file-table-wrap">
        <table className="file-table">
          <thead>
            <tr>
              <th>版本</th>
              <th>状态</th>
              <th>Warning</th>
              <th>Finding</th>
              <th>待复核</th>
              <th>生成时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((report) => {
              const isSelected = report.id === selectedReportId;
              return (
                <tr key={report.id} className={isSelected ? "is-selected" : ""}>
                  <td><strong>v{report.version}</strong></td>
                  <td><StatusBadge status={report.status} dictionary={REPORT_STATUS} /></td>
                  <td>{report.warning_count ?? 0}</td>
                  <td>{report.finding_count ?? 0}</td>
                  <td>{report.pending_review_count ?? 0}</td>
                  <td>{formatDate(report.created_at)}</td>
                  <td>
                    <Button
                      size="sm"
                      variant={isSelected ? "primary" : "ghost"}
                      aria-pressed={isSelected}
                      disabled={isSelected}
                      onClick={() => onSelect(report)}
                    >
                      {isSelected ? "当前" : "查看"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ReportDetail({ report }) {
  // 阶段 6D-2：AI 辅助生成固定提示（来自公开配置）
  const [aiNotice, setAiNotice] = useState("AI 辅助生成，须人工复核");
  useEffect(() => {
    let cancelled = false;
    fetchPublicSite()
      .then((data) => {
        if (!cancelled && data.ai_assisted_notice) setAiNotice(data.ai_assisted_notice);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const severityCounts = {
    high: report.high_count ?? 0,
    medium: report.medium_count ?? 0,
    low: report.low_count ?? 0,
  };
  const statusCounts = {
    pending_review: report.pending_review_count ?? 0,
    confirmed: report.confirmed_count ?? 0,
    rejected: report.rejected_count ?? 0,
    modified: report.modified_count ?? 0,
    resolved: report.resolved_count ?? 0,
  };

  return (
    <div className="engineering-stack">
      <Card>
        <h3>版本与可信信息</h3>
        <dl className="engineering-detail-list">
          <div><dt>报告版本</dt><dd><strong>v{report.version}</strong></dd></div>
          <div><dt>ReviewRun ID</dt><dd>#{report.review_run_id}</dd></div>
          <div>
            <dt>报告状态</dt>
            <dd>
              <StatusBadge status={report.status} dictionary={REPORT_STATUS} />
              {report.status === "ready" && <span className="muted"> — 质量门通过，无未决警告</span>}
            </dd>
          </div>
          <div><dt>生成时间</dt><dd>{formatDate(report.created_at)}</dd></div>
          <div><dt>生成器</dt><dd>{report.generator_name} / {report.generator_version}</dd></div>
          <div>
            <dt>审查状态哈希</dt>
            <dd>
              <code className="hash-full" title={report.review_state_hash}>
                {report.review_state_hash || "—"}
              </code>
            </dd>
          </div>
        </dl>
      </Card>

      <div className="overview-grid">
        <Card>
          <h3>风险统计</h3>
          <div className="metric-grid">
            <div><span>Finding</span><strong>{report.finding_count ?? 0}</strong></div>
            <div><span>高风险</span><strong className="tone-danger">{severityCounts.high}</strong></div>
            <div><span>中风险</span><strong className="tone-warning">{severityCounts.medium}</strong></div>
            <div><span>低风险</span><strong className="tone-info">{severityCounts.low}</strong></div>
          </div>
        </Card>
        <Card>
          <h3>复核统计</h3>
          <div className="status-count-list">
            <div><StatusBadge status="pending_review" dictionary={{ pending_review: ["待复核", "warning"] }} /><strong>{statusCounts.pending_review}</strong></div>
            <div><StatusBadge status="confirmed" dictionary={{ confirmed: ["已确认", "success"] }} /><strong>{statusCounts.confirmed}</strong></div>
            <div><StatusBadge status="rejected" dictionary={{ rejected: ["已驳回", "neutral"] }} /><strong>{statusCounts.rejected}</strong></div>
            <div><StatusBadge status="modified" dictionary={{ modified: ["已修改", "info"] }} /><strong>{statusCounts.modified}</strong></div>
            <div><StatusBadge status="resolved" dictionary={{ resolved: ["已解决", "success"] }} /><strong>{statusCounts.resolved}</strong></div>
          </div>
        </Card>
      </div>

      {report.quality_gate?.warnings?.length > 0 && (
        <Alert title="质量门 — 仍需人工复核" tone="warning">
          <ul className="report-warning-list">
            {report.quality_gate.warnings.map((warning, index) => (
              <ReportWarningItem key={warning.code || index} warning={warning} />
            ))}
          </ul>
        </Alert>
      )}
      {report.quality_gate && (!report.quality_gate.warnings || report.quality_gate.warnings.length === 0) && (
        <Alert title="质量门" tone="success">
          完整性质量门通过，当前无未决警告。
        </Alert>
      )}

      <Alert title="产品边界" tone="info">
        {PRODUCT_BOUNDARY}
      </Alert>

      <Alert title={aiNotice} tone="warning">
        本报告由系统在人工智能模型辅助下生成/规划，须人工复核后再行使用；
        报告不承诺结果完全准确，检索结果与候选证据仅作为线索，
        必须经具备相应权限的专业人员确认后方可采信。
        下载的 Markdown / PDF 文件均包含上述可见 AI 辅助生成声明（报告"报告声明"一节）。
      </Alert>
    </div>
  );
}

function ReportAssets({ workspaceId, runId, report }) {
  const [downloading, setDownloading] = useState({});
  const [dlErrors, setDlErrors] = useState({});

  const assets = report.assets || [];
  const missing = missingReportAssets(assets);

  const handleDownload = useCallback(async (asset) => {
    setDownloading((prev) => ({ ...prev, [asset.asset_type]: true }));
    setDlErrors((prev) => ({ ...prev, [asset.asset_type]: null }));
    try {
      await downloadReviewReportAsset(
        workspaceId, runId, report.id, asset.id, asset.file_name,
      );
    } catch (err) {
      setDlErrors((prev) => ({
        ...prev,
        [asset.asset_type]: {
          code: err.code || `HTTP_${err.status}`,
          message: err.message,
        },
      }));
    } finally {
      setDownloading((prev) => ({ ...prev, [asset.asset_type]: false }));
    }
  }, [workspaceId, runId, report.id]);

  const assetLabels = { markdown: "下载 Markdown", pdf: "下载 PDF" };
  const assetOrder = ["markdown", "pdf"];

  return (
    <Card>
      <h3>报告资产</h3>
      {!hasBothReportAssets(assets) && (
        <Alert title="资产完整性警告" tone="warning">
          报告缺少以下资产类型：{missing.join("、")}。这可能是生成过程中出现了异常。
        </Alert>
      )}
      {!assets.length && <EmptyState title="暂无报告资产" description="生成报告后会自动创建 Markdown 和 PDF 资产。" />}
      <div className="report-asset-grid">
        {assetOrder.map((type) => {
          const asset = assets.find((a) => a.asset_type === type);
          if (!asset) return null;
          const label = assetLabels[type] || `下载 ${type}`;
          const err = dlErrors[type];
          return (
            <div key={type} className="report-asset-card">
              <div className="report-asset-meta">
                <div><strong>{asset.file_name}</strong></div>
                <div className="muted">{asset.mime_type} · {formatFileSize(asset.size_bytes)}</div>
                <details>
                  <summary>SHA256</summary>
                  <code className="hash-full">{asset.content_hash || "—"}</code>
                </details>
                <div className="muted">创建于 {formatDate(asset.created_at)}</div>
              </div>
              {err && (
                <Alert title="下载失败" tone="danger">
                  <p><code>{err.code}</code>：{err.message}</p>
                </Alert>
              )}
              <Button
                variant="primary"
                loading={downloading[type]}
                disabled={Boolean(downloading[type])}
                onClick={() => handleDownload(asset)}
              >
                {label}
              </Button>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export default function ReviewReportPanel({
  workspaceId,
  basePath,
  runs,
  activeRun,
  onSelectRun,
}) {
  const [reports, setReports] = useState([]);
  const [selectedReport, setSelectedReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [feedback, setFeedback] = useState(null); // { tone, title, message }
  const [error, setError] = useState(null);

  const generationState = getReportGenerationState(activeRun);

  // 加载当前 Run 的报告列表
  async function loadReports(runId) {
    if (!runId) {
      setReports([]);
      setSelectedReport(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReviewReports(workspaceId, runId);
      setReports(data);
      if (data.length > 0) {
        const sorted = sortReviewReports(data);
        setSelectedReport(sorted[0]);
      } else {
        setSelectedReport(null);
      }
    } catch (err) {
      setError(err);
      setReports([]);
      setSelectedReport(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (activeRun) loadReports(activeRun.id);
    else { setReports([]); setSelectedReport(null); }
  }, [activeRun?.id, workspaceId]);

  // 生成报告
  async function handleGenerate() {
    if (!activeRun || !canGenerateReport(activeRun)) return;
    setGenerating(true);
    setFeedback(null);
    setError(null);
    try {
      const result = await generateReviewReport(workspaceId, activeRun.id);
      // 重新加载列表
      const data = await fetchReviewReports(workspaceId, activeRun.id);
      setReports(data);
      // 选中新返回的版本
      const found = data.find((r) => r.id === result.id);
      setSelectedReport(found || (data.length > 0 ? sortReviewReports(data)[0] : null));
      // 反馈
      if (result.reused) {
        setFeedback({
          tone: "info",
          title: "复用已有版本",
          message: `当前审查状态未变化，已复用报告 v${result.version}，未创建重复版本。`,
        });
      } else {
        setFeedback({
          tone: "success",
          title: "报告已生成",
          message: `已生成审查报告 v${result.version}，并固化当前审查状态。`,
        });
      }
    } catch (err) {
      const code = err.code || `HTTP_${err.status}`;
      const suggestion = getReportErrorSuggestion(code);
      setError({
        code,
        message: err.message,
        suggestion,
      });
    } finally {
      setGenerating(false);
    }
  }

  // 切换 Run
  function handleSelectRun(run) {
    setFeedback(null);
    setError(null);
    if (onSelectRun) onSelectRun(run);
  }

  return (
    <div className="engineering-stack">
      <SectionHeader
        title="审查报告"
        description="生成不可变审查报告快照，下载 Markdown 或 PDF。报告用于辅助审查，不构成自动合规判断。"
      />

      {/* Run 选择器 */}
      <Card>
        <h3>选择 ReviewRun</h3>
        {!runs.length && (
          <EmptyState
            title="尚无 ReviewRun"
            description="先完成材料上传和审查要求确认，再执行审查。"
            action={<Link to={`${basePath}/review`}>前往执行审查</Link>}
          />
        )}
        {runs.length > 0 && (
          <div className="file-table-wrap">
            <table className="file-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>状态</th>
                  <th>规则包版本</th>
                  <th>Brief 版本</th>
                  <th>Finding</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const isActive = activeRun && activeRun.id === run.id;
                  return (
                    <tr key={run.id} className={isActive ? "is-selected" : ""}>
                      <td><strong>#{run.id}</strong>{isActive && " (当前)"}</td>
                      <td><StatusBadge status={run.status} dictionary={{ completed: ["已完成", "success"], failed: ["失败", "danger"], draft: ["待开始", "neutral"], pending: ["待开始", "neutral"] }} /></td>
                      <td>{run.rule_pack_version || "—"}</td>
                      <td>v{run.review_brief_version ?? "—"}</td>
                      <td>{run.finding_count ?? 0}</td>
                      <td>{formatDate(run.created_at)}</td>
                      <td>
                        <Button
                          size="sm"
                          variant={isActive ? "primary" : "ghost"}
                          disabled={isActive}
                          onClick={() => handleSelectRun(run)}
                        >
                          {isActive ? "当前" : "选择"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* 错误 */}
      {error && (
        <Alert title={`生成失败 — ${error.code}`} tone="danger">
          <p>{error.message}</p>
          <p>{error.suggestion}</p>
        </Alert>
      )}

      {/* 前置条件检查 */}
      {!activeRun && (
        <EmptyState
          title="请先选择一个 ReviewRun"
          description="选择一个已完成审查的 Run，查看或生成其审查报告。"
          action={<Link to={`${basePath}/review`}>前往执行审查</Link>}
        />
      )}

      {activeRun && !generationState.canGenerate && (
        <Alert title="无法生成报告" tone="warning">
          {generationState.reason === "not_completed" && (
            <p>当前 ReviewRun #{activeRun.id} 尚未完成。请先执行审查，完成后再回来生成报告。<Link to={`${basePath}/review`}>前往执行审查</Link></p>
          )}
          {generationState.reason === "integrity_error" && (
            <p>当前 ReviewRun #{activeRun.id} 存在快照完整性错误，无法生成报告。建议创建新的 ReviewRun。</p>
          )}
        </Alert>
      )}

      {/* 反馈 */}
      {feedback && (
        <Alert title={feedback.title} tone={feedback.tone}>{feedback.message}</Alert>
      )}

      {/* 生成按钮 */}
      {activeRun && generationState.canGenerate && (
        <Card>
          <div className="engineering-section-heading">
            <div>
              <h3>当前 Run #{activeRun.id}</h3>
              <p className="muted">
                报告将固化当前 Finding、Evidence、规则快照、ReviewBrief 和人工复核状态。
                相同审查状态会复用已有版本；人工复核发生变化后会生成新版本。
              </p>
            </div>
            <Button onClick={handleGenerate} loading={generating} disabled={generating}>
              生成当前审查状态报告
            </Button>
          </div>
        </Card>
      )}

      {/* 报告加载中 */}
      {loading && <Skeleton lines={4} />}

      {/* 版本列表 */}
      {activeRun && !loading && (
        <>
          <Card>
            <h3>报告版本</h3>
            <ReportVersionList
              reports={reports}
              selectedReportId={selectedReport?.id}
              onSelect={setSelectedReport}
            />
          </Card>

          {/* 报告详情 */}
          {selectedReport && (
            <>
              <ReportDetail report={selectedReport} />
              <ReportAssets
                workspaceId={workspaceId}
                runId={activeRun.id}
                report={selectedReport}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}

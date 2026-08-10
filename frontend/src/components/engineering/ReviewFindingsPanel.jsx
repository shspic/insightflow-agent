import { useEffect, useMemo, useState } from "react";
import {
  createReviewFindingAction,
  fetchReviewEvidences,
  fetchReviewFindingActions,
  fetchReviewFindings,
} from "../../api/engineeringReviews";
import {
  Alert,
  Button,
  Card,
  Dialog,
  Drawer,
  EmptyState,
  FormField,
  Input,
  Select,
  Skeleton,
  StatusBadge,
  Textarea,
} from "../common";
import EvidenceDrawer from "./EvidenceDrawer";
import {
  FINDING_SEVERITY,
  FINDING_STATUS,
  filterReviewFindings,
  selectFindingEvidences,
} from "../../utils/engineeringReview";
import { formatDate } from "../../utils/ui";

const ACTION_LABELS = {
  confirm: "确认",
  reject: "驳回",
  modify: "修改",
  resolve: "解决",
};

function ActionDiff({ value, emptyLabel }) {
  if (!value) return <span className="muted">{emptyLabel}</span>;
  return (
    <dl className="action-diff">
      {Object.entries(value).map(([key, item]) => <div key={key}><dt>{key}</dt><dd>{String(item ?? "—")}</dd></div>)}
    </dl>
  );
}

export default function ReviewFindingsPanel({ workspaceId, run, files, onFindingsChanged }) {
  const [findings, setFindings] = useState([]);
  const [evidences, setEvidences] = useState([]);
  const [filters, setFilters] = useState({ severity: "all", status: "all", query: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [evidenceFinding, setEvidenceFinding] = useState(null);
  const [actionState, setActionState] = useState(null);
  const [reviewNote, setReviewNote] = useState("");
  const [modifiedConclusion, setModifiedConclusion] = useState("");
  const [modifiedSuggestion, setModifiedSuggestion] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [historyFinding, setHistoryFinding] = useState(null);
  const [actions, setActions] = useState([]);
  const [historyBusy, setHistoryBusy] = useState(false);

  async function loadData() {
    if (!run?.id) return;
    setLoading(true);
    setError("");
    try {
      const [findingData, evidenceData] = await Promise.all([
        fetchReviewFindings(workspaceId, run.id),
        fetchReviewEvidences(workspaceId, run.id),
      ]);
      setFindings(findingData);
      setEvidences(evidenceData);
      onFindingsChanged?.(findingData);
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [workspaceId, run?.id]);

  const visibleFindings = useMemo(() => filterReviewFindings(findings, filters), [findings, filters]);
  const selectedEvidence = selectFindingEvidences(evidenceFinding, evidences);

  function openAction(finding, actionType) {
    setActionState({ finding, actionType });
    setReviewNote("");
    setModifiedConclusion(finding.conclusion || "");
    setModifiedSuggestion(finding.suggestion || "");
    setActionError("");
  }

  async function submitAction() {
    const { finding, actionType } = actionState;
    setActionBusy(true);
    setActionError("");
    try {
      const payload = { action_type: actionType, review_note: reviewNote || null };
      if (actionType === "modify") {
        payload.modified_conclusion = modifiedConclusion;
        payload.modified_suggestion = modifiedSuggestion;
      }
      await createReviewFindingAction(workspaceId, finding.id, payload);
      await loadData();
      setActionState(null);
      setReviewNote("");
    } catch (requestError) {
      setActionError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setActionBusy(false);
    }
  }

  async function openHistory(finding) {
    setHistoryFinding(finding);
    setActions([]);
    setHistoryBusy(true);
    try {
      setActions(await fetchReviewFindingActions(workspaceId, finding.id));
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setHistoryBusy(false);
    }
  }

  if (!run) return <EmptyState title="请选择 ReviewRun" description="先在“执行审查”中选择已完成的 Run。" />;

  return (
    <div className="engineering-stack">
      <Alert title="辅助审查声明" tone="warning">
        本结果用于辅助审查、风险提示和证据定位，最终结论由专业人员确认。
      </Alert>
      <Card>
        <div className="engineering-section-heading">
          <div><h2>问题清单</h2><p className="muted">ReviewRun #{run.id} · 共 {findings.length} 条 Finding</p></div>
          <Button variant="secondary" onClick={loadData} loading={loading}>刷新</Button>
        </div>
        {error && <Alert title="问题数据加载失败" tone="danger">{error}</Alert>}
        <div className="filter-bar" role="search">
          <FormField label="风险等级"><Select value={filters.severity}
            onChange={(event) => setFilters((current) => ({ ...current, severity: event.target.value }))}>
            <option value="all">全部风险</option>
            {Object.entries(FINDING_SEVERITY).map(([value, meta]) => <option key={value} value={value}>{meta[0]}</option>)}
          </Select></FormField>
          <FormField label="复核状态"><Select value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}>
            <option value="all">全部状态</option>
            {Object.entries(FINDING_STATUS).map(([value, meta]) => <option key={value} value={value}>{meta[0]}</option>)}
          </Select></FormField>
          <FormField label="搜索问题"><Input type="search" placeholder="issue_code 或标题" value={filters.query}
            onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} /></FormField>
        </div>
      </Card>
      {loading && <Skeleton lines={6} />}
      {!loading && <div className="finding-list">
        {visibleFindings.map((finding) => (
          <Card key={finding.id} className="finding-card">
            <div className="engineering-section-heading">
              <div><p className="eyebrow">{finding.issue_code}</p><h3>{finding.title}</h3></div>
              <div className="row-actions">
                <StatusBadge status={finding.severity} dictionary={FINDING_SEVERITY} />
                <StatusBadge status={finding.status} dictionary={FINDING_STATUS} />
              </div>
            </div>
            <dl className="engineering-detail-list">
              <div><dt>rule_id</dt><dd>{finding.rule_id}</dd></div>
              <div><dt>rule_version</dt><dd>{finding.rule_version}</dd></div>
              <div><dt>Evidence</dt><dd>{finding.evidence_ids?.length || 0} 条</dd></div>
              <div><dt>复核时间</dt><dd>{formatDate(finding.reviewed_at)}</dd></div>
            </dl>
            <div className="finding-copy"><div><strong>结论</strong><p>{finding.conclusion}</p></div>
              <div><strong>建议</strong><p>{finding.suggestion}</p></div></div>
            {finding.review_note && <p><strong>复核备注：</strong>{finding.review_note}</p>}
            <div className="row-actions finding-actions">
              <Button variant="secondary" onClick={() => setEvidenceFinding(finding)}>查看证据</Button>
              <Button variant="ghost" onClick={() => openHistory(finding)}>Action 历史</Button>
              <Button size="sm" onClick={() => openAction(finding, "confirm")}>确认</Button>
              <Button size="sm" variant="secondary" onClick={() => openAction(finding, "reject")}>驳回</Button>
              <Button size="sm" variant="secondary" onClick={() => openAction(finding, "modify")}>修改</Button>
              <Button size="sm" variant="secondary" onClick={() => openAction(finding, "resolve")}>解决</Button>
            </div>
          </Card>
        ))}
        {visibleFindings.length === 0 && <EmptyState title="没有匹配问题" description={findings.length ? "调整筛选条件。" : "该 Run 暂无 Finding。"} />}
      </div>}

      <EvidenceDrawer open={Boolean(evidenceFinding)} onClose={() => setEvidenceFinding(null)}
        finding={evidenceFinding} evidences={selectedEvidence.evidences} missingIds={selectedEvidence.missingIds} files={files} />

      <Dialog open={Boolean(actionState)} onClose={() => setActionState(null)} busy={actionBusy}
        title={actionState ? `${ACTION_LABELS[actionState.actionType]} Finding` : "人工复核"}
        description={actionState ? `${actionState.finding.issue_code} · ${actionState.finding.title}` : ""}
        footer={<><Button variant="secondary" disabled={actionBusy} onClick={() => setActionState(null)}>取消</Button>
          <Button loading={actionBusy} onClick={submitAction}>确认{actionState ? ACTION_LABELS[actionState.actionType] : "操作"}</Button></>}>
        {actionError && <Alert title="复核操作失败" tone="danger">{actionError}。输入内容已保留，可修正后重试。</Alert>}
        {actionState?.actionType === "modify" && <>
          <FormField label="修改后的结论" required><Textarea rows="5" value={modifiedConclusion}
            onChange={(event) => setModifiedConclusion(event.target.value)} /></FormField>
          <FormField label="修改后的建议" required><Textarea rows="5" value={modifiedSuggestion}
            onChange={(event) => setModifiedSuggestion(event.target.value)} /></FormField>
        </>}
        {actionState?.actionType !== "modify" && <p>该操作会把 Finding 状态更新为“{ACTION_LABELS[actionState?.actionType]}”。请确认已完成专业判断。</p>}
        <FormField label="复核备注" hint="可选；用于记录本次人工判断依据。"><Textarea rows="3" value={reviewNote}
          onChange={(event) => setReviewNote(event.target.value)} /></FormField>
      </Dialog>

      <Drawer open={Boolean(historyFinding)} onClose={() => setHistoryFinding(null)}
        title={historyFinding ? `${historyFinding.issue_code} · Action 历史` : "Action 历史"}>
        {historyBusy && <Skeleton lines={4} />}
        {!historyBusy && actions.length === 0 && <EmptyState title="暂无 Action" description="人工复核后会记录操作历史。" />}
        <div className="action-history">
          {actions.map((action) => <article key={action.id} className="action-history-item">
            <div className="engineering-section-heading"><strong>{ACTION_LABELS[action.action_type] || action.action_type}</strong>
              <span className="muted">{formatDate(action.created_at)}</span></div>
            {action.review_note && <p><strong>备注：</strong>{action.review_note}</p>}
            {action.action_type === "modify" && <div className="action-compare">
              <div><h4>Before</h4><ActionDiff value={action.before_json} emptyLabel="无修改前快照" /></div>
              <div><h4>After</h4><ActionDiff value={action.after_json} emptyLabel="无修改后快照" /></div>
            </div>}
          </article>)}
        </div>
      </Drawer>
    </div>
  );
}

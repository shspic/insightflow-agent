import { useState } from "react";
import { Link } from "react-router-dom";
import {
  createReviewRun,
  executeReviewRun,
  fetchReviewRun,
} from "../../api/engineeringReviews";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  SectionHeader,
  StatusBadge,
} from "../common";
import { REVIEW_RUN_STATUS } from "../../utils/engineeringReview";
import { formatDate } from "../../utils/ui";

const ERROR_ACTIONS = {
  REVIEW_MATERIAL_MISSING: "返回“材料与角色”，补齐并确认缺少的必需角色。",
  REVIEW_ROLE_DUPLICATED: "返回“材料与角色”，把重复角色调整为唯一文件。",
  REVIEW_SNAPSHOT_INTEGRITY_ERROR: "停止使用该 Run，并联系管理员核查规则快照完整性。",
  REVIEW_ENGINE_ERROR: "停止使用该 Run，并联系管理员核查规则快照或规则引擎。",
};

export default function ReviewRunPanel({
  workspaceId,
  basePath,
  materialState,
  brief,
  runs,
  activeRun,
  onRunChanged,
  onSelectRun,
  onOpenFindings,
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const prerequisitesReady = materialState.complete && brief?.status === "confirmed";

  async function createRun() {
    setBusy("create");
    setError(null);
    try {
      const run = await createReviewRun(workspaceId, {
        review_brief_id: brief.id,
        review_template_key: "engineering_bid_review_v1",
      });
      await onRunChanged(run);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy("");
    }
  }

  async function executeRun() {
    if (!activeRun) return;
    setBusy("execute");
    setError(null);
    try {
      await executeReviewRun(workspaceId, activeRun.id);
      const detail = await fetchReviewRun(workspaceId, activeRun.id);
      await onRunChanged(detail);
    } catch (requestError) {
      setError(requestError);
      try {
        const failedRun = await fetchReviewRun(workspaceId, activeRun.id);
        await onRunChanged(failedRun);
      } catch {
        // 保留原始执行错误，不能用二次读取错误覆盖。
      }
    } finally {
      setBusy("");
    }
  }

  const runError = activeRun?.integrity_error || (activeRun?.error_code ? {
    error_code: activeRun.error_code,
    message: activeRun.error_message,
  } : null) || (error ? { error_code: error.code, message: error.message } : null);

  return (
    <div className="engineering-stack">
      <SectionHeader title="执行审查" description="创建任务与开始审查分为两步；执行采用同步确定性 API，不展示虚构的 Agent 轨迹。" />
      {!prerequisitesReady && (
        <Alert title="执行前置条件未满足" tone="warning">
          <ul>
            {!materialState.complete && <li>五种必需材料角色尚未全部唯一确认。<Link to={`${basePath}/materials`}>前往材料与角色</Link></li>}
            {brief?.status !== "confirmed" && <li>当前没有已确认 ReviewBrief。<Link to={`${basePath}/requirements`}>前往审查要求</Link></li>}
          </ul>
        </Alert>
      )}
      {runError && (
        <Alert title="审查执行失败" tone="danger">
          <p><code>{runError.error_code || "REVIEW_EXECUTION_FAILED"}</code>：{runError.message || "服务端未返回错误说明"}</p>
          <p>{ERROR_ACTIONS[runError.error_code] || "请按错误信息修正后重新创建 ReviewRun；不要把失败 Run 当作完成结果。"}</p>
        </Alert>
      )}
      <Card>
        <div className="engineering-section-heading">
          <div><h3>当前 ReviewRun</h3><p className="muted">先创建快照，再由用户明确开始审查。</p></div>
          <Button onClick={createRun} loading={busy === "create"} disabled={!prerequisitesReady || Boolean(busy)}>
            创建审查任务
          </Button>
        </div>
        {!activeRun && <EmptyState title="尚未创建 ReviewRun" description="满足材料与 Brief 条件后创建审查任务。" />}
        {activeRun && (
          <div className="run-detail">
            <dl className="engineering-detail-list">
              <div><dt>Run ID</dt><dd>#{activeRun.id}</dd></div>
              <div><dt>状态</dt><dd><StatusBadge status={activeRun.status} dictionary={REVIEW_RUN_STATUS} /></dd></div>
              <div><dt>规则包</dt><dd>{activeRun.rule_pack_id} / {activeRun.rule_pack_version}</dd></div>
              <div><dt>Brief 版本</dt><dd>v{activeRun.review_brief_version ?? "—"}</dd></div>
              <div><dt>Finding</dt><dd>{activeRun.finding_count ?? 0}</dd></div>
              <div><dt>Evidence</dt><dd>{activeRun.evidence_count ?? 0}</dd></div>
            </dl>
            {busy === "execute" && <Alert title="审查执行中" tone="info">正在执行确定性抽取、规则校验和证据绑定。</Alert>}
            {["draft", "pending"].includes(activeRun.status) && (
              <Button onClick={executeRun} loading={busy === "execute"} disabled={Boolean(busy)}>开始审查</Button>
            )}
            {activeRun.status === "completed" && !activeRun.integrity_error && (
              <>
                <div className="metric-grid">
                  {Object.entries(activeRun.severity_counts || {}).map(([severity, count]) => (
                    <div key={severity}><span>{severity} 风险</span><strong>{count}</strong></div>
                  ))}
                </div>
                <div className="run-rule-results">
                  <div><strong>通过规则</strong><p>{(activeRun.passed_rule_ids || []).join("、") || "无"}</p></div>
                  <div><strong>触发风险规则</strong><p>{(activeRun.failed_rule_ids || []).join("、") || "无"}</p></div>
                </div>
                <Button onClick={() => onOpenFindings(activeRun)}>查看问题清单</Button>
                <Link to={`${basePath}/reports`} className="ui-button ui-button--secondary">查看/生成报告</Link>
              </>
            )}
          </div>
        )}
      </Card>
      <Card>
        <h3>历史 ReviewRun</h3>
        {!runs.length && <EmptyState title="暂无历史 Run" description="创建后会在这里保留规则与 Brief 快照信息。" />}
        {runs.length > 0 && <div className="file-table-wrap"><table className="file-table">
          <thead><tr><th>Run</th><th>状态</th><th>规则包版本</th><th>Finding</th><th>创建时间</th><th>操作</th></tr></thead>
          <tbody>{runs.map((run) => <tr key={run.id}>
            <td>#{run.id}</td><td><StatusBadge status={run.status} dictionary={REVIEW_RUN_STATUS} /></td>
            <td>{run.rule_pack_version}</td><td>{run.finding_count ?? 0}</td><td>{formatDate(run.created_at)}</td>
            <td><div className="row-actions"><Button size="sm" variant="secondary" onClick={() => onSelectRun(run)}>查看详情</Button>
              <Button size="sm" variant="ghost" disabled={run.status !== "completed"} onClick={() => onOpenFindings(run)}>查看问题</Button></div></td>
          </tr>)}</tbody>
        </table></div>}
      </Card>
    </div>
  );
}

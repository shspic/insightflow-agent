import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  createSupervisorRun,
  createVerificationCandidateDecision,
  createVerificationRun,
  fetchSupervisorRun,
  fetchSupervisorRuns,
  fetchSupervisorSteps,
  fetchVerificationCandidateDecisions,
  fetchVerificationCandidates,
  fetchVerificationRun,
  fetchVerificationRuns,
  fetchVerificationToolCalls,
} from "../../api/engineeringReviews";
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  SectionHeader,
  Skeleton,
  StatusBadge,
} from "../common";
import {
  CANDIDATE_DECISION_LABELS,
  GATE_CHECK_CODE_LABELS,
  SUPERVISOR_BOUNDARY_TEXT,
  SUPERVISOR_STATUS,
  VERIFICATION_RUN_STATUS,
  describePlanner,
  formatCandidateLocator,
  getCandidateErrorSuggestion,
  getSupervisorErrorSuggestion,
  groupCandidatesByFinding,
  normalizePlanDecisions,
  normalizeSupervisorTimeline,
  shortHash,
  sortSupervisorSteps,
  sortToolCallsByTime,
} from "../../utils/engineeringReview";
import { formatDate } from "../../utils/ui";

const STEP_STATUS = {
  running: ["执行中", "info"],
  success: ["成功", "success"],
  failed: ["失败", "danger"],
  skipped: ["跳过", "neutral"],
  needs_human: ["需人工介入", "danger"],
};

const TOOL_NAME_LABELS = {
  engineering_hybrid_retrieval: "混合检索",
  engineering_retrieval_index_prepare: "索引准备",
  search_review_rules: "MCP 规则检索",
  run_bid_consistency_checks: "MCP 一致性检查",
};

export default function VerificationPanel({ workspaceId, runs, activeRun, onSelectRun }) {
  const completedRuns = useMemo(
    () => runs.filter((run) => run.status === "completed"),
    [runs],
  );
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [planner, setPlanner] = useState("deterministic");
  const [maxToolCalls, setMaxToolCalls] = useState(5);
  const [verificationRuns, setVerificationRuns] = useState([]);
  const [selectedVerificationId, setSelectedVerificationId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [toolCalls, setToolCalls] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [candidateWarnings, setCandidateWarnings] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [launchResult, setLaunchResult] = useState(null);
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // ── Supervisor（阶段 5B）──
  const [supervisorRuns, setSupervisorRuns] = useState([]);
  const [selectedSupervisorId, setSelectedSupervisorId] = useState(null);
  const [supervisorDetail, setSupervisorDetail] = useState(null);
  const [supervisorSteps, setSupervisorSteps] = useState([]);
  const [useDeepseek, setUseDeepseek] = useState(false);
  const [maxVerificationToolCalls, setMaxVerificationToolCalls] = useState(5);
  const [maxStepRetries, setMaxStepRetries] = useState(1);
  const [generateReport, setGenerateReport] = useState(false);
  const [supervisorBusy, setSupervisorBusy] = useState("");
  const [supervisorError, setSupervisorError] = useState(null);
  const [launchSupervisorResult, setLaunchSupervisorResult] = useState(null);
  const [loadingSupervisorDetail, setLoadingSupervisorDetail] = useState(false);

  // 默认选择当前 active Run；仅完成态 Run 可以启动核验
  const effectiveRunId = selectedRunId ?? (
    activeRun?.status === "completed" ? activeRun.id : completedRuns[0]?.id ?? null
  );

  async function loadVerificationRuns(runId) {
    if (!runId) {
      setVerificationRuns([]);
      return;
    }
    const list = await fetchVerificationRuns(workspaceId, runId);
    setVerificationRuns(list);
    if (list.length > 0) {
      setSelectedVerificationId((current) => (
        current && list.some((item) => item.verification_run_id === current)
          ? current
          : list[0].verification_run_id
      ));
    } else {
      setSelectedVerificationId(null);
    }
  }

  async function loadVerificationDetail(verificationRunId) {
    if (!effectiveRunId || !verificationRunId) {
      setDetail(null);
      setToolCalls([]);
      setCandidates([]);
      setDecisions([]);
      return;
    }
    setLoadingDetail(true);
    setError(null);
    try {
      const [detailData, toolCallData, candidateData, decisionData] = await Promise.all([
        fetchVerificationRun(workspaceId, effectiveRunId, verificationRunId),
        fetchVerificationToolCalls(workspaceId, effectiveRunId, verificationRunId),
        fetchVerificationCandidates(workspaceId, effectiveRunId, verificationRunId),
        fetchVerificationCandidateDecisions(workspaceId, effectiveRunId, verificationRunId),
      ]);
      setDetail(detailData);
      setToolCalls(sortToolCallsByTime(toolCallData));
      setCandidates(candidateData.candidates || []);
      setCandidateWarnings(candidateData.warnings || []);
      setDecisions(decisionData);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setLoadingDetail(false);
    }
  }

  // ── Supervisor 只读取历史记录；启动必须由用户点击触发 ──
  async function loadSupervisorRuns(runId) {
    if (!runId) {
      setSupervisorRuns([]);
      setSelectedSupervisorId(null);
      return;
    }
    const list = await fetchSupervisorRuns(workspaceId, runId);
    setSupervisorRuns(list);
    if (list.length > 0) {
      setSelectedSupervisorId((current) => (
        current && list.some((item) => item.supervisor_run_id === current)
          ? current
          : list[0].supervisor_run_id
      ));
    } else {
      setSelectedSupervisorId(null);
      setSupervisorDetail(null);
      setSupervisorSteps([]);
    }
  }

  async function loadSupervisorDetail(supervisorRunId) {
    if (!effectiveRunId || !supervisorRunId) {
      setSupervisorDetail(null);
      setSupervisorSteps([]);
      return;
    }
    setLoadingSupervisorDetail(true);
    setSupervisorError(null);
    try {
      const [detailData, stepsData] = await Promise.all([
        fetchSupervisorRun(workspaceId, effectiveRunId, supervisorRunId),
        fetchSupervisorSteps(workspaceId, effectiveRunId, supervisorRunId),
      ]);
      setSupervisorDetail(detailData);
      setSupervisorSteps(sortSupervisorSteps(stepsData));
    } catch (requestError) {
      setSupervisorError(requestError);
    } finally {
      setLoadingSupervisorDetail(false);
    }
  }

  useEffect(() => {
    if (!effectiveRunId) return;
    loadSupervisorRuns(effectiveRunId).catch((requestError) => setSupervisorError(requestError));
  }, [workspaceId, effectiveRunId]);

  useEffect(() => {
    loadSupervisorDetail(selectedSupervisorId);
  }, [selectedSupervisorId, effectiveRunId]);

  // 只读取历史记录；启动核验必须由用户点击触发
  useEffect(() => {
    if (!effectiveRunId) return;
    loadVerificationRuns(effectiveRunId).catch((requestError) => setError(requestError));
  }, [workspaceId, effectiveRunId]);

  useEffect(() => {
    loadVerificationDetail(selectedVerificationId);
  }, [selectedVerificationId, effectiveRunId]);

  function switchRun(runId) {
    // 切换 Run 后不混合 VerificationRun / SupervisorRun
    setSelectedRunId(runId);
    setSelectedVerificationId(null);
    setDetail(null);
    setToolCalls([]);
    setCandidates([]);
    setDecisions([]);
    setLaunchResult(null);
    setError(null);
    setSelectedSupervisorId(null);
    setSupervisorDetail(null);
    setSupervisorSteps([]);
    setLaunchSupervisorResult(null);
    setSupervisorError(null);
  }

  async function launchSupervisor() {
    if (!effectiveRunId || busy || supervisorBusy) return;
    setSupervisorBusy("launch");
    setSupervisorError(null);
    setLaunchSupervisorResult(null);
    try {
      const result = await createSupervisorRun(workspaceId, effectiveRunId, {
        use_deepseek: useDeepseek,
        max_verification_tool_calls: maxVerificationToolCalls,
        max_step_retries: maxStepRetries,
        generate_report: generateReport,
      });
      setLaunchSupervisorResult(result);
      await loadSupervisorRuns(effectiveRunId);
      setSelectedSupervisorId(result.supervisor_run_id);
    } catch (requestError) {
      setSupervisorError(requestError);
    } finally {
      setSupervisorBusy("");
    }
  }

  async function launchVerification() {
    if (!effectiveRunId || busy) return;
    setBusy("launch");
    setError(null);
    setLaunchResult(null);
    try {
      const result = await createVerificationRun(workspaceId, effectiveRunId, {
        use_deepseek: planner === "deepseek",
        max_tool_calls: maxToolCalls,
      });
      setLaunchResult(result);
      await loadVerificationRuns(effectiveRunId);
      setSelectedVerificationId(result.verification_run_id);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setBusy("");
    }
  }

  async function submitDecision() {
    if (!confirmTarget || busy) return;
    const { candidate, decision } = confirmTarget;
    setBusy("decision");
    setError(null);
    try {
      await createVerificationCandidateDecision(
        workspaceId, effectiveRunId, selectedVerificationId, {
          tool_call_id: candidate.tool_call_id,
          candidate_rank: candidate.candidate_rank,
          decision,
          review_note: confirmTarget.note || undefined,
        },
      );
      setConfirmTarget(null);
      // 接受/拒绝成功后刷新候选与决策；不自动修改 Finding 状态、不自动生成报告
      await loadVerificationDetail(selectedVerificationId);
      if (onSelectRun && effectiveRunId) {
        const run = runs.find((item) => item.id === effectiveRunId);
        if (run) await onSelectRun(run);
      }
    } catch (requestError) {
      setError(requestError);
      setConfirmTarget(null);
    } finally {
      setBusy("");
    }
  }

  const planDecisions = useMemo(() => normalizePlanDecisions(detail?.plan), [detail]);
  const candidateGroups = useMemo(() => groupCandidatesByFinding(candidates), [candidates]);
  const plannerMeta = describePlanner(detail);
  const supervisorTimeline = useMemo(() => normalizeSupervisorTimeline(supervisorSteps), [supervisorSteps]);
  const qualityGate = supervisorDetail?.quality_gate || {};
  const clarification = supervisorDetail?.clarification || {};
  const reportableIds = qualityGate.reportable_finding_ids || [];
  const needMoreIds = qualityGate.need_more_information_finding_ids || [];
  const relatedFileIds = qualityGate.related_file_ids || [];
  const gateChecks = qualityGate.checks || [];

  return (
    <div className="engineering-stack">
      <SectionHeader
        title="智能核验"
        description="Verification Agent 对已完成审查的问题补充检索候选证据；是否采纳完全由人工决定。"
      />
      <Alert title="候选证据边界" tone="info">
        检索结果只是候选证据。只有人工接受后才会成为正式 Evidence；
        接受候选不会自动确认问题、降低风险或修改结论。
      </Alert>

      <Card>
        <div className="engineering-section-heading">
          <div><h3>启动核验</h3><p className="muted">只有已完成的 ReviewRun 可以启动；页面不会自动调用。</p></div>
        </div>
        {completedRuns.length === 0 && (
          <EmptyState
            title="暂无已完成的 ReviewRun"
            description="请先在“执行审查”中创建并完成一次审查，再回来启动智能核验。"
          />
        )}
        {completedRuns.length > 0 && (
          <div className="verification-launch">
            <label>
              ReviewRun
              <select
                value={effectiveRunId ?? ""}
                onChange={(event) => switchRun(Number(event.target.value))}
              >
                {completedRuns.map((run) => (
                  <option key={run.id} value={run.id}>#{run.id}（{run.finding_count ?? 0} 个问题）</option>
                ))}
              </select>
            </label>
            <fieldset className="verification-planner-choice">
              <legend>规划方式</legend>
              <label>
                <input
                  type="radio"
                  name="planner"
                  value="deterministic"
                  checked={planner === "deterministic"}
                  onChange={() => setPlanner("deterministic")}
                />
                确定性规划
              </label>
              <label>
                <input
                  type="radio"
                  name="planner"
                  value="deepseek"
                  checked={planner === "deepseek"}
                  onChange={() => setPlanner("deepseek")}
                />
                DeepSeek 规划
              </label>
            </fieldset>
            <label>
              工具预算（1～5）
              <input
                type="number"
                min="1"
                max="5"
                value={maxToolCalls}
                onChange={(event) => {
                  const value = Math.max(1, Math.min(5, Number(event.target.value) || 1));
                  setMaxToolCalls(value);
                }}
              />
            </label>
            <Button onClick={launchVerification} loading={busy === "launch"} disabled={Boolean(busy) || !effectiveRunId}>
              启动智能核验
            </Button>
          </div>
        )}
        {planner === "deepseek" && (
          <Alert title="将产生模型调用" tone="warning">
            DeepSeek 规划会对当前 ReviewRun 发起一次真实模型调用；输出未通过校验时会自动改用确定性计划并如实标注。
          </Alert>
        )}
        {launchResult && (
          <Alert
            title={launchResult.reused ? "复用已有核验结果" : "已创建新的核验运行"}
            tone={launchResult.reused ? "info" : "success"}
          >
            {launchResult.reused
              ? `输入状态未变化，返回已有 VerificationRun #${launchResult.verification_run_id}（HTTP 200，reused=true）。`
              : `VerificationRun #${launchResult.verification_run_id} 已创建（HTTP 201，reused=false），候选 ${launchResult.candidate_count} 条。`}
          </Alert>
        )}
      </Card>

      {error && (
        <Alert title="智能核验操作未完成" tone="danger">
          <p><code>{error.code || "REQUEST_FAILED"}</code>：{error.message}</p>
          <p>{getCandidateErrorSuggestion(error.code)}</p>
        </Alert>
      )}

      <Card>
        <h3>核验历史</h3>
        {verificationRuns.length === 0 && (
          <EmptyState title="暂无核验记录" description="启动一次智能核验后，这里会保留规划、工具调用和候选证据。" />
        )}
        {verificationRuns.length > 0 && (
          <div className="file-table-wrap"><table className="file-table">
            <thead><tr><th>ID</th><th>状态</th><th>规划</th><th>工具调用</th><th>候选</th><th>警告</th><th>创建时间</th><th>操作</th></tr></thead>
            <tbody>{verificationRuns.map((run) => {
              const meta = describePlanner(run);
              return (
                <tr key={run.verification_run_id}>
                  <td>#{run.verification_run_id}</td>
                  <td><StatusBadge status={run.status} dictionary={VERIFICATION_RUN_STATUS} /></td>
                  <td><Badge tone={meta.tone}>{meta.label}</Badge></td>
                  <td>{run.tool_calls_used} / {run.tool_budget}</td>
                  <td>{run.candidate_count}</td>
                  <td>{run.warning_count}</td>
                  <td>{formatDate(run.created_at)}</td>
                  <td>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setSelectedVerificationId(run.verification_run_id)}
                    >
                      查看详情
                    </Button>
                  </td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </Card>

      {loadingDetail && <Skeleton lines={5} />}
      {!loadingDetail && detail && (
        <>
          <Card>
            <h3>核验详情 #{detail.verification_run_id}</h3>
            <dl className="engineering-detail-list">
              <div><dt>状态</dt><dd><StatusBadge status={detail.status} dictionary={VERIFICATION_RUN_STATUS} /></dd></div>
              <div><dt>规划方式</dt><dd><Badge tone={plannerMeta.tone}>{plannerMeta.label}</Badge></dd></div>
              <div><dt>fallback</dt><dd>{detail.fallback_used ? `是（${detail.fallback_reason || "未记录原因"}）` : "否"}</dd></div>
              <div><dt>模型</dt><dd>{detail.model_provider || "—"} / {detail.model_name || "—"}</dd></div>
              <div><dt>Prompt 版本</dt><dd>{detail.prompt_version || "—"}</dd></div>
              <div><dt>Token 用量</dt><dd>{detail.token_usage ? JSON.stringify(detail.token_usage) : "—"}</dd></div>
              <div><dt>input_state_hash</dt><dd><code className="hash-text">{shortHash(detail.input_state_hash)}</code></dd></div>
              {detail.warnings && detail.warnings.length > 0 && (
                <Alert title="核验警告" tone="warning">
                  <ul>
                    {detail.warnings.map((w, i) => (
                      <li key={`warn-${i}`}>{w}</li>
                    ))}
                  </ul>
                </Alert>
              )}
              <div><dt>检索预算</dt><dd>{detail.retrieval_tool_call_count ?? detail.tool_calls_used} / {detail.retrieval_budget ?? detail.tool_budget}</dd></div>
              <div><dt>MCP 调用</dt><dd>{detail.mcp_tool_call_count ?? 0}（重试 {detail.mcp_retry_count ?? 0}）</dd></div>
              <div><dt>总调用</dt><dd>{detail.total_tool_call_count ?? detail.tool_calls_used}</dd></div>
              {detail.mcp_enabled === false && <div className="muted">MCP 未启用：未执行 MCP 核验</div>}
              <div><dt>成功 / 失败 / 重试</dt><dd>{detail.success_count} / {detail.failed_count} / {detail.retry_count}</dd></div>
              <div><dt>候选数</dt><dd>{detail.candidate_count}</dd></div>
              <div><dt>警告数</dt><dd>{detail.warning_count}</dd></div>
              <div><dt>index_sha256</dt><dd><code className="hash-text">{shortHash(detail.index_sha256)}</code></dd></div>
              <div><dt>corpus_sha256</dt><dd><code className="hash-text">{shortHash(detail.corpus_sha256)}</code></dd></div>
              <div><dt>创建时间</dt><dd>{formatDate(detail.created_at)}</dd></div>
              <div><dt>完成时间</dt><dd>{detail.completed_at ? formatDate(detail.completed_at) : "—"}</dd></div>
            </dl>
          </Card>

          <Card>
            <h3>检索计划</h3>
            {planDecisions.length === 0 && <EmptyState title="无计划数据" description="该核验未产生计划快照。" />}
            {planDecisions.length > 0 && (
              <div className="file-table-wrap"><table className="file-table">
                <thead><tr><th>Finding</th><th>决策</th><th>原因</th><th>query</th><th>模式</th><th>top_k</th></tr></thead>
                <tbody>{planDecisions.map((item) => (
                  <tr key={`${item.findingId}-${item.issueCode}`}>
                    <td><code>{item.issueCode}</code></td>
                    <td><Badge tone={item.decision === "retrieve" ? "info" : "neutral"}>{item.decision === "retrieve" ? "补充检索" : "跳过"}</Badge></td>
                    <td className="wrap-cell">{item.reason}</td>
                    <td className="wrap-cell">{item.query || "—"}</td>
                    <td>{item.retrievalMode || "—"}</td>
                    <td>{item.topK ?? "—"}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>

          <Card>
            <h3>工具调用轨迹</h3>
            {toolCalls.length === 0 && <EmptyState title="无工具调用" description="该核验没有产生工具调用记录。" />}
            {toolCalls.length > 0 && (
              <div className="file-table-wrap"><table className="file-table">
                <thead><tr><th>工具</th><th>Finding</th><th>attempt</th><th>retry_of</th><th>状态</th><th>错误码</th><th>耗时</th><th>index</th><th>corpus</th><th>时间</th></tr></thead>
                <tbody>{toolCalls.map((call) => (
                  <tr key={call.id}>
                    <td>{TOOL_NAME_LABELS[call.tool_name] || call.tool_name}</td>
                    <td>{call.review_finding_id ?? "—"}</td>
                    <td>{call.attempt_number}</td>
                    <td>{call.retry_of_id ? `#${call.retry_of_id}` : "—"}</td>
                    <td><Badge tone={call.status === "success" ? "success" : call.status === "failed" ? "danger" : "info"}>{call.status}</Badge></td>
                    <td className="wrap-cell">{call.error_code ? (<><code>{call.error_code}</code><span className="muted">（{toolErrorHint(call.error_code)}）</span></>) : "—"}</td>
                    <td>{call.latency_ms != null ? `${call.latency_ms} ms` : "—"}</td>
                    <td><code className="hash-text">{shortHash(call.index_sha256)}</code></td>
                    <td><code className="hash-text">{shortHash(call.corpus_sha256)}</code></td>
                    <td>{formatDate(call.created_at)}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>

          <Card>
            <h3>候选证据</h3>
            {candidateWarnings.length > 0 && (
              <Alert title="部分候选来源数据异常" tone="warning">
                <ul>{candidateWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
              </Alert>
            )}
            {candidateGroups.length === 0 && (
              <EmptyState title="暂无候选证据" description="成功的检索调用产生候选后，可以在这里逐条接受或拒绝。" />
            )}
            {candidateGroups.map((group) => (
              <section key={group.findingId ?? "unknown"} className="verification-candidate-group">
                <h4><code>{group.issueCode}</code>（Finding #{group.findingId ?? "—"}）</h4>
                {group.candidates.map((candidate) => (
                  <CandidateCard
                    key={`${candidate.tool_call_id}-${candidate.candidate_rank}`}
                    candidate={candidate}
                    busy={busy === "decision"}
                    onAccept={() => setConfirmTarget({ candidate, decision: "accept" })}
                    onReject={() => setConfirmTarget({ candidate, decision: "reject" })}
                  />
                ))}
              </section>
            ))}
          </Card>
        </>
      )}

      {/* ── Supervisor 工作台（阶段 5B）────────────────────────── */}
      <Alert title="Supervisor 边界" tone="info">
        <ul>
          <li>{SUPERVISOR_BOUNDARY_TEXT.qualityGateDeterministic}</li>
          <li>{SUPERVISOR_BOUNDARY_TEXT.evidenceNotAutomatic}</li>
          <li>{SUPERVISOR_BOUNDARY_TEXT.gateFailNoReport}</li>
        </ul>
      </Alert>

      <Card>
        <div className="engineering-section-heading">
          <div><h3>启动 Supervisor</h3><p className="muted">确定性编排：Extraction → Verification → Quality Review → Reporting；只重试失败的节点。</p></div>
        </div>
        {completedRuns.length === 0 && (
          <EmptyState title="暂无已完成的 ReviewRun" description="先完成一次审查，再回来启动 Supervisor。" />
        )}
        {completedRuns.length > 0 && (
          <div className="verification-launch">
            <label>
              ReviewRun
              <select
                value={effectiveRunId ?? ""}
                onChange={(event) => switchRun(Number(event.target.value))}
              >
                {completedRuns.map((run) => (
                  <option key={run.id} value={run.id}>#{run.id}（{run.finding_count ?? 0} 个问题）</option>
                ))}
              </select>
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={useDeepseek}
                onChange={(event) => setUseDeepseek(event.target.checked)}
              />
              DeepSeek 规划
            </label>
            <label>
              Verification 预算（1～5）
              <input
                type="number"
                min="1"
                max="5"
                value={maxVerificationToolCalls}
                onChange={(event) => {
                  const value = Math.max(1, Math.min(5, Number(event.target.value) || 1));
                  setMaxVerificationToolCalls(value);
                }}
              />
            </label>
            <label>
              最大重试次数（0～2）
              <input
                type="number"
                min="0"
                max="2"
                value={maxStepRetries}
                onChange={(event) => {
                  const value = Math.max(0, Math.min(2, Number(event.target.value) || 0));
                  setMaxStepRetries(value);
                }}
              />
            </label>
            <label className="check-field">
              <input
                type="checkbox"
                checked={generateReport}
                onChange={(event) => setGenerateReport(event.target.checked)}
              />
              generate_report（质量门通过后生成报告）
            </label>
            <Button
              onClick={launchSupervisor}
              loading={supervisorBusy === "launch"}
              disabled={Boolean(busy) || Boolean(supervisorBusy) || !effectiveRunId}
            >
              启动 Supervisor
            </Button>
          </div>
        )}
        {launchSupervisorResult && (
          <Alert
            title={launchSupervisorResult.reused ? "复用已有 Supervisor 运行" : "Supervisor 已执行"}
            tone={launchSupervisorResult.reused ? "info" : "success"}
          >
            {launchSupervisorResult.reused
              ? `输入状态未变化，返回已有 SupervisorRun #${launchSupervisorResult.supervisor_run_id}（HTTP 200，reused=true）。`
              : `SupervisorRun #${launchSupervisorResult.supervisor_run_id}（HTTP 201，reused=false）状态：${SUPERVISOR_STATUS[launchSupervisorResult.status]?.[0] || launchSupervisorResult.status}。`}
          </Alert>
        )}
      </Card>

      {supervisorError && (
        <Alert title="Supervisor 操作未完成" tone="danger">
          <p><code>{supervisorError.code || "REQUEST_FAILED"}</code>：{supervisorError.message}</p>
          <p>{getSupervisorErrorSuggestion(supervisorError.code)}</p>
        </Alert>
      )}

      <Card>
        <h3>Supervisor 历史</h3>
        {supervisorRuns.length === 0 && (
          <EmptyState title="暂无 Supervisor 记录" description="启动一次 Supervisor 后，这里会保留四节点执行轨迹与质量门结果。" />
        )}
        {supervisorRuns.length > 0 && (
          <div className="file-table-wrap"><table className="file-table">
            <thead><tr><th>ID</th><th>状态</th><th>Reused</th><th>VerificationRun</th><th>报告</th><th>质量门</th><th>当前节点</th><th>错误</th><th>时间</th><th>操作</th></tr></thead>
            <tbody>{supervisorRuns.map((run) => (
              <tr key={run.supervisor_run_id}>
                <td>#{run.supervisor_run_id}</td>
                <td><StatusBadge status={run.status} dictionary={SUPERVISOR_STATUS} /></td>
                <td>{run.reused ? "是" : "否"}</td>
                <td>{run.verification_run_id ? `#${run.verification_run_id}` : "—"}</td>
                <td>{run.report_id ? `#${run.report_id}` : "—"}</td>
                <td>{run.quality_gate?.status === "passed" ? "通过" : (run.quality_gate?.status || "—")}</td>
                <td>{run.current_step || "—"}</td>
                <td className="wrap-cell">{run.error_code ? <><code>{run.error_code}</code><span className="muted">（{getSupervisorErrorSuggestion(run.error_code)}）</span></> : "—"}</td>
                <td>{formatDate(run.created_at)}</td>
                <td>
                  <Button size="sm" variant="secondary" onClick={() => setSelectedSupervisorId(run.supervisor_run_id)}>
                    查看轨迹
                  </Button>
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </Card>

      {loadingSupervisorDetail && <Skeleton lines={5} />}
      {!loadingSupervisorDetail && supervisorDetail && (
        <>
          <Card>
            <h3>Supervisor 详情 #{supervisorDetail.supervisor_run_id}</h3>
            <dl className="engineering-detail-list">
              <div><dt>状态</dt><dd><StatusBadge status={supervisorDetail.status} dictionary={SUPERVISOR_STATUS} /></dd></div>
              <div><dt>Reused</dt><dd>{supervisorDetail.reused ? "是（幂等复用）" : "否（新执行）"}</dd></div>
              <div><dt>graph / quality gate 版本</dt><dd>{supervisorDetail.graph_version} / {supervisorDetail.quality_gate_version}</dd></div>
              <div><dt>max_step_retries</dt><dd>{supervisorDetail.max_step_retries}</dd></div>
              <div><dt>retry_count</dt><dd>{supervisorDetail.retry_count}</dd></div>
              <div><dt>input_state_hash</dt><dd><code className="hash-text">{shortHash(supervisorDetail.input_state_hash)}</code></dd></div>
              <div><dt>VerificationRun</dt><dd>{supervisorDetail.verification_run_id ? `#${supervisorDetail.verification_run_id}` : "—"}</dd></div>
              <div><dt>耗时</dt><dd>{supervisorDetail.latency_ms != null ? `${supervisorDetail.latency_ms} ms` : "—"}</dd></div>
              <div><dt>创建 / 完成时间</dt><dd>{formatDate(supervisorDetail.created_at)} / {supervisorDetail.completed_at ? formatDate(supervisorDetail.completed_at) : "—"}</dd></div>
            </dl>
            {supervisorDetail.report_id && (
              <Alert title="报告已生成" tone="success">
                报告 #{supervisorDetail.report_id} 已关联到本次 Supervisor 运行。
                <Link to={`/engineering/projects/${workspaceId}/reports`}>前往审查报告</Link>
              </Alert>
            )}
          </Card>

          <Card>
            <h3>四节点时间线</h3>
            {supervisorTimeline.length === 0 && <EmptyState title="无执行轨迹" description="该 Supervisor 运行没有记录任何节点步骤。" />}
            {supervisorTimeline.map((group) => (
              <section key={group.node} className="supervisor-node">
                <div className="engineering-section-heading">
                  <strong>{group.label}</strong>
                  <StatusBadge status={group.last.status} dictionary={STEP_STATUS} />
                </div>
                <div className="file-table-wrap"><table className="file-table">
                  <thead><tr><th>attempt</th><th>retry_of</th><th>reused</th><th>状态</th><th>错误码</th><th>错误信息</th><th>耗时</th><th>时间</th></tr></thead>
                  <tbody>{group.attempts.map((step) => (
                    <tr key={step.id}>
                      <td>{step.attempt_number}</td>
                      <td>{step.retry_of_id ? `#${step.retry_of_id}` : "—"}</td>
                      <td>{step.reused ? "是" : "否"}</td>
                      <td><Badge tone={step.status === "success" ? "success" : step.status === "failed" ? "danger" : "info"}>{step.status}</Badge></td>
                      <td className="wrap-cell">{step.error_code ? <code>{step.error_code}</code> : "—"}</td>
                      <td className="wrap-cell">{step.error_message || "—"}</td>
                      <td>{step.latency_ms != null ? `${step.latency_ms} ms` : "—"}</td>
                      <td>{formatDate(step.created_at)}</td>
                    </tr>
                  ))}</tbody>
                </table></div>
              </section>
            ))}
          </Card>

          <Card>
            <h3>Quality Review 检查项</h3>
            {gateChecks.length === 0 && <EmptyState title="无检查项" description="质量门未产生检查记录。" />}
            {gateChecks.length > 0 && (
              <div className="file-table-wrap"><table className="file-table">
                <thead><tr><th>检查码</th><th>状态</th><th>Finding</th><th>Evidence</th><th>说明</th><th>可重试</th></tr></thead>
                <tbody>{gateChecks.map((check, index) => (
                  <tr key={`${check.check_code}-${index}`}>
                    <td><code>{check.check_code}</code></td>
                    <td><Badge tone={check.status === "pass" ? "success" : "danger"}>{check.status === "pass" ? "通过" : "未通过"}</Badge></td>
                    <td>#{check.finding_id}</td>
                    <td>{check.evidence_id ? `#${check.evidence_id}` : "—"}</td>
                    <td className="wrap-cell">{check.safe_message}</td>
                    <td>{check.retryable ? "是" : "否"}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
            <dl className="engineering-detail-list">
              <div><dt>质量门状态</dt><dd><Badge tone={qualityGate.status === "passed" ? "success" : "danger"}>{qualityGate.status === "passed" ? "passed" : qualityGate.status || "—"}</Badge></dd></div>
              <div><dt>reportable Finding</dt><dd>{reportableIds.length > 0 ? reportableIds.map((id) => `#${id}`).join("、") : "无"}</dd></div>
              <div><dt>need_more_information Finding</dt><dd>{needMoreIds.length > 0 ? needMoreIds.map((id) => `#${id}`).join("、") : "无"}</dd></div>
              <div><dt>related file ids</dt><dd>{relatedFileIds.length > 0 ? relatedFileIds.join("、") : "—"}</dd></div>
            </dl>
            {GATE_CHECK_CODE_LABELS && Object.keys(GATE_CHECK_CODE_LABELS).length > 0 && (
              <p className="muted">检查码说明：{Object.entries(GATE_CHECK_CODE_LABELS).map(([code, label]) => `${code}（${label}）`).join("；")}</p>
            )}
          </Card>

          {clarification.code && (
            <Card>
              <h3>澄清说明（clarification）</h3>
              <p>{clarification.message || "—"}</p>
              {Array.isArray(clarification.issues) && clarification.issues.length > 0 && (
                <ul>
                  {clarification.issues.map((issue, index) => (
                    <li key={`clarify-${index}`}>
                      {issue.safe_message || issue}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          {supervisorDetail.status === "needs_human" && (
            <Alert title="Supervisor 需要人工介入" tone="danger">
              <p><code>{supervisorDetail.error_code || "—"}</code>：{supervisorDetail.error_message || "未记录原因"}</p>
              <p>{getSupervisorErrorSuggestion(supervisorDetail.error_code)}</p>
              <p className="muted">恢复建议：修正问题后重新启动 Supervisor；成功运行会被幂等复用，needs_human/failed 运行不会伪装成功。</p>
            </Alert>
          )}
        </>
      )}

      <ConfirmDialog
        open={Boolean(confirmTarget)}
        title={confirmTarget?.decision === "accept" ? "接受为正式证据" : "拒绝候选"}
        description={confirmTarget ? (
          confirmTarget.decision === "accept"
            ? `将把该候选作为正式 Evidence 附加到 Finding ${confirmTarget.candidate.issue_code}（#${confirmTarget.candidate.finding_id}）。接受不会自动确认问题、降低风险或修改结论。`
            : `将拒绝 Finding ${confirmTarget.candidate.issue_code}（#${confirmTarget.candidate.finding_id}）的这条候选。拒绝不会修改任何 Evidence 或 Finding。`
        ) : ""}
        confirmLabel={confirmTarget?.decision === "accept" ? "确认接受" : "确认拒绝"}
        tone={confirmTarget?.decision === "accept" ? "primary" : "danger"}
        busy={busy === "decision"}
        onConfirm={submitDecision}
        onClose={() => setConfirmTarget(null)}
      />
    </div>
  );
}

function toolErrorHint(errorCode) {
  const hints = {
    ENGINEERING_RETRIEVAL_INDEX_MISSING: "索引未构建，系统已通过索引准备后重试",
    ENGINEERING_RETRIEVAL_INDEX_STALE: "材料已变化，系统已通过索引重建后重试",
    ENGINEERING_RETRIEVAL_MODEL_UNAVAILABLE: "Embedding 模型不可用，请稍后重新运行核验",
    ENGINEERING_VERIFICATION_BUDGET_EXCEEDED: "工具预算耗尽，可提高预算后重新运行",
    ENGINEERING_MCP_UNAVAILABLE: "MCP 服务不可用，核验上下文不完整；可稍后重试，候选检索不受影响",
    ENGINEERING_MCP_TIMEOUT: "MCP 服务响应超时，已重试；核验上下文可能不完整",
    ENGINEERING_MCP_DISCOVERY_ERROR: "MCP 工具发现失败，核验上下文不完整",
    ENGINEERING_MCP_TOOL_NOT_ALLOWED: "MCP 工具未授权，核验上下文不完整",
    ENGINEERING_MCP_REQUEST_INVALID: "MCP 请求参数不合法，核验上下文不完整",
    ENGINEERING_MCP_RESPONSE_INVALID: "MCP 响应不合法，核验上下文不完整",
    ENGINEERING_MCP_TOOL_ERROR: "MCP 工具执行失败，核验上下文不完整",
  };
  return hints[errorCode] || "可按错误码排查后重新运行核验";
}

function CandidateCard({ candidate, busy, onAccept, onReject }) {
  const decided = candidate.decision === "accept" || candidate.decision === "reject";
  const decisionMeta = decided ? CANDIDATE_DECISION_LABELS[candidate.decision] : null;
  return (
    <article className="evidence-card verification-candidate">
      <div className="engineering-section-heading">
        <strong>{candidate.file_name || `文件 #${candidate.file_id}`} · {formatCandidateLocator(candidate)}</strong>
        <Badge>{candidate.file_role || "未知角色"}</Badge>
      </div>
      <dl className="engineering-detail-list">
        <div><dt>rank</dt><dd>#{candidate.candidate_rank}（score {Number(candidate.score ?? 0).toFixed(4)}）</dd></div>
        <div><dt>BM25 / Dense rank</dt><dd>{candidate.bm25_rank || "—"} / {candidate.dense_rank || "—"}</dd></div>
        <div><dt>parser</dt><dd>{candidate.parser_name} {candidate.parser_version}</dd></div>
        <div><dt>content_hash</dt><dd><code className="hash-text">{shortHash(candidate.content_hash)}</code></dd></div>
        {decided && <div><dt>人工决定</dt><dd><Badge tone={decisionMeta[1]}>{decisionMeta[0]}</Badge></dd></div>}
        {decided && candidate.decision === "accept" && <div><dt>Evidence ID</dt><dd>#{candidate.evidence_id}</dd></div>}
        {decided && <div><dt>决定时间</dt><dd>{candidate.decision_created_at ? formatDate(candidate.decision_created_at) : "—"}</dd></div>}
        {decided && candidate.review_note && <div><dt>备注</dt><dd className="wrap-cell">{candidate.review_note}</dd></div>}
      </dl>
      <blockquote>{candidate.quote || "（无引用文本）"}</blockquote>
      {!decided && (
        <div className="row-actions">
          <Button size="sm" onClick={onAccept} disabled={busy}>接受为正式证据</Button>
          <Button size="sm" variant="secondary" onClick={onReject} disabled={busy}>拒绝候选</Button>
        </div>
      )}
    </article>
  );
}

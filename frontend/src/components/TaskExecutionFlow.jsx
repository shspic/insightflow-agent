import { useEffect, useMemo, useRef, useState } from "react";
import {
  answerTaskClarification,
  cancelWorkspaceTask,
  confirmTaskPlan,
  createWorkspaceTaskDraft,
  fetchWorkspaceTask,
  fetchWorkspaceTaskEvents,
  openWorkspaceTaskEventStream,
  patchTaskPlan,
  regenerateTaskPlan,
  retryWorkspaceTask,
  retryWorkspaceTaskStep,
} from "../api/workspaceTasks";
import ReportCenter from "./ReportCenter";
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  EmptyState,
  FormField,
  Progress,
  StatusBadge,
  Stepper,
  Textarea,
} from "./common";
import { useFeedback } from "../context/FeedbackContext";
import {
  AGENT_LABELS,
  FILE_STATUS,
  TASK_STATUS,
  mergeEvents,
  statusMeta,
  validatePlanSteps,
} from "../utils/ui";

const TERMINAL = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);
const LIVE = new Set(["queued", "running", "reviewing", "retrying"]);

function normalizeDependencies(steps) {
  const keys = steps.map((step) => step.step_key);
  return steps.map((step, index) => {
    if (step.agent_type === "file_understanding_agent") {
      return { ...step, depends_on: [] };
    }
    if (step.agent_type === "report_agent") {
      return { ...step, depends_on: keys.slice(0, index) };
    }
    if (step.agent_type === "quality_review_agent") {
      const report = steps.find((item) => item.agent_type === "report_agent");
      return { ...step, depends_on: report ? [report.step_key] : [] };
    }
    return { ...step, depends_on: ["understand_files"] };
  });
}

function statusText(status) {
  return {
    draft: "草稿",
    awaiting_clarification: "需要追问",
    planning: "生成计划中",
    awaiting_confirmation: "等待确认",
    queued: "排队中",
    running: "执行中",
    reviewing: "质量审核中",
    retrying: "局部重试中",
    completed: "已完成",
    completed_with_warnings: "已完成（有警告）",
    failed: "执行失败",
    cancelled: "已取消",
    pending: "等待执行",
  }[status] || status;
}

export default function TaskExecutionFlow({ workspaceId, files, onTaskChanged, initialTaskId = null }) {
  const [task, setTask] = useState(null);
  const [request, setRequest] = useState("");
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [useDeepseek, setUseDeepseek] = useState(false);
  const [templateKey, setTemplateKey] = useState("comprehensive_analysis");
  const [answers, setAnswers] = useState({});
  const [planDraft, setPlanDraft] = useState(null);
  const [events, setEvents] = useState([]);
  const [reportVisible, setReportVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [transport, setTransport] = useState("idle");
  const streamFailures = useRef(0);
  const lastEventIdRef = useRef(0);
  const { confirm, toast } = useFeedback();
  const lastEventId = useMemo(
    () => events.reduce((maximum, item) => Math.max(maximum, item.id || 0), 0),
    [events],
  );
  useEffect(() => { lastEventIdRef.current = lastEventId; }, [lastEventId]);

  useEffect(() => {
    if (!initialTaskId) return;
    let active = true;
    setBusy(true);
    Promise.all([
      fetchWorkspaceTask(workspaceId, initialTaskId),
      fetchWorkspaceTaskEvents(workspaceId, initialTaskId, 0),
    ]).then(([detail, taskEvents]) => {
      if (!active) return;
      setTask(detail);
      setEvents(mergeEvents(detail.latest_events || [], taskEvents));
      setError("");
    }).catch((requestError) => {
      if (active) setError(requestError.message);
    }).finally(() => {
      if (active) setBusy(false);
    });
    return () => { active = false; };
  }, [workspaceId, initialTaskId]);

  useEffect(() => {
    if (!task?.current_plan) {
      setPlanDraft(null);
      return;
    }
    setPlanDraft({
      goal: task.current_plan.goal,
      selected_file_ids: task.current_plan.selected_file_ids,
      assumptions: task.current_plan.assumptions,
      steps: task.current_plan.steps,
    });
  }, [task?.current_plan?.id]);

  useEffect(() => {
    if (!task || !LIVE.has(task.status)) {
      setTransport("idle");
      return undefined;
    }
    let pollingTimer;
    let closeStream = () => {};
    let closed = false;
    const refresh = async () => {
      const latest = await fetchWorkspaceTask(workspaceId, task.id);
      if (!closed) {
        setTask(latest);
        if (TERMINAL.has(latest.status)) onTaskChanged?.();
      }
    };
    const poll = async () => {
      try {
        const additions = await fetchWorkspaceTaskEvents(workspaceId, task.id, lastEventIdRef.current);
        if (!closed && additions.length) {
          setEvents((current) => mergeEvents(current, additions));
          await refresh();
        }
      } catch (pollError) {
        if (!closed) setError(pollError.message);
      }
    };
    const startPolling = () => {
      if (pollingTimer || closed) return;
      closeStream();
      setTransport("polling");
      pollingTimer = window.setInterval(poll, 2500);
      poll();
    };
    setTransport("connecting");
    closeStream = openWorkspaceTaskEventStream(workspaceId, task.id, {
      onOpen: () => {
        streamFailures.current = 0;
        setTransport("sse");
      },
      onEvent: async (event) => {
        setEvents((current) => mergeEvents(current, [event]));
        await refresh();
      },
      onError: () => {
        streamFailures.current += 1;
        setTransport("reconnecting");
        if (streamFailures.current >= 2) startPolling();
      },
    });
    return () => {
      closed = true;
      closeStream();
      if (pollingTimer) window.clearInterval(pollingTimer);
    };
  }, [workspaceId, task?.id, task?.status]);

  async function createDraft(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await createWorkspaceTaskDraft(workspaceId, {
        user_request: request.trim(),
        selected_file_ids: selectedFileIds,
        use_deepseek: useDeepseek,
        report_preferences: { format: "markdown", template_key: templateKey },
      });
      setTask(created);
      setEvents(mergeEvents([], created.latest_events || []));
      setError("");
      onTaskChanged?.();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitClarification(continueWithRecommendation) {
    setBusy(true);
    try {
      const updated = await answerTaskClarification(workspaceId, task.id, {
        answers,
        continue_with_recommendation: continueWithRecommendation,
      });
      setTask(updated);
      setEvents(mergeEvents(events, updated.latest_events || []));
      setAnswers({});
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function savePlan() {
    const validation = validatePlanSteps(planDraft.steps);
    if (!validation.valid) {
      setError(validation.message);
      return;
    }
    setBusy(true);
    try {
      const updatedPlan = await patchTaskPlan(
        workspaceId,
        task.id,
        task.current_plan.id,
        { ...planDraft, steps: normalizeDependencies(planDraft.steps) },
      );
      setTask(await fetchWorkspaceTask(workspaceId, task.id));
      setPlanDraft({
        goal: updatedPlan.goal,
        selected_file_ids: updatedPlan.selected_file_ids,
        assumptions: updatedPlan.assumptions,
        steps: updatedPlan.steps,
      });
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmPlan() {
    setBusy(true);
    try {
      const updated = await confirmTaskPlan(workspaceId, task.id, task.current_plan.id);
      setTask(updated);
      setEvents(mergeEvents(events, updated.latest_events || []));
      setError("");
      onTaskChanged?.();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function runAction(action) {
    setBusy(true);
    try {
      const updated = await action();
      setTask(updated);
      setEvents(mergeEvents(events, updated.latest_events || []));
      setError("");
      onTaskChanged?.();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  function moveStep(index, direction) {
    const nextIndex = index + direction;
    if (nextIndex <= 0 || nextIndex >= planDraft.steps.length - 2) return;
    const steps = [...planDraft.steps];
    [steps[index], steps[nextIndex]] = [steps[nextIndex], steps[index]];
    setPlanDraft({ ...planDraft, steps: normalizeDependencies(steps) });
  }

  function addOptionalStep(agentType) {
    if (planDraft.steps.some((step) => step.agent_type === agentType)) return;
    const reportIndex = planDraft.steps.findIndex((step) => step.agent_type === "report_agent");
    const step = agentType === "data_analysis_agent"
      ? {
          step_key: "analyze_tables",
          title: "分析表格数据",
          description: "执行预设 Pandas 统计并生成图表。",
          agent_type: agentType,
          tool_name: "preset_multi_table_analysis",
          depends_on: ["understand_files"],
          parameters: { generate_charts: true },
          optional: true,
        }
      : {
          step_key: "research_documents",
          title: "检索文档证据",
          description: "检索所选 PDF 和 Markdown。",
          agent_type: agentType,
          tool_name: "selected_document_retrieval",
          depends_on: ["understand_files"],
          parameters: { top_k: 5, retrieval_mode: "auto" },
          optional: true,
        };
    const steps = [...planDraft.steps];
    steps.splice(reportIndex, 0, step);
    setPlanDraft({ ...planDraft, steps: normalizeDependencies(steps) });
  }

  async function requestCancellation() {
    const accepted = await confirm({
      title: "请求取消当前任务？",
      description: "排队任务会立即取消；运行中的任务会在安全检查点停止，当前不可中断的库调用可能仍会完成。",
      confirmLabel: "请求取消",
    });
    if (accepted) {
      await runAction(() => cancelWorkspaceTask(workspaceId, task.id));
      toast("取消请求已提交");
    }
  }

  if (!task) {
    return (
      <form className="task-form" onSubmit={createDraft}>
        <Stepper steps={["选择文件", "输入目标", "输出偏好", "Agent 追问", "计划确认", "开始执行"]} current={0} />
        <fieldset className="task-file-picker">
          <legend>选择参与分析的文件</legend>
          <div className="task-file-options">
            {files.map((file) => (
              <label key={file.file_id} className="ui-choice task-file-option">
                <input type="checkbox"
                  checked={selectedFileIds.includes(file.file_id)}
                  onChange={() =>
                    setSelectedFileIds((current) =>
                      current.includes(file.file_id)
                        ? current.filter((id) => id !== file.file_id)
                        : [...current, file.file_id],
                    )
                  }
                />
                <span>
                  <strong>{file.display_name}</strong>
                  <small>{file.file_type} · {statusMeta(file.status, FILE_STATUS).label}
                    {file.status !== "ready" ? " · 建议先完成理解" : ""}</small>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {!files.length && <EmptyState title="还没有可选文件" description="请先在“文件”模块上传并理解资料。" />}
        <FormField label="分析目标" hint="说明要比较什么、需要回答什么，以及报告的使用场景。" required>
          <Textarea rows="5"
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            placeholder="例如：结合成绩表和课程要求，找出风险并生成带引用的行动建议报告"
          />
        </FormField>
        <Checkbox label="允许 DeepSeek 参与计划和质量审核"
          hint="不可用或输出不符合 Schema 时自动降级为确定性流程。"
          checked={useDeepseek} onChange={(event) => setUseDeepseek(event.target.checked)} />
        <FormField label="报告模板">
          <Select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
            <option value="comprehensive_analysis">综合分析报告</option>
            <option value="student_research">学生调研报告</option>
            <option value="job_application_analysis">求职资料分析</option>
          </Select>
        </FormField>
        {error && <Alert title="无法创建任务草稿" tone="danger">{error}</Alert>}
        <Button type="submit" loading={busy} disabled={!request.trim() || !selectedFileIds.length}>
          继续：创建任务草稿
        </Button>
      </form>
    );
  }

  const clarification = task.clarifications?.find((item) => item.status === "pending");
  const flowStep = task.status === "awaiting_clarification" ? 3
    : task.status === "awaiting_confirmation" ? 4
      : LIVE.has(task.status) || TERMINAL.has(task.status) ? 5 : 2;
  const createdAt = new Date(task.created_at).getTime();
  const updatedAt = new Date(task.updated_at).getTime();
  const elapsedSeconds = Number.isNaN(createdAt) || Number.isNaN(updatedAt)
    ? null : Math.max(0, Math.round((updatedAt - createdAt) / 1000));
  return (
    <div className="task-flow">
      <Stepper steps={["选择文件", "输入目标", "输出偏好", "Agent 追问", "计划确认", "开始执行"]} current={flowStep} />
      <div className="task-flow__status">
        <strong>任务 #{task.id}</strong>
        <StatusBadge status={task.status} dictionary={TASK_STATUS} />
        {elapsedSeconds !== null && <span>已用 {elapsedSeconds < 60 ? `${elapsedSeconds} 秒` : `${Math.floor(elapsedSeconds / 60)} 分钟`}</span>}
        {LIVE.has(task.status) && <Badge tone={transport === "sse" ? "success" : transport === "polling" ? "warning" : "info"}>
          {transport === "sse" ? "SSE 已连接" : transport === "polling" ? "轮询模式" : transport === "reconnecting" ? "SSE 重连中" : "正在连接"}
        </Badge>}
      </div>
      <Progress value={task.progress_percent} label={`总进度 · ${statusText(task.status)}`} />
      <p>{task.user_request}</p>
      {!task.model_available && useDeepseek && (
        <p className="form-message form-message--info">DeepSeek 当前不可用，系统正在使用确定性降级能力。</p>
      )}
      {transport === "polling" && <Alert title="实时连接已降级" tone="warning">
        页面正在每 2.5 秒增量获取事件；服务端任务不会受影响。
      </Alert>}
      {task.status === "queued" && <Alert title="任务正在排队" tone="info">
        如果长时间没有进展，请管理员在 Worker 页面检查心跳状态。
      </Alert>}
      {error && <Alert title="任务操作未完成" tone="danger">{error}</Alert>}

      {task.status === "awaiting_clarification" && clarification && (
        <section className="task-stage">
          <h4>Agent 需要补充信息</h4>
          {clarification.questions.map((question) => (
            <label key={question.id} className="ui-field">
              <strong>{question.question}</strong>
              <small>为什么需要：{question.reason}</small>
              {question.id === "selected_file_ids" ? (
                <div className="task-file-options">
                  {files.map((file) => (
                    <label key={file.file_id} className="task-file-option">
                      <input
                        type="checkbox"
                        checked={(answers.selected_file_ids || []).includes(file.file_id)}
                        onChange={() =>
                          setAnswers((current) => ({
                            ...current,
                            selected_file_ids: (current.selected_file_ids || []).includes(file.file_id)
                              ? current.selected_file_ids.filter((id) => id !== file.file_id)
                              : [...(current.selected_file_ids || []), file.file_id],
                          }))
                        }
                      />
                      {file.display_name}
                    </label>
                  ))}
                </div>
              ) : (
                <Textarea
                  rows="2"
                  value={answers[question.id] || ""}
                  placeholder={question.recommended_answer}
                  onChange={(event) =>
                    setAnswers({ ...answers, [question.id]: event.target.value })
                  }
                />
              )}
            </label>
          ))}
          <div className="row-actions">
            <Button type="button" loading={busy} onClick={() => submitClarification(false)}>提交回答</Button>
            <Button type="button" variant="secondary" disabled={busy} onClick={() => submitClarification(true)}>按系统建议继续</Button>
          </div>
        </section>
      )}

      {task.status === "awaiting_confirmation" && planDraft && (
        <section className="task-stage plan-editor">
          <h4>确认执行计划 v{task.current_plan.version}</h4>
          <Alert title="确认后才会占用执行配额" tone="info">
            预计模型调用 {task.current_plan.estimated_model_calls} 次，工具调用 {task.current_plan.estimated_tool_calls} 次。
          </Alert>
          <label>
            任务目标
            <Textarea
              rows="3"
              value={planDraft.goal}
              onChange={(event) => setPlanDraft({ ...planDraft, goal: event.target.value })}
            />
          </label>
          <fieldset className="task-file-picker">
            <legend>计划使用文件</legend>
            {files.map((file) => (
              <label key={file.file_id} className="task-file-option">
                <input
                  type="checkbox"
                  checked={planDraft.selected_file_ids.includes(file.file_id)}
                  onChange={() =>
                    setPlanDraft({
                      ...planDraft,
                      selected_file_ids: planDraft.selected_file_ids.includes(file.file_id)
                        ? planDraft.selected_file_ids.filter((id) => id !== file.file_id)
                        : [...planDraft.selected_file_ids, file.file_id],
                    })
                  }
                />
                {file.display_name}
              </label>
            ))}
          </fieldset>
          <p>假设：{planDraft.assumptions.join("；") || "无"}</p>
          <p>
            配额预估：模型 {task.current_plan.estimated_model_calls} 次，工具 {task.current_plan.estimated_tool_calls} 次
          </p>
          <div className="plan-steps">
            {planDraft.steps.map((step, index) => (
              <article key={step.step_key} className="plan-step">
                <strong>{index + 1}. {AGENT_LABELS[step.agent_type] || step.agent_type}</strong>
                <input
                  value={step.title}
                  onChange={(event) => {
                    const steps = planDraft.steps.map((item) =>
                      item.step_key === step.step_key ? { ...item, title: event.target.value } : item,
                    );
                    setPlanDraft({ ...planDraft, steps });
                  }}
                />
                <span>工具：{step.tool_name}</span>
                <span>依赖：{step.depends_on.join("、") || "无"}</span>
                {step.optional && (
                  <div className="row-actions">
                    <button type="button" onClick={() => moveStep(index, -1)}>上移</button>
                    <button type="button" onClick={() => moveStep(index, 1)}>下移</button>
                    <button
                      type="button"
                      onClick={() =>
                        setPlanDraft({
                          ...planDraft,
                          steps: normalizeDependencies(
                            planDraft.steps.filter((item) => item.step_key !== step.step_key),
                          ),
                        })
                      }
                    >
                      删除可选步骤
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
          <div className="row-actions">
            <button type="button" onClick={() => addOptionalStep("data_analysis_agent")}>增加表格分析</button>
            <button type="button" onClick={() => addOptionalStep("document_research_agent")}>增加文档检索</button>
          </div>
          <div className="row-actions">
            <Button type="button" disabled={busy} onClick={savePlan}>保存为新版本</Button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                runAction(async () => {
                  await regenerateTaskPlan(workspaceId, task.id);
                  return fetchWorkspaceTask(workspaceId, task.id);
                })
              }
            >
              重新生成计划
            </button>
            <Button type="button" loading={busy} onClick={confirmPlan}>确认并入队</Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={requestCancellation}
            >
              取消任务
            </Button>
          </div>
        </section>
      )}

      {task.steps?.length > 0 && (
        <section className="task-stage">
          <h4>执行步骤</h4>
          {task.steps.map((step) => (
            <article key={step.id} className="execution-step">
              <strong>{step.step_order}. {step.title}</strong>
              <span>{AGENT_LABELS[step.agent_type] || step.agent_type} · {step.tool_name}</span>
              <span>{statusText(step.status)} · {step.progress_percent}% · 已重试 {step.retry_count} 次</span>
              {step.output && <details><summary>结果摘要</summary><pre>{JSON.stringify(step.output, null, 2)}</pre></details>}
              {step.error_message && <span className="form-message--error">{step.error_message}</span>}
              {step.status === "failed" && (
                <button
                  type="button"
                  disabled={busy || task.retry_count >= task.max_retries}
                  onClick={() =>
                    runAction(() => retryWorkspaceTaskStep(workspaceId, task.id, step.id))
                  }
                >
                  从此失败步骤重试
                </button>
              )}
            </article>
          ))}
          {LIVE.has(task.status) && (
            <Button
              type="button"
              variant="warning"
              disabled={busy}
              onClick={requestCancellation}
            >
              请求取消
            </Button>
          )}
        </section>
      )}

      {task.latest_events?.length > 0 && (
        <section className="task-stage">
          <h4>Agent 事件时间线</h4>
          <ol className="event-timeline">
            {(events.length ? events : task.latest_events).map((event) => (
              <li key={event.id}>
                <time>{new Date(event.created_at).toLocaleTimeString()}</time>
                <strong>{AGENT_LABELS[event.agent_type] || event.event_type}</strong>
                <span>{event.message}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {TERMINAL.has(task.status) && (
        <section className="task-stage">
          <h4>最终结果</h4>
          <p>{task.final_result?.summary || task.result_summary?.summary || statusText(task.status)}</p>
          {task.current_plan && <details><summary>查看已确认计划 v{task.current_plan.version}</summary>
            <ol>{task.current_plan.steps.map((step) => <li key={step.step_key}>
              {AGENT_LABELS[step.agent_type] || step.agent_type}：{step.title}
            </li>)}</ol>
          </details>}
          {task.final_result?.warnings?.length > 0 && (
            <ul>{task.final_result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          )}
          <div className="row-actions">
            {task.has_report && (
              <button type="button" onClick={() => setReportVisible(true)}>查看报告中心</button>
            )}
            {["failed", "completed_with_warnings"].includes(task.status) && (
              <button
                type="button"
                disabled={busy || task.retry_count >= task.max_retries}
                onClick={() => runAction(() => retryWorkspaceTask(workspaceId, task.id))}
              >
                重试失败链路
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setTask(null);
                setEvents([]);
                setReportVisible(false);
              }}
            >
              新建任务
            </button>
          </div>
        </section>
      )}
      {reportVisible && <ReportCenter workspaceId={workspaceId} taskId={task.id} />}
    </div>
  );
}

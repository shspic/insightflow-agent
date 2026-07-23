import { useEffect, useMemo, useRef, useState } from "react";
import {
  answerTaskClarification,
  cancelWorkspaceTask,
  confirmTaskPlan,
  createWorkspaceTaskDraft,
  fetchWorkspaceReport,
  fetchWorkspaceTask,
  fetchWorkspaceTaskEvents,
  openWorkspaceTaskEventStream,
  patchTaskPlan,
  regenerateTaskPlan,
  retryWorkspaceTask,
  retryWorkspaceTaskStep,
} from "../api/workspaceTasks";
import ReportViewer from "./ReportViewer";

const TERMINAL = new Set(["completed", "completed_with_warnings", "failed", "cancelled"]);
const LIVE = new Set(["queued", "running", "reviewing", "retrying"]);

const AGENT_LABELS = {
  file_understanding_agent: "File Understanding Agent",
  data_analysis_agent: "Data Analysis Agent",
  document_research_agent: "Document Research Agent",
  report_agent: "Report Agent",
  quality_review_agent: "Quality Review Agent",
};

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
    queued: "排队中（请确认 Worker 已启动）",
    running: "执行中",
    reviewing: "质量审核中",
    retrying: "局部重试中",
    completed: "已完成",
    completed_with_warnings: "已完成（有警告）",
    failed: "执行失败",
    cancelled: "已取消",
  }[status] || status;
}

export default function TaskExecutionFlow({ workspaceId, files, onTaskChanged }) {
  const [task, setTask] = useState(null);
  const [request, setRequest] = useState("");
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [useDeepseek, setUseDeepseek] = useState(false);
  const [answers, setAnswers] = useState({});
  const [planDraft, setPlanDraft] = useState(null);
  const [events, setEvents] = useState([]);
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [transport, setTransport] = useState("idle");
  const streamFailures = useRef(0);
  const lastEventId = useMemo(
    () => events.reduce((maximum, item) => Math.max(maximum, item.id || 0), 0),
    [events],
  );

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
    let closed = false;
    const refresh = async () => {
      const latest = await fetchWorkspaceTask(workspaceId, task.id);
      if (!closed) {
        setTask(latest);
        onTaskChanged?.();
      }
    };
    const poll = async () => {
      try {
        const additions = await fetchWorkspaceTaskEvents(workspaceId, task.id, lastEventId);
        if (!closed && additions.length) {
          setEvents((current) => [...current, ...additions]);
          await refresh();
        }
      } catch (pollError) {
        if (!closed) setError(pollError.message);
      }
    };
    const startPolling = () => {
      if (pollingTimer || closed) return;
      setTransport("polling");
      pollingTimer = window.setInterval(poll, 2500);
      poll();
    };
    setTransport("sse");
    const closeStream = openWorkspaceTaskEventStream(workspaceId, task.id, {
      onOpen: () => {
        streamFailures.current = 0;
        setTransport("sse");
      },
      onEvent: async (event) => {
        setEvents((current) =>
          current.some((item) => item.id === event.id) ? current : [...current, event],
        );
        await refresh();
      },
      onError: () => {
        streamFailures.current += 1;
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
        report_preferences: { format: "markdown" },
      });
      setTask(created);
      setEvents(created.latest_events || []);
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
      setEvents(updated.latest_events || []);
      setAnswers({});
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function savePlan() {
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
      setEvents(updated.latest_events || []);
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
      setEvents(updated.latest_events || []);
      setError("");
      onTaskChanged?.();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadReport() {
    try {
      setReport(await fetchWorkspaceReport(workspaceId, task.id));
    } catch (requestError) {
      setError(requestError.message);
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

  if (!task) {
    return (
      <form className="task-form" onSubmit={createDraft}>
        <fieldset className="task-file-picker">
          <legend>选择参与分析的文件</legend>
          <div className="task-file-options">
            {files.map((file) => (
              <label key={file.file_id} className="task-file-option">
                <input
                  type="checkbox"
                  checked={selectedFileIds.includes(file.file_id)}
                  onChange={() =>
                    setSelectedFileIds((current) =>
                      current.includes(file.file_id)
                        ? current.filter((id) => id !== file.file_id)
                        : [...current, file.file_id],
                    )
                  }
                />
                <span>#{file.file_id} {file.display_name}（{file.file_type}，{file.status}）</span>
              </label>
            ))}
          </div>
        </fieldset>
        <label>
          自然语言需求
          <textarea
            rows="5"
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            placeholder="例如：结合成绩表和课程要求，找出风险并生成带引用的行动建议报告"
          />
        </label>
        <label className="task-file-option">
          <input
            type="checkbox"
            checked={useDeepseek}
            onChange={(event) => setUseDeepseek(event.target.checked)}
          />
          允许 DeepSeek 参与计划和质量审核（不可用时自动降级）
        </label>
        {error && <p className="form-message form-message--error">{error}</p>}
        <button type="submit" disabled={busy || !request.trim()}>
          {busy ? "创建中…" : "创建任务草稿"}
        </button>
      </form>
    );
  }

  const clarification = task.clarifications?.find((item) => item.status === "pending");
  return (
    <div className="task-flow">
      <div className="task-flow__status">
        <strong>任务 #{task.id}</strong>
        <span>{statusText(task.status)}</span>
        <span>进度 {task.progress_percent}%</span>
        {LIVE.has(task.status) && <span>实时通道：{transport === "sse" ? "SSE" : "轮询降级"}</span>}
      </div>
      <progress max="100" value={task.progress_percent} />
      <p>{task.user_request}</p>
      {!task.model_available && useDeepseek && (
        <p className="form-message form-message--info">DeepSeek 当前不可用，系统正在使用确定性降级能力。</p>
      )}
      {error && <p className="form-message form-message--error">{error}</p>}

      {task.status === "awaiting_clarification" && clarification && (
        <section className="task-stage">
          <h4>Agent 需要补充信息</h4>
          {clarification.questions.map((question) => (
            <label key={question.id}>
              {question.question}
              <small>{question.reason}</small>
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
                <textarea
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
            <button type="button" disabled={busy} onClick={() => submitClarification(false)}>提交回答</button>
            <button type="button" disabled={busy} onClick={() => submitClarification(true)}>按系统推荐继续</button>
          </div>
        </section>
      )}

      {task.status === "awaiting_confirmation" && planDraft && (
        <section className="task-stage plan-editor">
          <h4>确认执行计划 v{task.current_plan.version}</h4>
          <label>
            任务目标
            <textarea
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
            预计模型调用 {task.current_plan.estimated_model_calls} 次，工具调用 {task.current_plan.estimated_tool_calls} 次
          </p>
          <div className="plan-steps">
            {planDraft.steps.map((step, index) => (
              <article key={step.step_key} className="plan-step">
                <strong>{index + 1}. {AGENT_LABELS[step.agent_type]}</strong>
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
            <button type="button" disabled={busy} onClick={savePlan}>保存为新版本</button>
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
            <button type="button" disabled={busy} onClick={confirmPlan}>确认并入队</button>
            <button
              type="button"
              disabled={busy}
              onClick={() => runAction(() => cancelWorkspaceTask(workspaceId, task.id))}
            >
              取消任务
            </button>
          </div>
        </section>
      )}

      {task.steps?.length > 0 && (
        <section className="task-stage">
          <h4>执行步骤</h4>
          {task.steps.map((step) => (
            <article key={step.id} className="execution-step">
              <strong>{step.step_order}. {step.title}</strong>
              <span>{AGENT_LABELS[step.agent_type]} · {step.tool_name}</span>
              <span>{statusText(step.status)} · {step.progress_percent}%</span>
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
            <button
              type="button"
              disabled={busy}
              onClick={() => runAction(() => cancelWorkspaceTask(workspaceId, task.id))}
            >
              请求取消
            </button>
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
                <strong>{event.agent_type || event.event_type}</strong>
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
          {task.final_result?.warnings?.length > 0 && (
            <ul>{task.final_result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          )}
          <div className="row-actions">
            {task.has_report && <button type="button" onClick={loadReport}>查看 Markdown 报告</button>}
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
                setReport(null);
              }}
            >
              新建任务
            </button>
          </div>
        </section>
      )}
      <ReportViewer report={report} />
    </div>
  );
}

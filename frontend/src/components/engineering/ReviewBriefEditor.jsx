import { useEffect, useState } from "react";
import {
  confirmReviewBrief,
  createReviewBrief,
} from "../../api/engineeringReviews";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  FormField,
  SectionHeader,
  Textarea,
} from "../common";
import {
  REVIEW_CHECK_TYPES,
  REVIEW_OUTPUT_REQUIREMENTS,
  buildReviewBriefPayload,
  shortHash,
} from "../../utils/engineeringReview";
import { formatDate } from "../../utils/ui";

const defaultForm = {
  rawRequirements: "",
  objectives: "完成工程投标材料的确定性规则审查",
  requiredCheckTypes: REVIEW_CHECK_TYPES.map(([value]) => value),
  excludedCheckTypes: [],
  excludedScopes: "",
  priorityFields: "",
  outputRequirements: REVIEW_OUTPUT_REQUIREMENTS.map(([value]) => value),
  clarificationQuestions: [],
};

function formFromBrief(brief) {
  const interpreted = brief?.interpreted || {};
  return {
    rawRequirements: brief?.raw_requirements || "",
    objectives: (interpreted.objectives || []).join("\n"),
    requiredCheckTypes: interpreted.required_check_types || defaultForm.requiredCheckTypes,
    excludedCheckTypes: interpreted.excluded_check_types || [],
    excludedScopes: (interpreted.excluded_scopes || []).join("\n"),
    priorityFields: (interpreted.priority_fields || []).join("\n"),
    outputRequirements: interpreted.output_requirements || defaultForm.outputRequirements,
    clarificationQuestions: interpreted.clarification_questions || brief?.clarification_questions || [],
  };
}

function toggleValue(values, value) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function StructuredPreview({ brief }) {
  const interpreted = brief.interpreted || {};
  return (
    <Card className="brief-preview">
      <div className="engineering-section-heading">
        <h3>结构化解释预览</h3>
        <Badge tone={brief.status === "confirmed" ? "success" : "warning"}>
          {brief.status === "confirmed" ? "已确认" : "草稿"}
        </Badge>
      </div>
      <dl className="engineering-detail-list">
        <div><dt>Brief 版本</dt><dd>v{brief.version}</dd></div>
        <div><dt>content_hash</dt><dd><code>{shortHash(brief.content_hash)}</code></dd></div>
        <div><dt>确认时间</dt><dd>{formatDate(brief.confirmed_at)}</dd></div>
        <div><dt>解释方式</dt><dd>{brief.interpreter_type === "manual" ? "用户人工结构化确认" : brief.interpreter_type}</dd></div>
      </dl>
      <div><strong>原始要求</strong><p className="preserve-lines">{brief.raw_requirements}</p></div>
      <div className="brief-structured-grid">
        <div><strong>审查目标</strong><ul>{(interpreted.objectives || []).map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div><strong>必需检查类型</strong><p>{(interpreted.required_check_types || []).join("、") || "—"}</p></div>
        <div><strong>排除检查类型</strong><p>{(interpreted.excluded_check_types || []).join("、") || "无"}</p></div>
        <div><strong>排除范围</strong><p>{(interpreted.excluded_scopes || []).join("、") || "无"}</p></div>
        <div><strong>优先字段</strong><p>{(interpreted.priority_fields || []).join("、") || "无"}</p></div>
        <div><strong>输出要求</strong><p>{(interpreted.output_requirements || []).join("、") || "无"}</p></div>
      </div>
    </Card>
  );
}

export default function ReviewBriefEditor({ workspaceId, currentBrief, onBriefChanged }) {
  const [form, setForm] = useState(() => currentBrief ? formFromBrief(currentBrief) : defaultForm);
  const [draft, setDraft] = useState(null);
  const [editing, setEditing] = useState(!currentBrief);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (currentBrief && !editing) setForm(formFromBrief(currentBrief));
  }, [currentBrief, editing]);

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function saveDraft() {
    if (!form.rawRequirements.trim()) {
      setError("请填写特殊要求或约束的原始文本。");
      return;
    }
    if (!form.objectives.trim() || form.requiredCheckTypes.length === 0) {
      setError("至少需要一个审查目标和一种必需检查类型。");
      return;
    }
    setBusy("save");
    setError("");
    try {
      const created = await createReviewBrief(workspaceId, buildReviewBriefPayload(form));
      setDraft(created);
      setEditing(false);
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setBusy("");
    }
  }

  async function confirmDraft() {
    if (!draft) return;
    setBusy("confirm");
    setError("");
    try {
      const confirmed = await confirmReviewBrief(workspaceId, draft.id);
      setDraft(null);
      setEditing(false);
      onBriefChanged(confirmed);
    } catch (requestError) {
      setError(`${requestError.code ? `${requestError.code}：` : ""}${requestError.message}`);
    } finally {
      setBusy("");
    }
  }

  const preview = draft || currentBrief;
  const questions = draft?.clarification_questions || draft?.interpreted?.clarification_questions || [];

  return (
    <div className="engineering-stack">
      <SectionHeader title="审查要求" description="保留原始要求，并由用户把要求整理为后端允许的固定白名单结构。" />
      <Alert title="人工解释边界" tone="info">
        当前审查要求由用户人工确认；Supervisor 自动意图解释将在可信 Agent 阶段接入。
      </Alert>
      {currentBrief && !editing && (
        <Alert title="当前已确认 Brief" tone="success" action={(
          <Button variant="secondary" onClick={() => { setForm(formFromBrief(currentBrief)); setDraft(null); setEditing(true); }}>
            创建新版本
          </Button>
        )}>
          新版本不会修改任何历史 ReviewRun 的 Brief 快照。
        </Alert>
      )}
      {error && <Alert title="审查要求未保存" tone="danger">{error}</Alert>}
      {editing && (
        <Card className="brief-editor">
          <FormField label="特殊要求或约束" required hint="原始文本会原样保留在 ReviewBrief 中。">
            <Textarea rows="6" value={form.rawRequirements}
              placeholder="请描述本项目需要重点检查的内容、特殊阈值、排除范围和报告要求。"
              onChange={(event) => update("rawRequirements", event.target.value)} />
          </FormField>
          <FormField label="审查目标" required hint="每行一个审查目标。">
            <Textarea rows="4" value={form.objectives} onChange={(event) => update("objectives", event.target.value)} />
          </FormField>
          <fieldset className="engineering-choice-group"><legend>必需检查类型</legend>
            {REVIEW_CHECK_TYPES.map(([value, label]) => <Checkbox key={value} label={label} hint={value}
              checked={form.requiredCheckTypes.includes(value)}
              onChange={() => update("requiredCheckTypes", toggleValue(form.requiredCheckTypes, value))} />)}
          </fieldset>
          <fieldset className="engineering-choice-group"><legend>排除检查类型（可选）</legend>
            {REVIEW_CHECK_TYPES.map(([value, label]) => <Checkbox key={value} label={label} hint={value}
              checked={form.excludedCheckTypes.includes(value)}
              onChange={() => update("excludedCheckTypes", toggleValue(form.excludedCheckTypes, value))} />)}
          </fieldset>
          <div className="engineering-form-grid">
            <FormField label="排除范围" hint="每行一个排除范围。"><Textarea rows="4" value={form.excludedScopes}
              onChange={(event) => update("excludedScopes", event.target.value)} /></FormField>
            <FormField label="优先字段" hint="每行一个字段路径，例如 bid_response.project_name。"><Textarea rows="4" value={form.priorityFields}
              onChange={(event) => update("priorityFields", event.target.value)} /></FormField>
          </div>
          <fieldset className="engineering-choice-group"><legend>输出要求</legend>
            {REVIEW_OUTPUT_REQUIREMENTS.map(([value, label]) => <Checkbox key={value} label={label} hint={value}
              checked={form.outputRequirements.includes(value)}
              onChange={() => update("outputRequirements", toggleValue(form.outputRequirements, value))} />)}
          </fieldset>
          <div className="row-actions">
            <Button onClick={saveDraft} loading={busy === "save"}>保存草稿</Button>
            {currentBrief && <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditing(false)}>取消新版本</Button>}
          </div>
        </Card>
      )}
      {preview && !editing && <StructuredPreview brief={preview} />}
      {draft && questions.length > 0 && (
        <Alert title="存在待澄清问题，暂不能确认" tone="warning">
          <ul>{questions.map((question) => <li key={question}>{question}</li>)}</ul>
          请返回修改原始要求或结构化内容，再保存新草稿。
        </Alert>
      )}
      {draft && !editing && (
        <div className="row-actions">
          <Button variant="secondary" disabled={Boolean(busy)} onClick={() => setEditing(true)}>返回修改</Button>
          <Button onClick={confirmDraft} loading={busy === "confirm"} disabled={questions.length > 0}>确认审查要求</Button>
        </div>
      )}
    </div>
  );
}

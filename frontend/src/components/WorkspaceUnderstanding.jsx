import { useEffect, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import {
  discoverWorkspaceFileRelations,
  fetchWorkspaceFileProfile,
  fetchWorkspaceFileRelations,
  previewWorkspaceContext,
  understandWorkspaceFile,
  understandWorkspaceFiles,
  updateWorkspaceFileProfile,
  updateWorkspaceFileRelation,
  uploadWorkspaceFilesBatch,
} from "../api/fileUnderstanding";
import { removeWorkspaceFile } from "../api/workspaceFiles";
import BatchFileUploader from "./BatchFileUploader";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  FormField,
  Input,
  Select,
  SectionHeader,
  StatusBadge,
} from "./common";
import { useFeedback } from "../context/FeedbackContext";
import { FILE_STATUS, RELATION_STATUS, fileTypeMeta } from "../utils/ui";

const FILE_ROLES = [
  ["primary_dataset", "主要数据集"],
  ["supplementary_dataset", "补充数据集"],
  ["rule_document", "规则文档"],
  ["reference_document", "参考文档"],
  ["resume", "简历"],
  ["job_description", "岗位说明"],
  ["research_material", "研究资料"],
  ["image_evidence", "图片证据"],
  ["report_template", "报告模板"],
  ["supporting_material", "支持材料"],
  ["unknown", "未知"],
  ["custom", "自定义"],
];

const RELATION_TYPES = [
  ["same_dataset", "同一数据集"],
  ["continuation", "连续数据"],
  ["comparison", "对比关系"],
  ["reference_rule", "规则引用"],
  ["supporting_document", "支持文档"],
  ["derived_from", "派生自"],
  ["image_evidence", "图片证据"],
  ["unrelated", "无关"],
  ["custom", "自定义"],
];

function friendlyError(error) {
  if (!(error instanceof ApiError)) return error.message || "请求失败";
  const labels = {
    401: "Session 已失效，请重新登录。",
    403: "当前账号没有权限执行此操作。",
    413: "文件过大或单次数量超过限制。",
    415: "文件类型、MIME 或内容特征不受支持。",
    422: "文件或表单未通过服务端校验。",
    429: "工作区或用户配额不足。",
    500: "服务器暂时无法处理请求。",
  };
  return `${labels[error.status] || ""}${labels[error.status] ? " " : ""}${error.message}`;
}

function formatConfidence(value) {
  if (value === null || value === undefined) return "-";
  return `${Number(value).toFixed(2)} 匹配分`;
}

function formatBytes(value) {
  if (value === null || value === undefined) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function roleLabel(value) {
  if (!value) return "-";
  if (value.startsWith("custom:")) return value.slice("custom:".length);
  return FILE_ROLES.find(([key]) => key === value)?.[1] || value;
}

function relationLabel(value) {
  if (!value) return "-";
  if (value.startsWith("custom:")) return value.slice("custom:".length);
  return RELATION_TYPES.find(([key]) => key === value)?.[1] || value;
}

function StructureSummary({ profile }) {
  const structure = profile.structure || {};
  if (profile.file_category === "table") {
    return (
      <div className="profile-structure">
        {(structure.tables || []).map((table, index) => (
          <div key={`${table.sheet_name || table.table_name}-${index}`}>
            <strong>{table.sheet_name || table.table_name || `表 ${index + 1}`}</strong>
            <span>{table.row_count ?? "-"} 行 · {table.column_count ?? "-"} 列</span>
            <span>
              字段：{(table.columns || []).slice(0, 20).map((column) => column.name).join("、") || "-"}
            </span>
          </div>
        ))}
      </div>
    );
  }
  if (profile.file_category === "document" && structure.page_count !== undefined) {
    return (
      <div className="profile-structure">
        <span>页数：{structure.page_count}</span>
        <span>分块：{structure.chunk_count ?? 0}</span>
        <span>疑似扫描件：{structure.suspected_scanned ? "是" : "否"}</span>
        <span>标题候选：{(structure.heading_candidates || []).slice(0, 8).join("、") || "-"}</span>
      </div>
    );
  }
  if (profile.file_category === "image") {
    return (
      <div className="profile-structure">
        <span>尺寸：{structure.width}×{structure.height}</span>
        <span>格式：{structure.format}</span>
        <span>图片判断：{structure.image_kind}</span>
        <span>OCR：{structure.ocr_status} · {structure.ocr_text_length || 0} 字符</span>
      </div>
    );
  }
  return (
    <div className="profile-structure">
      <span>标题：{structure.title || profile.title || "-"}</span>
      <span>标题数量：{structure.heading_count ?? 0}</span>
      <span>代码块：{structure.code_block_count ?? 0}</span>
      <span>表格：{structure.table_count ?? 0}</span>
      <span>链接：{structure.link_count ?? 0}</span>
      <span>文本长度：{structure.text_length ?? 0}</span>
    </div>
  );
}

function ProfileEditor({ profile, onSave, isSaving }) {
  const currentRole = profile.confirmed_role?.startsWith("custom:") ? "custom" : (
    profile.confirmed_role || profile.suggested_role || "unknown"
  );
  const [role, setRole] = useState(currentRole);
  const [customRole, setCustomRole] = useState(
    profile.confirmed_role?.startsWith("custom:")
      ? profile.confirmed_role.slice("custom:".length)
      : "",
  );
  const [tags, setTags] = useState(profile.user_tags.join("，"));

  async function save(roleValue = role) {
    await onSave({
      confirmed_role: roleValue,
      custom_role: roleValue === "custom" ? customRole : null,
      user_tags: tags
        .split(/[,，]/)
        .map((item) => item.trim())
        .filter(Boolean)
        .slice(0, 20),
    });
  }

  return (
    <div className="profile-editor">
      <label>
        确认角色
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          {FILE_ROLES.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      {role === "custom" && (
        <label>
          自定义角色
          <input
            maxLength="60"
            value={customRole}
            onChange={(event) => setCustomRole(event.target.value)}
          />
        </label>
      )}
      <label>
        用户标签（逗号分隔）
        <input
          maxLength="620"
          value={tags}
          onChange={(event) => setTags(event.target.value)}
        />
      </label>
      <div className="row-actions">
        <button type="button" disabled={isSaving} onClick={() => save()}>
          {isSaving ? "保存中" : "保存角色和标签"}
        </button>
        {profile.suggested_role && (
          <button
            type="button"
            disabled={isSaving}
            onClick={() => {
              setRole(profile.suggested_role);
              save(profile.suggested_role);
            }}
          >
            确认推荐角色
          </button>
        )}
      </div>
    </div>
  );
}

function ProfileCard({ file, profile, busy, onUnderstand, onSave, onRemove }) {
  const typeMeta = fileTypeMeta(file.file_type);
  return (
    <article className="file-profile-card">
      <div className="section-heading">
        <div>
          <h4 title={file.display_name}><span className="file-type-glyph" aria-hidden="true">{typeMeta.glyph}</span> {file.display_name}</h4>
          <p>{typeMeta.label} · {formatBytes(file.size_bytes)} · <StatusBadge status={file.status} dictionary={FILE_STATUS} /></p>
        </div>
        <div className="row-actions">
          <Button type="button" disabled={busy} loading={busy} onClick={onUnderstand}>
            {busy ? "理解中" : profile ? "重新理解" : "理解文件"}
          </Button>
          <Button type="button" variant="ghost" disabled={busy} onClick={onRemove}>移除</Button>
        </div>
      </div>
      {!profile && <p className="parse-empty">尚未生成文件 Profile。</p>}
      {profile && (
        <details className="profile-details">
          <summary>
            <span>{profile.summary || "查看结构化 Profile"}</span>
            <Badge tone={profile.fallback_used ? "warning" : "success"}>
              v{profile.profile_version} · {profile.fallback_used ? "已降级" : profile.status}
            </Badge>
          </summary>
          <div className="profile-meta-grid">
            <span>Profile：v{profile.profile_version} · {profile.status}</span>
            <span>类型：{profile.file_category || "-"}</span>
            <span>推荐角色：{roleLabel(profile.suggested_role)}</span>
            <span>确认角色：{roleLabel(profile.confirmed_role)}</span>
            <span>角色匹配信号：{formatConfidence(profile.confidence)}</span>
            <span>解析器：{profile.parser_name || "-"} / {profile.parser_version || "-"}</span>
            <span>
              DeepSeek：{profile.model_provider
                ? `${profile.model_provider}/${profile.model_name}${profile.fallback_used ? "（已降级）" : ""}`
                : "未启用"}
            </span>
            <span>系统标签：{profile.system_tags.join("、") || "-"}</span>
          </div>
          {profile.error_message && (
            <p className="form-message form-message--error">
              {profile.error_code}: {profile.error_message}
            </p>
          )}
          <div className="profile-summary">
            <strong>摘要</strong>
            <p>{profile.summary || "暂无摘要"}</p>
          </div>
          <StructureSummary profile={profile} />
          <div className="quality-list">
            <strong>数据质量与降级信息</strong>
            {profile.quality_issues.length === 0 && <span>未发现明确问题</span>}
            {profile.quality_issues.map((issue, index) => (
              <span key={`${issue.code}-${index}`}>
                {issue.severity} · {issue.code}：{issue.message}
              </span>
            ))}
          </div>
          <ProfileEditor profile={profile} onSave={onSave} isSaving={busy} />
        </details>
      )}
    </article>
  );
}

function RelationCard({ relation, busy, onMutate }) {
  const [relationType, setRelationType] = useState(
    relation.relation_type.startsWith("custom:") ? "custom" : relation.relation_type,
  );
  const [customType, setCustomType] = useState(
    relation.relation_type.startsWith("custom:")
      ? relation.relation_type.slice("custom:".length)
      : "",
  );
  const [note, setNote] = useState(relation.user_note || "");
  return (
    <article className="relation-card">
      <div className="section-heading">
        <div>
          <h4>{relation.source_filename} → {relation.target_filename}</h4>
          <p>
            {relationLabel(relation.relation_type)} · {formatConfidence(relation.confidence)}
            · 规则等级 {relation.confidence_level} · <StatusBadge status={relation.status} dictionary={RELATION_STATUS} />
          </p>
        </div>
      </div>
      <div className="relation-evidence">
        {Object.entries(relation.evidence || {}).map(([key, value]) => (
          <span key={key}>{key}：{typeof value === "string" ? value : JSON.stringify(value)}</span>
        ))}
      </div>
      <div className="relation-editor">
        <label>
          关系类型
          <select value={relationType} onChange={(event) => setRelationType(event.target.value)}>
            {RELATION_TYPES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        {relationType === "custom" && (
          <label>
            自定义关系
            <input
              maxLength="60"
              value={customType}
              onChange={(event) => setCustomType(event.target.value)}
            />
          </label>
        )}
        <label>
          用户备注
          <input maxLength="500" value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
      </div>
      <div className="row-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => onMutate({ action: "confirm", user_note: note })}
        >
          确认
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onMutate({ action: "reject", user_note: note })}
        >
          拒绝
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onMutate({
            action: "replace",
            relation_type: relationType,
            custom_relation_type: relationType === "custom" ? customType : null,
            user_note: note,
          })}
        >
          修改并确认
        </button>
      </div>
    </article>
  );
}

function ContextPreview({ context }) {
  if (!context) return <p className="parse-empty">尚未生成上下文预览。</p>;
  return (
    <div className="context-preview">
      <p>
        Schema {context.context_version} · 已包含 {context.files.length} 个文件
        {context.limits.truncated ? " · 已按限制裁剪" : ""}
      </p>
      <div className="context-grid">
        <div>
          <strong>文件与角色</strong>
          {context.files.map((file) => (
            <span key={file.file_id}>#{file.file_id} {file.filename}：{roleLabel(file.effective_role)}</span>
          ))}
        </div>
        <div>
          <strong>已确认关系</strong>
          {context.confirmed_relations.map((relation) => (
            <span key={relation.relation_id}>
              #{relation.source_file_id} → #{relation.target_file_id}：{relationLabel(relation.relation_type)}
            </span>
          ))}
          {context.confirmed_relations.length === 0 && <span>无</span>}
        </div>
        <div>
          <strong>高置信待确认关系</strong>
          {context.pending_high_confidence_relations.map((relation) => (
            <span key={relation.relation_id}>
              #{relation.source_file_id} → #{relation.target_file_id}：{relationLabel(relation.relation_type)}
            </span>
          ))}
          {context.pending_high_confidence_relations.length === 0 && <span>无</span>}
        </div>
        <div>
          <strong>未就绪文件</strong>
          {context.unready_files.map((file) => (
            <span key={file.file_id}>#{file.file_id} {file.filename}：{file.profile_status}</span>
          ))}
          {context.unready_files.length === 0 && <span>无</span>}
        </div>
      </div>
      {context.data_quality_issues.length > 0 && (
        <div className="quality-list">
          <strong>质量问题</strong>
          {context.data_quality_issues.map((issue, index) => (
            <span key={`${issue.file_id}-${issue.code}-${index}`}>
              {issue.filename} · {issue.code}：{issue.message}
            </span>
          ))}
        </div>
      )}
      <p>
        可用能力：{context.available_tools.join("、")}。上下文不含完整原文；
        最大文件数 {context.limits.max_files}，最大字符数 {context.limits.max_chars}。
      </p>
    </div>
  );
}

export default function WorkspaceUnderstanding({ workspaceId, files, onFilesChanged, mode = "files" }) {
  const [profiles, setProfiles] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [relations, setRelations] = useState([]);
  const [context, setContext] = useState(null);
  const [busy, setBusy] = useState({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [roleFilter, setRoleFilter] = useState("all");
  const [relationFilter, setRelationFilter] = useState("all");
  const { confirm, toast } = useFeedback();
  const fileKey = useMemo(() => files.map((file) => file.file_id).join(","), [files]);
  const visibleFiles = useMemo(() => files.filter((file) => {
    const profile = profiles[file.file_id];
    const query = search.trim().toLocaleLowerCase("zh-CN");
    return (!query || file.display_name.toLocaleLowerCase("zh-CN").includes(query))
      && (typeFilter === "all" || file.file_type === typeFilter)
      && (statusFilter === "all" || file.status === statusFilter)
      && (roleFilter === "all" || profile?.effective_role === roleFilter);
  }), [files, profiles, search, typeFilter, statusFilter, roleFilter]);
  const visibleRelations = useMemo(
    () => relationFilter === "all" ? relations : relations.filter((item) => item.status === relationFilter),
    [relations, relationFilter],
  );

  async function loadProfiles() {
    const entries = await Promise.all(
      files.map(async (file) => {
        try {
          return [file.file_id, await fetchWorkspaceFileProfile(workspaceId, file.file_id)];
        } catch (requestError) {
          if (requestError.status === 404) return [file.file_id, null];
          throw requestError;
        }
      }),
    );
    setProfiles(Object.fromEntries(entries));
  }

  async function loadRelations() {
    setRelations(await fetchWorkspaceFileRelations(workspaceId));
  }

  useEffect(() => {
    let active = true;
    const requests = [];
    if (mode === "files") requests.push(loadProfiles());
    if (mode === "relations") requests.push(loadRelations());
    Promise.all(requests).catch((requestError) => {
      if (active) setError(friendlyError(requestError));
    });
    setSelectedIds((current) => current.filter((id) => files.some((file) => file.file_id === id)));
    return () => {
      active = false;
    };
  }, [workspaceId, fileKey, mode]);

  async function runBusy(key, action, successMessage) {
    setBusy((current) => ({ ...current, [key]: true }));
    setError("");
    try {
      await action();
      if (successMessage) {
        setMessage(successMessage);
        toast(successMessage);
      }
    } catch (requestError) {
      setError(friendlyError(requestError));
    } finally {
      setBusy((current) => ({ ...current, [key]: false }));
    }
  }

  async function understandOne(fileId) {
    await runBusy(`file-${fileId}`, async () => {
      const result = await understandWorkspaceFile(workspaceId, fileId, {
        use_deepseek: false,
        run_ocr: true,
      });
      const profile = await fetchWorkspaceFileProfile(workspaceId, fileId);
      setProfiles((current) => ({ ...current, [fileId]: profile }));
      await onFilesChanged?.();
      if (result.status !== "ready") throw new Error(result.message);
    }, "文件理解完成");
  }

  async function understandSelected() {
    if (selectedIds.length === 0) {
      setError("请先选择文件");
      return;
    }
    await runBusy("batch-understand", async () => {
      const result = await understandWorkspaceFiles(workspaceId, selectedIds, {
        use_deepseek: false,
        run_ocr: true,
      });
      await loadProfiles();
      await onFilesChanged?.();
      const failed = result.results.filter((item) => item.status !== "ready");
      setMessage(failed.length ? `${failed.length} 个文件未完成理解` : "批量理解完成");
    });
  }

  async function saveProfile(fileId, payload) {
    await runBusy(`file-${fileId}`, async () => {
      const profile = await updateWorkspaceFileProfile(workspaceId, fileId, payload);
      setProfiles((current) => ({ ...current, [fileId]: profile }));
    }, "角色和标签已保存");
  }

  async function removeFile(fileId) {
    const file = files.find((item) => item.file_id === fileId);
    const accepted = await confirm({
      title: `从工作区移除“${file?.display_name || "此文件"}”？`,
      description: "文件关联关系会被清理，依赖它的已有任务和报告可能无法再次完整复现。原始文件会等待服务端清理策略处理。",
      confirmLabel: "确认移除",
    });
    if (!accepted) return;
    await runBusy(`file-${fileId}`, async () => {
      await removeWorkspaceFile(workspaceId, fileId);
      setProfiles((current) => {
        const updated = { ...current };
        delete updated[fileId];
        return updated;
      });
      await onFilesChanged?.();
      await loadRelations();
    }, "文件已从工作区移除");
  }

  async function discoverRelations() {
    await runBusy("relations", async () => {
      const result = await discoverWorkspaceFileRelations(workspaceId, {
        file_ids: selectedIds.length > 1 ? selectedIds : null,
        use_deepseek: false,
      });
      setRelations(await fetchWorkspaceFileRelations(workspaceId));
      setMessage(`关系识别完成：新增 ${result.created_count}，更新 ${result.updated_count}`);
    });
  }

  async function mutateRelation(relationId, payload) {
    await runBusy(`relation-${relationId}`, async () => {
      await updateWorkspaceFileRelation(workspaceId, relationId, payload);
      await loadRelations();
      setContext(null);
    }, "关系状态已更新");
  }

  async function previewContext() {
    await runBusy("context", async () => {
      setContext(await previewWorkspaceContext(
        workspaceId,
        selectedIds.length ? selectedIds : null,
      ));
    }, "上下文预览已更新");
  }

  return (
    <div className="workspace-understanding">
      {error && <Alert title="操作未完成" tone="danger">{error}</Alert>}
      {message && <span className="sr-only" aria-live="polite">{message}</span>}
      {mode === "files" && (
        <>
          <BatchFileUploader
            uploadAction={(selectedFiles) => uploadWorkspaceFilesBatch(workspaceId, selectedFiles)}
            onUploaded={onFilesChanged}
            storageHint="上传后还需要执行“理解文件”，才会生成结构、质量问题和角色建议。"
          />
          <div className="filter-bar" role="search">
            <FormField label="搜索文件"><Input type="search" value={search}
              placeholder="按文件名搜索" onChange={(event) => setSearch(event.target.value)} /></FormField>
            <FormField label="类型"><Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="all">全部类型</option>
              {[...new Set(files.map((file) => file.file_type).filter(Boolean))].map((value) =>
                <option key={value} value={value}>{fileTypeMeta(value).label}</option>)}
            </Select></FormField>
            <FormField label="状态"><Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">全部状态</option>
              {Object.entries(FILE_STATUS).map(([value, meta]) => <option key={value} value={value}>{meta[0]}</option>)}
            </Select></FormField>
            <FormField label="角色"><Select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
              <option value="all">全部角色</option>
              {FILE_ROLES.filter(([value]) => value !== "custom").map(([value, label]) =>
                <option key={value} value={value}>{label}</option>)}
            </Select></FormField>
          </div>
          <SectionHeader title="文件与 Profile" description="选择文件执行批量理解；展开单个文件查看结构、质量与角色。"
            actions={<Button loading={busy["batch-understand"]} disabled={!selectedIds.length}
              onClick={understandSelected}>批量理解 {selectedIds.length || ""}</Button>} />
          <div className="file-selection-list">
            {visibleFiles.map((file) => (
              <label key={file.file_id}>
                <input type="checkbox" checked={selectedIds.includes(file.file_id)}
                  onChange={() => setSelectedIds((current) => current.includes(file.file_id)
                    ? current.filter((id) => id !== file.file_id) : [...current, file.file_id])} />
                <span title={file.display_name}>{file.display_name}</span>
              </label>
            ))}
          </div>
          <div className="file-profile-list">
            {visibleFiles.map((file) => (
              <ProfileCard key={`${file.file_id}-${profiles[file.file_id]?.id || "none"}`}
                file={file} profile={profiles[file.file_id]} busy={Boolean(busy[`file-${file.file_id}`])}
                onUnderstand={() => understandOne(file.file_id)}
                onSave={(payload) => saveProfile(file.file_id, payload)}
                onRemove={() => removeFile(file.file_id)} />
            ))}
            {visibleFiles.length === 0 && <EmptyState title={files.length ? "没有匹配文件" : "还没有文件"}
              description={files.length ? "调整筛选条件。" : "先上传资料，再执行批量理解。"} />}
          </div>
        </>
      )}
      {mode === "relations" && (
        <section className="understanding-section">
          <SectionHeader title="文件关系" description="候选来自规则或可选模型增强，匹配分不是准确率；确认后才进入 Workspace Context。"
            actions={<Button loading={busy.relations} disabled={files.length < 2} onClick={discoverRelations}>生成候选</Button>} />
          <div className="filter-bar">
            <FormField label="候选范围"><Select value={relationFilter} onChange={(event) => setRelationFilter(event.target.value)}>
              <option value="all">全部状态</option>
              {Object.entries(RELATION_STATUS).map(([value, meta]) => <option key={value} value={value}>{meta[0]}</option>)}
            </Select></FormField>
            <span className="muted">选择两个以上文件可缩小发现范围</span>
          </div>
          <div className="file-selection-list">
            {files.map((file) => <label key={file.file_id}><input type="checkbox"
              checked={selectedIds.includes(file.file_id)}
              onChange={() => setSelectedIds((current) => current.includes(file.file_id)
                ? current.filter((id) => id !== file.file_id) : [...current, file.file_id])} />{file.display_name}</label>)}
          </div>
          <div className="relation-list">
            {visibleRelations.map((relation) => <RelationCard key={relation.id} relation={relation}
              busy={Boolean(busy[`relation-${relation.id}`])}
              onMutate={(payload) => mutateRelation(relation.id, payload)} />)}
            {visibleRelations.length === 0 && <EmptyState title="暂无关系候选"
              description="至少需要两个已理解文件。生成后请逐条确认、拒绝或修改。" />}
          </div>
        </section>
      )}
      {mode === "context" && (
        <section className="understanding-section">
          <SectionHeader title="Workspace Context" description="预览 Supervisor 可读取的安全结构化上下文，不包含完整原文或服务器路径。"
            actions={<Button loading={busy.context} onClick={previewContext}>生成预览</Button>} />
          <div className="file-selection-list">
            {files.map((file) => <label key={file.file_id}><input type="checkbox"
              checked={selectedIds.includes(file.file_id)}
              onChange={() => setSelectedIds((current) => current.includes(file.file_id)
                ? current.filter((id) => id !== file.file_id) : [...current, file.file_id])} />{file.display_name}</label>)}
          </div>
          <ContextPreview context={context} />
        </section>
      )}
    </div>
  );
}

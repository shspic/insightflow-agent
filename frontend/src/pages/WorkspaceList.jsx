import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { fetchMyUsage } from "../api/operations";
import {
  createWorkspace,
  deleteWorkspace,
  fetchWorkspaces,
  updateWorkspace,
} from "../api/workspaces";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  EmptyState,
  FormField,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Textarea,
} from "../components/common";
import { useFeedback } from "../context/FeedbackContext";
import { formatDate, mapApiError, quotaState } from "../utils/ui";

const LABELS = {
  engineering: {
    title: "engineering",
    eyebrow: "工程投标审查",
    description: "每个审查项目独立管理招标要求、投标响应、人员设备清单和资质附件。",
    createLabel: "新建审查项目",
    emptyTitle: "创建第一个审查项目",
    emptyDesc: "上传招标要求、投标文件、人员设备清单和资质附件，系统帮助核对一致性。",
    detailPath: (id) => `/engineering/projects/${id}`,
    formNameLabel: "项目名称",
    formDescLabel: "项目说明",
    workspaceType: "engineering",
  },
  general: {
    title: "general",
    eyebrow: "通用文档分析（旧版）",
    description: "保留原有多模态文档与数据分析能力，不再横向扩展。",
    createLabel: "创建工作区",
    emptyTitle: "创建第一个工作区",
    emptyDesc: "工作区会把资料、任务和报告组织在同一个上下文中。",
    detailPath: (id) => `/general/workspaces/${id}`,
    formNameLabel: "工作区名称",
    formDescLabel: "描述（可选）",
    workspaceType: "general",
  },
};

export default function WorkspaceList({ type = "general" }) {
  const labels = LABELS[type] || LABELS.general;
  const [items, setItems] = useState([]);
  const [usage, setUsage] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [form, setForm] = useState({ name: "", description: "" });
  const [dialog, setDialog] = useState(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState(null);
  const { confirm, toast } = useFeedback();
  const navigate = useNavigate();

  async function load() {
    try {
      const [workspaceData, usageData] = await Promise.all([
        fetchWorkspaces(true, labels.workspaceType),
        fetchMyUsage().catch(() => null),
      ]);
      setItems(workspaceData);
      setUsage(usageData);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { load(); }, [type]);

  async function handleCreate(event) {
    event.preventDefault();
    setIsSaving(true);
    try {
      const created = await createWorkspace({
        ...form,
        workspace_type: labels.workspaceType,
      });
      setItems((current) => [created, ...current]);
      setForm({ name: "", description: "" });
      setDialog(null);
      toast(labels.workspaceType === "engineering" ? "审查项目已创建" : "工作区已创建");
      if (labels.workspaceType === "engineering") {
        navigate(labels.detailPath(created.id));
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  async function updateItem(item, payload, successMessage) {
    setIsSaving(true);
    try {
      const updated = await updateWorkspace(item.id, payload);
      setItems((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      setDialog(null);
      toast(successMessage);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  async function removeItem(item) {
    setDeleteTarget(item);
    setDeleteConfirmName('');
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    if (deleteConfirmName !== deleteTarget.name) return;
    setIsSaving(true);
    try {
      const result = await deleteWorkspace(deleteTarget.id, deleteTarget.name);
      setItems((current) => current.filter((entry) => entry.id !== deleteTarget.id));
      setDeleteTarget(null);
      setDeleteConfirmName('');
      const warnings = result.storage_cleanup_warnings || [];
      if (warnings.length > 0) {
        toast('业务数据已删除，但部分磁盘资产清理失败。');
      } else {
        toast('已永久删除');
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase('zh-CN');
    return items.filter((item) => {
      const statusMatches = statusFilter === 'all'
        || (!item.is_deleted && item.status === statusFilter);
      const queryMatches = !query
        || item.name.toLocaleLowerCase('zh-CN').includes(query)
        || (item.description || '').toLocaleLowerCase('zh-CN').includes(query);
      return statusMatches && queryMatches;
    });
  }, [items, search, statusFilter]);

  const workspaceQuota = usage && quotaState(usage.usage.workspaces, usage.limits.workspaces);

  return (
    <section className="page-section">
      <PageHeader
        eyebrow={labels.eyebrow}
        title={labels.title}
        description={labels.description}
        actions={<Button onClick={() => {
          setForm({ name: "", description: "" });
          setDialog({ type: "create" });
        }}>{labels.createLabel}</Button>}
      />
      {workspaceQuota?.warning && (
        <Alert title="工作区配额接近上限" tone={workspaceQuota.tone}>
          当前 {usage.usage.workspaces} / {usage.limits.workspaces}。可归档不再使用的工作区，或永久删除以释放存储。
        </Alert>
      )}
      {error && <Alert title="工作区操作未完成" tone="danger">
        {mapApiError({ message: error }).message}
      </Alert>}
      <div className="filter-bar" role="search">
        <FormField label="搜索">
          <Input type="search" placeholder="按名称或描述搜索" value={search}
            onChange={(event) => setSearch(event.target.value)} />
        </FormField>
        <FormField label="状态">
          <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="active">使用中</option>
            <option value="archived">已归档</option>
            <option value="all">全部</option>
          </Select>
        </FormField>
        <span className="muted">显示 {filtered.length} / {items.length}</span>
      </div>
      {isLoading && <div className="card-grid"><Skeleton lines={4} /><Skeleton lines={4} /><Skeleton lines={4} /></div>}
      <div className="card-grid">
        {!isLoading && filtered.map((item) => (
          <article className="workspace-card" key={item.id}>
            <div className="section-heading">
              <h3>{item.name}</h3>
              <Badge tone={item.status === "archived" ? "warning" : "success"}>
                {item.status === "archived" ? "已归档" : "使用中"}
              </Badge>
            </div>
            <p>{item.description || "暂无描述"}</p>
            <div className="workspace-card__meta">
              <span>文件 {item.file_count}</span> · <span>任务 {item.task_count}</span>
              <br />最近更新 {formatDate(item.updated_at)}
            </div>
            <div className="row-actions">
              {!item.is_deleted && <Link className="button-link" to={labels.detailPath(item.id)}>
                {type === "engineering" ? "打开项目" : "打开工作区"}
              </Link>}
              {!item.is_deleted && (
                <Button variant="secondary" onClick={() => {
                  setForm({ name: item.name, description: item.description || "" });
                  setDialog({ type: "edit", item });
                }}>编辑</Button>
              )}
              {!item.is_deleted && (
                <Button variant="secondary" onClick={() => updateItem(
                  item,
                  { status: item.status === "active" ? "archived" : "active" },
                  item.status === "active" ? "工作区已归档" : "工作区已恢复使用",
                )}>{item.status === "active" ? "归档" : "恢复使用"}</Button>
              )}
              {!item.is_deleted && (
                <Button variant="danger" onClick={() => removeItem(item)}>永久删除</Button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!isLoading && filtered.length === 0 && (
        <EmptyState
          title={items.length ? "没有匹配的项目" : labels.emptyTitle}
          description={items.length ? "调整搜索词或状态筛选。" : labels.emptyDesc}
          action={!items.length && <Button onClick={() => setDialog({ type: "create" })}>{labels.createLabel}</Button>}
        />
      )}
      <Dialog
        open={Boolean(dialog)}
        busy={isSaving}
        onClose={() => setDialog(null)}
        title={dialog?.type === "edit"
          ? (type === "engineering" ? "编辑审查项目" : "编辑工作区")
          : labels.createLabel}
        description="名称用于导航和报告上下文，描述可以说明资料范围或分析目标。"
        footer={(
          <>
            <Button variant="secondary" onClick={() => setDialog(null)}>取消</Button>
            <Button type="submit" form="workspace-form" loading={isSaving}>
              {dialog?.type === "edit" ? "保存修改" : "创建"}
            </Button>
          </>
        )}
      >
        <form id="workspace-form" className="auth-form" onSubmit={(event) => {
          if (dialog?.type === "edit") {
            event.preventDefault();
            updateItem(dialog.item, { name: form.name.trim(), description: form.description.trim() || null }, "工作区信息已更新");
          } else {
            handleCreate(event);
          }
        }}>
          <FormField label={labels.formNameLabel} required>
            <Input required autoFocus maxLength="255" value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </FormField>
          <FormField label={labels.formDescLabel} hint={`${form.description.length} / 2000`}>
            <Textarea maxLength="2000" value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </FormField>
        </form>
      </Dialog>
      <Dialog
        open={Boolean(deleteTarget)}
        busy={isSaving}
        onClose={() => { if (!isSaving) { setDeleteTarget(null); setDeleteConfirmName(""); } }}
        title={`永久删除"${deleteTarget?.name || ""}"？`}
        description="项目及其关联业务数据将从当前系统永久删除，无法通过产品界面恢复。"
        footer={(
          <>
            <Button variant="secondary" onClick={() => { setDeleteTarget(null); setDeleteConfirmName(""); }} disabled={isSaving}>取消</Button>
            <Button variant="danger" onClick={confirmDelete} loading={isSaving}
              disabled={deleteConfirmName !== deleteTarget?.name}>
              确认永久删除
            </Button>
          </>
        )}
      >
        <p className="muted">
          {type === "engineering" ? "项目" : "工作区"}包含文件 {" "}
          {deleteTarget?.file_count ?? 0} 个、任务 {deleteTarget?.task_count ?? 0} 个。
        </p>
        <FormField label={`输入完整${type === "engineering" ? "项目" : "工作区"}名称以确认`} required>
          <Input
            autoFocus
            value={deleteConfirmName}
            onChange={(event) => setDeleteConfirmName(event.target.value)}
            placeholder={deleteTarget?.name || ""}
          />
        </FormField>
      </Dialog>
    </section>
  );
}

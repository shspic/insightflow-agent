import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchMyUsage } from "../api/operations";
import {
  createWorkspace,
  deleteWorkspace,
  fetchWorkspaces,
  restoreWorkspace,
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

export default function WorkspaceList() {
  const [items, setItems] = useState([]);
  const [usage, setUsage] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [form, setForm] = useState({ name: "", description: "" });
  const [dialog, setDialog] = useState(null);
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const { confirm, toast } = useFeedback();

  async function load() {
    try {
      const [workspaceData, usageData] = await Promise.all([
        fetchWorkspaces(true),
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

  useEffect(() => { load(); }, []);

  async function handleCreate(event) {
    event.preventDefault();
    setIsSaving(true);
    try {
      const created = await createWorkspace(form);
      setItems((current) => [created, ...current]);
      setForm({ name: "", description: "" });
      setDialog(null);
      toast("工作区已创建");
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
    const accepted = await confirm({
      title: `软删除“${item.name}”？`,
      description: "工作区会从默认列表隐藏，文件、任务和报告不会立刻物理删除，并可在已删除筛选中恢复。",
      confirmLabel: "软删除",
    });
    if (!accepted) return;
    try {
      await deleteWorkspace(item.id);
      setItems((current) => current.map((entry) =>
        entry.id === item.id ? { ...entry, is_deleted: true } : entry));
      toast("工作区已软删除");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function restoreItem(item) {
    try {
      const restored = await restoreWorkspace(item.id);
      setItems((current) => current.map((entry) => entry.id === item.id ? restored : entry));
      toast("工作区已恢复");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  const filtered = useMemo(() => {
    const query = search.trim().toLocaleLowerCase("zh-CN");
    return items.filter((item) => {
      const statusMatches = statusFilter === "all"
        || (statusFilter === "deleted" ? item.is_deleted : !item.is_deleted && item.status === statusFilter);
      const queryMatches = !query
        || item.name.toLocaleLowerCase("zh-CN").includes(query)
        || (item.description || "").toLocaleLowerCase("zh-CN").includes(query);
      return statusMatches && queryMatches;
    });
  }, [items, search, statusFilter]);

  const workspaceQuota = usage && quotaState(usage.usage.workspaces, usage.limits.workspaces);

  return (
    <section className="page-section">
      <PageHeader
        eyebrow="资料与任务的安全边界"
        title="工作区"
        description="每个工作区独立管理文件理解、分析计划、执行事件和报告版本。"
        actions={<Button onClick={() => {
          setForm({ name: "", description: "" });
          setDialog({ type: "create" });
        }}>创建工作区</Button>}
      />
      {workspaceQuota?.warning && (
        <Alert title="工作区配额接近上限" tone={workspaceQuota.tone}>
          当前 {usage.usage.workspaces} / {usage.limits.workspaces}。可归档不再使用的工作区，软删除不会立即释放文件存储。
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
            <option value="deleted">已删除</option>
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
              <Badge tone={item.is_deleted ? "danger" : item.status === "archived" ? "warning" : "success"}>
                {item.is_deleted ? "已删除" : item.status === "archived" ? "已归档" : "使用中"}
              </Badge>
            </div>
            <p>{item.description || "暂无描述"}</p>
            <div className="workspace-card__meta">
              <span>文件 {item.file_count}</span> · <span>任务 {item.task_count}</span>
              <br />最近更新 {formatDate(item.updated_at)}
            </div>
            <div className="row-actions">
              {!item.is_deleted && <Link className="button-link" to={`/workspaces/${item.id}`}>打开工作区</Link>}
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
                <Button variant="danger" onClick={() => removeItem(item)}>软删除</Button>
              )}
              {item.is_deleted && (
                <Button variant="secondary" onClick={() => restoreItem(item)}>恢复</Button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!isLoading && filtered.length === 0 && (
        <EmptyState
          title={items.length ? "没有匹配的工作区" : "创建第一个工作区"}
          description={items.length ? "调整搜索词或状态筛选。" : "工作区会把资料、任务和报告组织在同一个上下文中。"}
          action={!items.length && <Button onClick={() => setDialog({ type: "create" })}>创建工作区</Button>}
        />
      )}
      <Dialog
        open={Boolean(dialog)}
        busy={isSaving}
        onClose={() => setDialog(null)}
        title={dialog?.type === "edit" ? "编辑工作区" : "创建工作区"}
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
          <FormField label="工作区名称" required>
            <Input required autoFocus maxLength="255" value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </FormField>
          <FormField label="描述（可选）" hint={`${form.description.length} / 2000`}>
            <Textarea maxLength="2000" value={form.description}
              onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </FormField>
        </form>
      </Dialog>
    </section>
  );
}

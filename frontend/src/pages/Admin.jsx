import { useEffect, useReducer, useState } from "react";
import {
  buildInviteCodePayload,
  createInviteCode,
  fetchAuditLogs,
  fetchInviteCodes,
  fetchResetRequests,
  fetchUsers,
  issueTemporaryPassword,
  rejectResetRequest,
  rotateInviteCode,
  updateInviteCode,
  updateUserStatus,
} from "../api/admin";
import AdminOperations from "../components/AdminOperations";
import {
  Alert,
  Badge,
  Button,
  Dialog,
  EmptyState,
  FormField,
  Input,
  PageHeader,
  Tabs,
} from "../components/common";
import { useFeedback } from "../context/FeedbackContext";
import { formatDate, oneTimeSecretReducer } from "../utils/ui";

const TABS = [
  ["operations", "运行治理"],
  ["users", "用户"],
  ["invites", "邀请码"],
  ["resets", "密码重置"],
  ["audits", "审计日志"],
];

export default function Admin() {
  const [invites, setInvites] = useState([]);
  const [requests, setRequests] = useState([]);
  const [users, setUsers] = useState([]);
  const [audits, setAudits] = useState([]);
  const [secret, dispatchSecret] = useReducer(oneTimeSecretReducer, { title: "", value: "", visible: false });
  const [error, setError] = useState("");
  const [customInviteCode, setCustomInviteCode] = useState("");
  const [maxUses, setMaxUses] = useState("5");
  const [active, setActive] = useState("operations");
  const [busy, setBusy] = useState("");
  const { confirm, toast } = useFeedback();

  async function load() {
    try {
      const [inviteData, requestData, userData, auditData] = await Promise.all([
        fetchInviteCodes(), fetchResetRequests(), fetchUsers(), fetchAuditLogs(),
      ]);
      setInvites(inviteData);
      setRequests(requestData);
      setUsers(userData.items);
      setAudits(auditData.items);
      setError("");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => { load(); }, []);

  async function run(name, action, onSuccess, successMessage) {
    setBusy(name);
    try {
      const result = await action();
      onSuccess?.(result);
      if (successMessage) toast(successMessage);
      await load();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy("");
    }
  }

  async function confirmAction(options, action) {
    const accepted = await confirm(options);
    if (accepted) await action();
  }

  return (
    <section className="page-section">
      <PageHeader eyebrow="仅展示运行与治理元数据" title="管理后台"
        description="普通用户原始文件和完整报告正文不会在这里展示。高风险操作需要二次确认并写入审计日志。" />
      {error && <Alert title="管理操作未完成" tone="danger">{error}</Alert>}
      <Tabs items={TABS.map(([value, label]) => ({ value, label }))} value={active} onChange={setActive}
        label="管理员信息架构" />

      {active === "operations" && <AdminOperations />}

      {active === "invites" && (
        <section className="panel">
          <div className="section-heading"><div><h2>邀请码</h2><p className="muted">原始邀请码只在创建或轮换响应中显示一次。</p></div></div>
          <form className="inline-form" onSubmit={(event) => {
            event.preventDefault();
            run("invite-create", () => createInviteCode(
              buildInviteCodePayload(customInviteCode, maxUses),
            ),
              (result) => {
                setCustomInviteCode("");
                dispatchSecret({ type: "show", title: "新邀请码", value: result.invite_code });
              },
              "邀请码已创建");
          }}>
            <FormField label="自定义邀请码（可选）"
              hint="留空时由系统自动生成。支持 8～64 位英文字母、数字、-、_。">
              <Input minLength="8" maxLength="64" pattern={"[A-Za-z0-9_\\-]{8,64}"}
                autoComplete="off" value={customInviteCode}
                onChange={(event) => setCustomInviteCode(event.target.value)} />
            </FormField>
            <FormField label="最大使用次数"><Input type="number" min="1" value={maxUses}
              onChange={(event) => setMaxUses(event.target.value)} /></FormField>
            <Button loading={busy === "invite-create"}>创建邀请码</Button>
          </form>
          <div className="table-scroll"><table className="file-table"><thead><tr>
            <th>提示</th><th>状态</th><th>使用</th><th>过期时间</th><th>操作</th>
          </tr></thead><tbody>
            {invites.map((invite) => <tr key={invite.id}>
              <td>{invite.code_hint}</td><td><Badge tone={invite.status === "active" ? "success" : "warning"}>{invite.status}</Badge></td>
              <td>{invite.used_count}/{invite.max_uses ?? "不限"}</td><td>{formatDate(invite.expires_at, "不限")}</td>
              <td><div className="row-actions">
                <Button size="sm" variant="secondary" onClick={() => run("invite-status", () => updateInviteCode(
                  invite.id, { status: invite.status === "disabled" ? "active" : "disabled" }),
                null, invite.status === "disabled" ? "邀请码已启用" : "邀请码已停用")}>
                  {invite.status === "disabled" ? "启用" : "停用"}
                </Button>
                <Button size="sm" variant="warning" onClick={() => confirmAction({
                  title: "轮换邀请码？", description: "旧邀请码会立即失效，使用次数会重置；新值只显示一次。",
                  confirmLabel: "确认轮换", tone: "warning",
                }, () => run("invite-rotate", () => rotateInviteCode(invite.id),
                  (result) => dispatchSecret({ type: "show", title: "轮换后的邀请码", value: result.invite_code }),
                  "邀请码已轮换"))}>轮换</Button>
              </div></td>
            </tr>)}
          </tbody></table></div>
        </section>
      )}

      {active === "resets" && (
        <section className="panel">
          <h2>密码重置申请</h2>
          {requests.map((item) => <article className="task-card" key={item.id}>
            <div className="section-heading"><strong>{item.username}</strong><Badge tone="warning">{item.status}</Badge></div>
            <p>{item.request_note || "无申请说明"}</p><p className="muted">{formatDate(item.requested_at)}</p>
            <div className="row-actions">
              <Button variant="danger" onClick={() => confirmAction({
                title: `拒绝 ${item.username} 的重置申请？`, description: "申请会标记为拒绝并写入审计日志。",
                confirmLabel: "拒绝申请",
              }, () => run("reset-reject", () => rejectResetRequest(item.id, "管理员拒绝"), null, "申请已拒绝"))}>拒绝</Button>
              <Button onClick={() => confirmAction({
                title: `为 ${item.username} 生成临时密码？`,
                description: "现有 Session 会撤销，用户下次登录必须改密。临时密码只显示一次。",
                confirmLabel: "生成临时密码", tone: "warning",
              }, () => run("reset-issue", () => issueTemporaryPassword(item.id, "管理员已线下核验"),
                (result) => dispatchSecret({
                  type: "show", title: `${item.username} 的临时密码`, value: result.temporary_password,
                }), "临时密码已生成"))}>生成临时密码</Button>
            </div>
          </article>)}
          {!requests.length && <EmptyState title="暂无待处理申请" description="新的匿名密码重置申请会显示在这里。" />}
        </section>
      )}

      {active === "users" && (
        <section className="panel">
          <h2>用户</h2>
          <div className="table-scroll"><table className="file-table"><thead><tr>
            <th>账号</th><th>角色</th><th>状态</th><th>创建时间</th><th>最后登录</th><th>操作</th>
          </tr></thead><tbody>
            {users.map((user) => <tr key={user.id}><td>{user.username}</td><td>{user.role}</td>
              <td><Badge tone={user.status === "active" ? "success" : "danger"}>{user.status}</Badge></td>
              <td>{formatDate(user.created_at)}</td><td>{formatDate(user.last_login_at)}</td>
              <td>{user.role === "user" && <Button size="sm" variant={user.status === "active" ? "danger" : "secondary"}
                onClick={() => confirmAction({
                  title: `${user.status === "active" ? "禁用" : "启用"}账号 ${user.username}？`,
                  description: user.status === "active" ? "用户现有会话将失效，且无法继续访问工作区。" : "用户将恢复登录能力。",
                  confirmLabel: user.status === "active" ? "确认禁用" : "确认启用",
                }, () => run("user-status", () =>
                  updateUserStatus(user.id, user.status === "active" ? "disabled" : "active"),
                null, "用户状态已更新"))}>{user.status === "active" ? "禁用" : "启用"}</Button>}</td>
            </tr>)}
          </tbody></table></div>
        </section>
      )}

      {active === "audits" && (
        <section className="panel">
          <h2>审计日志</h2>
          <div className="table-scroll"><table className="file-table"><thead><tr>
            <th>时间</th><th>操作</th><th>状态</th><th>资源</th><th>脱敏详情</th>
          </tr></thead><tbody>
            {audits.map((item) => <tr key={item.id}><td>{formatDate(item.created_at)}</td>
              <td>{item.action}</td><td>{item.status}</td>
              <td>{item.resource_type || "—"} #{item.resource_id || "—"}</td>
              <td><details><summary>查看字段</summary><pre>{JSON.stringify(item.details, null, 2)}</pre></details></td></tr>)}
          </tbody></table></div>
        </section>
      )}

      <Dialog open={secret.visible} onClose={() => dispatchSecret({ type: "clear" })}
        title={secret.title} description="只显示一次。关闭后前端会立即清除，服务端不会再次返回明文。"
        footer={<Button variant="danger" onClick={() => dispatchSecret({ type: "clear" })}>关闭并清除</Button>}>
        <div className="one-time-secret">
          <code>{secret.value}</code>
          <Button onClick={async () => {
            await navigator.clipboard.writeText(secret.value);
            toast("已复制到剪贴板");
          }}>立即复制</Button>
        </div>
      </Dialog>
    </section>
  );
}

import { useEffect, useState } from "react";
import {
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

export default function Admin() {
  const [invites, setInvites] = useState([]);
  const [requests, setRequests] = useState([]);
  const [users, setUsers] = useState([]);
  const [audits, setAudits] = useState([]);
  const [oneTimeSecret, setOneTimeSecret] = useState(null);
  const [error, setError] = useState("");
  const [maxUses, setMaxUses] = useState("5");

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

  useEffect(() => {
    load();
  }, []);

  async function run(action, onSuccess) {
    try {
      const result = await action();
      onSuccess?.(result);
      await load();
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  return (
    <section className="page-section">
      <h2>管理员后台</h2>
      <p>这里只提供邀请码、密码重置、用户状态和审计日志的最小管理能力。</p>
      {error && <p className="form-message form-message--error">{error}</p>}
      {oneTimeSecret && (
        <div className="one-time-secret">
          <strong>{oneTimeSecret.title}（只显示一次，请立即复制）</strong>
          <code>{oneTimeSecret.value}</code>
          <button type="button" onClick={() => setOneTimeSecret(null)}>关闭并清除</button>
        </div>
      )}
      <AdminOperations />

      <section className="panel">
        <h3>邀请码管理</h3>
        <form className="inline-form" onSubmit={(event) => {
          event.preventDefault();
          run(
            () => createInviteCode({ max_uses: Number(maxUses) }),
            (result) => setOneTimeSecret({ title: "新邀请码", value: result.invite_code }),
          );
        }}>
          <label>最大使用次数<input type="number" min="1" value={maxUses}
            onChange={(event) => setMaxUses(event.target.value)} /></label>
          <button>创建邀请码</button>
        </form>
        <div className="table-scroll"><table className="file-table"><thead><tr>
          <th>提示</th><th>状态</th><th>使用</th><th>过期时间</th><th>操作</th>
        </tr></thead><tbody>
          {invites.map((invite) => <tr key={invite.id}>
            <td>{invite.code_hint}</td><td>{invite.status}</td>
            <td>{invite.used_count}/{invite.max_uses ?? "不限"}</td>
            <td>{invite.expires_at ? new Date(invite.expires_at).toLocaleString("zh-CN") : "不限"}</td>
            <td><div className="row-actions">
              <button type="button" onClick={() => run(() => updateInviteCode(
                invite.id,
                { status: invite.status === "disabled" ? "active" : "disabled" },
              ))}>{invite.status === "disabled" ? "启用" : "停用"}</button>
              <button type="button" onClick={() => run(
                () => rotateInviteCode(invite.id),
                (result) => setOneTimeSecret({ title: "轮换后的邀请码", value: result.invite_code }),
              )}>轮换</button>
            </div></td>
          </tr>)}
        </tbody></table></div>
      </section>

      <section className="panel">
        <h3>密码重置申请</h3>
        {requests.map((item) => <article className="task-card" key={item.id}>
          <p><strong>{item.username}</strong> · {new Date(item.requested_at).toLocaleString("zh-CN")}</p>
          <p>{item.request_note || "无申请说明"}</p>
          <div className="row-actions">
            <button type="button" onClick={() => run(() => rejectResetRequest(item.id, "管理员拒绝"))}>
              拒绝
            </button>
            <button type="button" onClick={() => run(
              () => issueTemporaryPassword(item.id, "管理员已线下核验"),
              (result) => setOneTimeSecret({
                title: `${item.username} 的临时密码`,
                value: result.temporary_password,
              }),
            )}>生成临时密码</button>
          </div>
        </article>)}
        {requests.length === 0 && <p className="table-state">暂无待处理申请。</p>}
      </section>

      <section className="panel">
        <h3>用户管理</h3>
        <div className="table-scroll"><table className="file-table"><thead><tr>
          <th>账号</th><th>角色</th><th>状态</th><th>创建时间</th><th>最后登录</th><th>操作</th>
        </tr></thead><tbody>
          {users.map((user) => <tr key={user.id}>
            <td>{user.username}</td><td>{user.role}</td><td>{user.status}</td>
            <td>{new Date(user.created_at).toLocaleString("zh-CN")}</td>
            <td>{user.last_login_at ? new Date(user.last_login_at).toLocaleString("zh-CN") : "-"}</td>
            <td>{user.role === "user" && <button type="button" onClick={() => run(
              () => updateUserStatus(user.id, user.status === "active" ? "disabled" : "active"),
            )}>{user.status === "active" ? "禁用" : "启用"}</button>}</td>
          </tr>)}
        </tbody></table></div>
      </section>

      <section className="panel">
        <h3>审计日志</h3>
        <div className="table-scroll"><table className="file-table"><thead><tr>
          <th>时间</th><th>操作</th><th>状态</th><th>资源</th><th>脱敏详情</th>
        </tr></thead><tbody>
          {audits.map((item) => <tr key={item.id}>
            <td>{new Date(item.created_at).toLocaleString("zh-CN")}</td>
            <td>{item.action}</td><td>{item.status}</td>
            <td>{item.resource_type || "-"} #{item.resource_id || "-"}</td>
            <td><code>{JSON.stringify(item.details)}</code></td>
          </tr>)}
        </tbody></table></div>
      </section>
    </section>
  );
}

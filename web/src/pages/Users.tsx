import { RefreshCw, ShieldCheck, UserRoundCog, UsersRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { ManagedUser, RuntimeConfig, UserRole } from "../types";

const roleLabels: Record<UserRole, string> = {
  member: "普通成员",
  lead: "负责人",
  admin: "管理员"
};

const roleDescriptions: Record<UserRole, string> = {
  member: "可查询知识与 Issue，默认不能执行写操作",
  lead: "可查询并创建 GitHub Issue",
  admin: "拥有完整业务工具权限"
};

function compactIdentity(value: string) {
  if (value.length <= 20) return value;
  return `${value.slice(0, 10)}…${value.slice(-6)}`;
}

export default function Users() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [memberCanCreate, setMemberCanCreate] = useState(false);

  function load() {
    setLoading(true);
    setError("");
    Promise.all([
      api<ManagedUser[]>("/api/v1/users"),
      api<RuntimeConfig>("/api/v1/config/runtime")
    ])
      .then(([nextUsers, runtime]) => { setUsers(nextUsers); setMemberCanCreate(runtime.github.member_can_create_issue); })
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const counts = useMemo(() => ({
    total: users.length,
    privileged: users.filter((user) => user.role !== "member").length
  }), [users]);

  async function changeRole(user: ManagedUser, role: UserRole) {
    if (role === user.role) return;
    setSavingId(user.id);
    setError("");
    try {
      const updated = await api<ManagedUser>(`/api/v1/users/${user.id}/role`, {
        method: "PUT",
        body: JSON.stringify({ role })
      });
      setUsers((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "角色更新失败");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="用户与权限"
        description="管理飞书身份映射和业务工具权限。角色调整会在用户下一条消息时生效。"
        action={<button className="secondary-button" onClick={load}><RefreshCw size={16} />刷新</button>}
      />
      {error && <ErrorBanner message={error} />}
      <section className="permission-summary">
        <div><UsersRound size={22} /><span><strong>{counts.total}</strong> 个已识别用户</span></div>
        <div><ShieldCheck size={22} /><span><strong>{counts.privileged}</strong> 个写操作授权用户</span></div>
        <p>权限在 Tool 执行前由服务端校验，模型无法绕过。</p>
      </section>
      <section className="panel permission-matrix">
        <div className="panel__header"><div><h2>Tool 权限矩阵</h2><p>实际权限由服务端 Tool Runner 在每次执行前校验</p></div><ShieldCheck size={20} /></div>
        <div className="table-scroll"><table><thead><tr><th>工具</th><th>普通成员</th><th>负责人</th><th>管理员</th></tr></thead><tbody>
          <tr><td><strong>knowledge_search</strong><span className="cell-sub">检索内部知识</span></td><td>允许</td><td>允许</td><td>允许</td></tr>
          <tr><td><strong>github_search / get / recent</strong><span className="cell-sub">读取 Issue、Commit 与 PR</span></td><td>允许</td><td>允许</td><td>允许</td></tr>
          <tr><td><strong>github_create_issue</strong><span className="cell-sub">创建真实 Issue；P0/P1 另需二次确认</span></td><td>{memberCanCreate ? "按配置允许" : "拒绝"}</td><td>允许</td><td>允许</td></tr>
          <tr><td><strong>管理后台配置</strong><span className="cell-sub">Agent、GitHub、知识库与角色</span></td><td>拒绝</td><td>拒绝</td><td>允许</td></tr>
        </tbody></table></div>
      </section>
      <section className="panel table-panel">
        {loading ? <LoadingBlock /> : !users.length ? (
          <EmptyState title="暂无用户" description="用户向飞书机器人发送消息后，身份会自动出现在这里。" />
        ) : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>用户</th><th>租户</th><th>渠道身份</th><th>消息数</th><th>当前角色</th><th>权限范围</th></tr></thead>
              <tbody>{users.map((user) => (
                <tr key={user.id}>
                  <td><div className="user-name"><UserRoundCog size={18} /><div><strong>用户 #{user.id}</strong><span>{compactIdentity(user.name)}</span></div></div></td>
                  <td>{user.tenant_key}</td>
                  <td>{user.channels.map((channel) => <span className="identity-chip" title={channel.external_user_id} key={`${channel.platform}-${channel.external_user_id}`}>{channel.platform} · {compactIdentity(channel.external_user_id)}</span>)}</td>
                  <td>{user.message_count}</td>
                  <td>
                    <select className="role-select" value={user.role} disabled={savingId === user.id} onChange={(event) => changeRole(user, event.target.value as UserRole)} aria-label={`修改用户 ${user.id} 的角色`}>
                      <option value="member">普通成员</option>
                      <option value="lead">负责人</option>
                      <option value="admin">管理员</option>
                    </select>
                  </td>
                  <td><div className="role-scope"><StatusBadge status={roleLabels[user.role]} /><span>{roleDescriptions[user.role]}</span></div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

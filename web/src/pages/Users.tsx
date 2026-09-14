import { Plus, RefreshCw, Save, ShieldCheck, Trash2, UserRoundCog, UsersRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { ManagedUser, OwnershipMapping, RuntimeConfig, TenantSummary, UserRole } from "../types";

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
  const [owners, setOwners] = useState<OwnershipMapping[]>([]);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [newOwner, setNewOwner] = useState({ tenant_id: 0, service: "", team: "", display_name: "", feishu_open_id: "", github_username: "", active: true });

  function load() {
    setLoading(true);
    setError("");
    Promise.all([
      api<ManagedUser[]>("/api/v1/users"),
      api<RuntimeConfig>("/api/v1/config/runtime"),
      api<OwnershipMapping[]>("/api/v1/ownership"),
      api<TenantSummary[]>("/api/v1/tenants")
    ])
      .then(([nextUsers, runtime, nextOwners, nextTenants]) => {
        setUsers(nextUsers); setMemberCanCreate(runtime.github.member_can_create_issue);
        setOwners(nextOwners); setTenants(nextTenants);
        setNewOwner((current) => ({ ...current, tenant_id: current.tenant_id || nextTenants[0]?.id || 0 }));
      })
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

  async function createOwner() {
    if (!newOwner.tenant_id || !newOwner.service.trim()) return;
    setError("");
    try {
      const created = await api<OwnershipMapping>("/api/v1/ownership", { method: "POST", body: JSON.stringify(newOwner) });
      setOwners((items) => [...items, created]);
      setNewOwner((current) => ({ ...current, service: "", team: "", display_name: "", feishu_open_id: "", github_username: "" }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "负责人映射创建失败"); }
  }

  async function saveOwner(owner: OwnershipMapping) {
    setSavingId(owner.id); setError("");
    try {
      const updated = await api<OwnershipMapping>(`/api/v1/ownership/${owner.id}`, {
        method: "PUT",
        body: JSON.stringify({ service: owner.service, team: owner.team, display_name: owner.display_name, feishu_open_id: owner.feishu_open_id, github_username: owner.github_username, active: owner.active })
      });
      setOwners((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "负责人映射保存失败"); }
    finally { setSavingId(null); }
  }

  async function deleteOwner(owner: OwnershipMapping) {
    if (!window.confirm(`确认删除 ${owner.service} 的负责人映射吗？`)) return;
    try {
      await api(`/api/v1/ownership/${owner.id}`, { method: "DELETE" });
      setOwners((items) => items.filter((item) => item.id !== owner.id));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "负责人映射删除失败"); }
  }

  function patchOwner(id: number, values: Partial<OwnershipMapping>) {
    setOwners((items) => items.map((item) => item.id === id ? { ...item, ...values } : item));
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
          <tr><td><strong>incident_save</strong><span className="cell-sub">显式沉淀结构化历史故障</span></td><td>允许</td><td>允许</td><td>允许</td></tr>
          <tr><td><strong>feishu_import_document</strong><span className="cell-sub">同步内部飞书文档</span></td><td>拒绝</td><td>允许</td><td>允许</td></tr>
          <tr><td><strong>管理后台配置</strong><span className="cell-sub">Agent、GitHub、知识库与角色</span></td><td>拒绝</td><td>拒绝</td><td>允许</td></tr>
        </tbody></table></div>
      </section>
      <section className="panel ownership-panel">
        <div className="panel__header"><div><h2>服务负责人映射</h2><p>Agent 会用这里的 GitHub 用户名处理“分配给后端负责人”等指令</p></div><UserRoundCog size={20} /></div>
        <div className="ownership-create">
          <select value={newOwner.tenant_id} onChange={(event) => setNewOwner({ ...newOwner, tenant_id: Number(event.target.value) })}>{tenants.map((tenant) => <option value={tenant.id} key={tenant.id}>{tenant.name}</option>)}</select>
          <input placeholder="服务/模块（必填）" value={newOwner.service} onChange={(event) => setNewOwner({ ...newOwner, service: event.target.value })} />
          <input placeholder="团队" value={newOwner.team} onChange={(event) => setNewOwner({ ...newOwner, team: event.target.value })} />
          <input placeholder="负责人姓名" value={newOwner.display_name} onChange={(event) => setNewOwner({ ...newOwner, display_name: event.target.value })} />
          <input placeholder="飞书 Open ID" value={newOwner.feishu_open_id} onChange={(event) => setNewOwner({ ...newOwner, feishu_open_id: event.target.value })} />
          <input placeholder="GitHub 用户名" value={newOwner.github_username} onChange={(event) => setNewOwner({ ...newOwner, github_username: event.target.value })} />
          <button className="primary-button compact" onClick={createOwner} disabled={!newOwner.tenant_id || !newOwner.service.trim()}><Plus size={16} />新增</button>
        </div>
        {!!owners.length && <div className="table-scroll"><table><thead><tr><th>租户</th><th>服务/模块</th><th>团队</th><th>负责人</th><th>飞书 Open ID</th><th>GitHub 用户名</th><th>启用</th><th className="align-right">操作</th></tr></thead><tbody>{owners.map((owner) => <tr key={owner.id}>
          <td>{owner.tenant_key}</td>
          <td><input value={owner.service} onChange={(event) => patchOwner(owner.id, { service: event.target.value })} /></td>
          <td><input value={owner.team} onChange={(event) => patchOwner(owner.id, { team: event.target.value })} /></td>
          <td><input value={owner.display_name} onChange={(event) => patchOwner(owner.id, { display_name: event.target.value })} /></td>
          <td><input value={owner.feishu_open_id} onChange={(event) => patchOwner(owner.id, { feishu_open_id: event.target.value })} /></td>
          <td><input value={owner.github_username} onChange={(event) => patchOwner(owner.id, { github_username: event.target.value })} /></td>
          <td><input type="checkbox" checked={owner.active} onChange={(event) => patchOwner(owner.id, { active: event.target.checked })} /></td>
          <td className="align-right"><button className="icon-button" title="保存" onClick={() => saveOwner(owner)} disabled={savingId === owner.id}><Save size={16} /></button><button className="icon-button icon-button--danger" title="删除" onClick={() => deleteOwner(owner)}><Trash2 size={16} /></button></td>
        </tr>)}</tbody></table></div>}
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

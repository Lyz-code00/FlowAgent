import { Bot, KeyRound, LockKeyhole } from "lucide-react";
import { FormEvent, useState } from "react";
import { api, clearToken, setToken } from "../api";

export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [token, updateToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    setError("");
    setToken(token.trim());
    try {
      await api("/api/v1/dashboard/metrics");
      onSuccess();
    } catch (reason) {
      clearToken();
      setError(reason instanceof Error ? reason.message : "无法登录");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-intro">
        <div className="login-brand"><Bot size={26} />FlowAgent</div>
        <div className="login-intro__content">
          <span>研发协同基础设施</span>
          <h1>把分散的研发信息<br />汇聚成可执行的工作流</h1>
          <p>统一管理飞书会话、Agent 执行轨迹、GitHub Issue 与内部知识库。</p>
          <div className="login-capabilities">
            <div><strong>可追踪</strong><span>每一步推理与工具调用均有记录</span></div>
            <div><strong>有边界</strong><span>租户隔离与服务端权限校验</span></div>
            <div><strong>可扩展</strong><span>渠道、模型与业务工具完全解耦</span></div>
          </div>
        </div>
        <small>FlowAgent Control Center · v0.5</small>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div className="login-card__icon"><LockKeyhole size={25} /></div>
          <h2>登录管理控制台</h2>
          <p>请输入服务端配置的管理员访问令牌。</p>
          <label htmlFor="admin-token">管理员令牌</label>
          <div className="input-with-icon">
            <KeyRound size={18} />
            <input
              id="admin-token"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(event) => updateToken(event.target.value)}
              placeholder="输入 X-FlowAgent-Admin-Token"
              autoFocus
            />
          </div>
          {error && <div className="login-error">{error}</div>}
          <button className="primary-button" disabled={loading || !token.trim()}>
            {loading ? "正在验证…" : "安全登录"}
          </button>
          <span className="login-card__note">令牌仅保存在当前浏览器会话中</span>
        </form>
      </section>
    </div>
  );
}

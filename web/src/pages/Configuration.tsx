import { Bot, BrainCircuit, CheckCircle2, Github, KeyRound, Network, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { AgentConfig, RuntimeConfig } from "../types";

export default function Configuration() {
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);
  const [agent, setAgent] = useState<AgentConfig | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      api<RuntimeConfig>("/api/v1/config/runtime"),
      api<AgentConfig>("/api/v1/agent/config"),
    ]).then(([nextRuntime, nextAgent]) => {
      setRuntime(nextRuntime);
      setAgent(nextAgent);
    }).catch((reason) => setError(reason.message));
  }, []);

  async function save() {
    if (!agent) return;
    setSaving(true);
    setSaved(false);
    setError("");
    try {
      const updated = await api<AgentConfig>("/api/v1/agent/config", {
        method: "PUT",
        body: JSON.stringify(agent),
      });
      setAgent(updated);
      setRuntime((current) => current ? {
        ...current,
        llm: { ...current.llm, model: updated.model, max_steps: updated.max_steps },
      } : current);
      setSaved(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "配置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="Agent 配置" description="调整模型、行为指令与工具能力；保存后对下一条消息立即生效。" />
      {error && <ErrorBanner message={error} />}
      {!runtime || !agent ? <LoadingBlock /> : <div className="config-grid">
        <section className="panel agent-editor">
          <div className="agent-editor__header">
            <div className="config-card__heading-icon"><BrainCircuit size={22} /></div>
            <div><h2>核心运行策略</h2><p>密钥仍由服务端安全管理，这里只保存非敏感配置。</p></div>
            {saved && <span className="save-confirmation"><CheckCircle2 size={15} />已生效</span>}
          </div>
          <div className="agent-form-grid">
            <label><span>Agent 名称</span><input value={agent.name} maxLength={255} onChange={(event) => setAgent({ ...agent, name: event.target.value })} /></label>
            <label><span>模型</span><input value={agent.model} maxLength={128} onChange={(event) => setAgent({ ...agent, model: event.target.value })} /><small>例如 deepseek-chat</small></label>
            <label><span>最大执行步数</span><input type="number" min={1} max={10} value={agent.max_steps} onChange={(event) => setAgent({ ...agent, max_steps: Number(event.target.value) })} /><small>建议 3–7，最大 10</small></label>
          </div>
          <label className="prompt-field"><span>System Prompt</span><textarea value={agent.system_prompt} minLength={20} maxLength={20000} rows={8} onChange={(event) => setAgent({ ...agent, system_prompt: event.target.value })} /><small>{agent.system_prompt.length} / 20000 字符</small></label>
          <div className="capability-row">
            <label className="capability-toggle"><input type="checkbox" checked={agent.knowledge_enabled} onChange={(event) => setAgent({ ...agent, knowledge_enabled: event.target.checked })} /><span className="toggle-track" /><span><strong>知识库检索</strong><small>允许 Agent 搜索当前租户文档</small></span></label>
            <label className="capability-toggle"><input type="checkbox" checked={agent.github_enabled} onChange={(event) => setAgent({ ...agent, github_enabled: event.target.checked })} /><span className="toggle-track" /><span><strong>GitHub 工具</strong><small>允许查询和按权限创建 Issue</small></span></label>
            <button className="primary-button compact" onClick={save} disabled={saving || agent.name.trim().length < 1 || agent.model.trim().length < 1 || agent.system_prompt.trim().length < 20 || agent.max_steps < 1 || agent.max_steps > 10}><Save size={16} />{saving ? "正在保存…" : "保存并生效"}</button>
          </div>
        </section>

        <section className="panel config-card"><div className="config-card__heading"><Github size={21} /><div><h2>GitHub</h2><p>Issue 查询与创建</p></div><StatusBadge status={runtime.github.configured} /></div><dl><div><dt>工具状态</dt><dd>{agent.github_enabled ? "已启用" : "已停用"}</dd></div><div><dt>仓库</dt><dd>{runtime.github.owner && runtime.github.repo ? `${runtime.github.owner}/${runtime.github.repo}` : "未设置"}</dd></div><div><dt>默认标签</dt><dd>{runtime.github.default_labels.join(", ") || "无"}</dd></div><div><dt>成员写权限</dt><dd>{runtime.github.member_can_create_issue ? "允许" : "禁止"}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><Network size={21} /><div><h2>知识检索</h2><p>Embedding 与召回</p></div><StatusBadge status={runtime.knowledge.external_embedding_configured ? "外部模型" : "本地模式"} /></div><dl><div><dt>工具状态</dt><dd>{agent.knowledge_enabled ? "已启用" : "已停用"}</dd></div><div><dt>Embedding 模型</dt><dd>{runtime.knowledge.embedding_model}</dd></div><div><dt>向量维度</dt><dd>{runtime.knowledge.dimensions}</dd></div><div><dt>默认 Top K</dt><dd>{runtime.knowledge.default_top_k}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><Bot size={21} /><div><h2>飞书渠道</h2><p>机器人消息入口</p></div><StatusBadge status={runtime.feishu.configured} /></div><dl><div><dt>运行环境</dt><dd>{runtime.environment}</dd></div><div><dt>事件入口</dt><dd>/api/v1/channels/feishu/events</dd></div><div><dt>上下文轮数</dt><dd>{runtime.llm.context_turns}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><BrainCircuit size={21} /><div><h2>当前模型</h2><p>下一次会话运行参数</p></div><StatusBadge status={runtime.llm.configured} /></div><dl><div><dt>模型</dt><dd>{agent.model}</dd></div><div><dt>最大步骤</dt><dd>{agent.max_steps}</dd></div><div><dt>Agent 名称</dt><dd>{agent.name}</dd></div></dl></section>
        <section className="panel security-note"><ShieldCheck size={24} /><div><h2>安全说明</h2><p>GitHub Token、飞书 Secret、LLM Key 与管理员令牌仅由服务端环境变量读取，任何配置接口都不会返回明文密钥。</p></div><KeyRound size={20} /></section>
      </div>}
    </>
  );
}

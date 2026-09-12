import { Bot, BrainCircuit, Github, KeyRound, Network, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { RuntimeConfig } from "../types";

export default function Configuration() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<RuntimeConfig>("/api/v1/config/runtime").then(setConfig).catch((reason) => setError(reason.message)); }, []);
  return (
    <>
      <PageHeader title="运行配置" description="安全查看当前生效的渠道、模型与业务工具配置。敏感值不会返回浏览器。" />
      {error && <ErrorBanner message={error} />}
      {!config ? <LoadingBlock /> : <div className="config-grid">
        <section className="panel config-card"><div className="config-card__heading"><BrainCircuit size={21} /><div><h2>Agent 模型</h2><p>推理与上下文策略</p></div><StatusBadge status={config.llm.configured} /></div><dl><div><dt>模型</dt><dd>{config.llm.model}</dd></div><div><dt>最大步骤</dt><dd>{config.llm.max_steps}</dd></div><div><dt>上下文轮数</dt><dd>{config.llm.context_turns}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><Github size={21} /><div><h2>GitHub</h2><p>Issue 查询与创建</p></div><StatusBadge status={config.github.configured} /></div><dl><div><dt>仓库</dt><dd>{config.github.owner && config.github.repo ? `${config.github.owner}/${config.github.repo}` : "未设置"}</dd></div><div><dt>默认标签</dt><dd>{config.github.default_labels.join(", ") || "无"}</dd></div><div><dt>成员写权限</dt><dd>{config.github.member_can_create_issue ? "允许" : "禁止"}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><Network size={21} /><div><h2>知识检索</h2><p>Embedding 与召回</p></div><StatusBadge status={config.knowledge.external_embedding_configured ? "外部模型" : "本地模式"} /></div><dl><div><dt>Embedding 模型</dt><dd>{config.knowledge.embedding_model}</dd></div><div><dt>向量维度</dt><dd>{config.knowledge.dimensions}</dd></div><div><dt>默认 Top K</dt><dd>{config.knowledge.default_top_k}</dd></div></dl></section>
        <section className="panel config-card"><div className="config-card__heading"><Bot size={21} /><div><h2>飞书渠道</h2><p>机器人消息入口</p></div><StatusBadge status={config.feishu.configured} /></div><dl><div><dt>运行环境</dt><dd>{config.environment}</dd></div><div><dt>事件入口</dt><dd>/api/v1/channels/feishu/events</dd></div><div><dt>消息类型</dt><dd>文本消息</dd></div></dl></section>
        <section className="panel security-note"><ShieldCheck size={24} /><div><h2>安全说明</h2><p>GitHub Token、飞书 Secret、LLM Key 与管理员令牌仅由服务端环境变量读取，运行配置接口不会返回任何明文密钥。</p></div><KeyRound size={20} /></section>
      </div>}
    </>
  );
}

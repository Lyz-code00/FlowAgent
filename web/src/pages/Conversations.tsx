import { ArrowLeft, Clock3, MessageSquareText, RefreshCw, Search, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { Conversation, ConversationDetail, TraceRun } from "../types";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function Conversations() {
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<ConversationDetail | null>(null);
  const [traces, setTraces] = useState<TraceRun[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  function load() {
    setLoading(true);
    api<Conversation[]>("/api/v1/conversations")
      .then(setItems)
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const filtered = useMemo(() => items.filter((item) =>
    [item.tenant_key, item.external_conversation_id, item.last_message ?? ""].some((value) => value.toLowerCase().includes(query.toLowerCase()))
  ), [items, query]);

  async function openConversation(id: number) {
    setDetailLoading(true);
    setError("");
    try {
      const [detail, traceData] = await Promise.all([
        api<ConversationDetail>(`/api/v1/conversations/${id}`),
        api<TraceRun[]>(`/api/v1/conversations/${id}/traces`)
      ]);
      setSelected(detail);
      setTraces(traceData);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载会话失败");
    } finally {
      setDetailLoading(false);
    }
  }

  if (selected || detailLoading) {
    return (
      <>
        <button className="text-button back-button" onClick={() => { setSelected(null); setTraces([]); }}><ArrowLeft size={17} />返回会话列表</button>
        {detailLoading || !selected ? <LoadingBlock /> : (
          <>
            <PageHeader title={`会话 #${selected.id}`} description={`${selected.platform.toUpperCase()} · ${selected.tenant_key} · ${selected.external_conversation_id}`} />
            {error && <ErrorBanner message={error} />}
            <div className="conversation-layout">
              <section className="panel message-panel">
                <div className="panel__header"><div><h2>消息记录</h2><p>{selected.messages.length} 条消息</p></div><MessageSquareText size={20} /></div>
                <div className="message-list">
                  {selected.messages.map((message) => (
                    <article className={`message message--${message.role}`} key={message.id}>
                      <div className="message__meta"><strong>{message.role === "user" ? "用户" : "FlowAgent"}</strong><span>{formatTime(message.created_at)}</span></div>
                      <p>{message.content}</p>
                    </article>
                  ))}
                </div>
              </section>
              <section className="panel trace-panel">
                <div className="panel__header"><div><h2>Agent Trace</h2><p>{traces.length} 次运行</p></div><Workflow size={20} /></div>
                {!traces.length ? <EmptyState title="暂无 Trace" description="该会话还没有 Agent 运行记录。" /> : traces.map((run) => (
                  <article className="trace-run" key={run.id}>
                    <div className="trace-run__header"><div><strong>Run #{run.id}</strong><span>{run.model}</span></div><StatusBadge status={run.status} /></div>
                    <div className="trace-run__meta"><Clock3 size={14} />{run.latency_ms ?? 0} ms · {run.steps.length} steps</div>
                    <div className="trace-steps">
                      {run.steps.map((step) => (
                        <div className="trace-step" key={step.id}>
                          <i /><div><strong>Step {step.step_no} · {step.name ?? step.kind}</strong><span>{step.kind.toUpperCase()} · {step.latency_ms ?? 0} ms</span>{step.error && <p>{step.error}</p>}</div><StatusBadge status={step.status} />
                        </div>
                      ))}
                    </div>
                  </article>
                ))}
              </section>
            </div>
          </>
        )}
      </>
    );
  }

  return (
    <>
      <PageHeader title="会话与 Trace" description="查看用户对话、模型推理和每一次工具执行。" action={<button className="secondary-button" onClick={load}><RefreshCw size={16} />刷新</button>} />
      {error && <ErrorBanner message={error} />}
      <section className="panel table-panel">
        <div className="table-toolbar"><div className="search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索租户、会话 ID 或消息" /></div><span>共 {filtered.length} 个会话</span></div>
        {loading ? <LoadingBlock /> : !filtered.length ? <EmptyState title="暂无会话" description="飞书消息进入系统后，会话会显示在这里。" /> : (
          <div className="table-scroll"><table><thead><tr><th>会话</th><th>渠道</th><th>租户</th><th>消息数</th><th>最近消息</th><th>更新时间</th></tr></thead><tbody>
            {filtered.map((item) => <tr key={item.id} onClick={() => openConversation(item.id)} tabIndex={0}><td><strong>#{item.id}</strong><span className="cell-sub">{item.external_conversation_id}</span></td><td><span className="channel-badge">{item.platform}</span></td><td>{item.tenant_key}</td><td>{item.message_count}</td><td className="truncate-cell">{item.last_message ?? "—"}</td><td>{formatTime(item.updated_at)}</td></tr>)}
          </tbody></table></div>
        )}
      </section>
    </>
  );
}

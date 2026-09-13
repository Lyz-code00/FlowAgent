import { ArrowLeft, Clock3, MessageSquareText, RefreshCw, Search, ThumbsDown, ThumbsUp, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, getToken } from "../api";
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

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    let buffer = "";
    async function connect() {
      try {
        const response = await fetch(`/api/v1/conversations/${selected!.id}/traces/stream`, {
          headers: { "X-FlowAgent-Admin-Token": getToken() },
          signal: controller.signal
        });
        if (!response.ok || !response.body) throw new Error(`Trace 实时连接失败 (${response.status})`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const data = frame.split("\n").find((line) => line.startsWith("data: "));
            if (data) setTraces(JSON.parse(data.slice(6)) as TraceRun[]);
          }
        }
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Trace 实时连接失败");
      }
    }
    connect();
    return () => controller.abort();
  }, [selected?.id]);

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

  async function rateMessage(messageId: number, rating: "positive" | "negative") {
    const reason = rating === "negative" ? window.prompt("请简要说明这条回复哪里需要改进（可留空）") : null;
    if (rating === "negative" && reason === null) return;
    setError("");
    try {
      const feedback = await api<{ id: number; rating: "positive" | "negative"; reason: string | null }>(`/api/v1/messages/${messageId}/feedback`, {
        method: "PUT",
        body: JSON.stringify({ rating, reason: reason || null })
      });
      setSelected((current) => current ? {
        ...current,
        messages: current.messages.map((message) => message.id === messageId ? { ...message, feedback } : message)
      } : current);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "反馈保存失败");
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
                      {message.role === "assistant" && (
                        <div className="message__feedback" aria-label="回复反馈">
                          <button className={message.feedback?.rating === "positive" ? "active" : ""} onClick={() => rateMessage(message.id, "positive")} title="有帮助"><ThumbsUp size={14} /></button>
                          <button className={message.feedback?.rating === "negative" ? "active negative" : ""} onClick={() => rateMessage(message.id, "negative")} title="需要改进"><ThumbsDown size={14} /></button>
                          {message.feedback && <span>已记录</span>}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              </section>
              <section className="panel trace-panel">
                <div className="panel__header"><div><h2>Agent Trace</h2><p>{traces.length} 次运行 · 实时更新</p></div><div className="live-badge"><i />LIVE <Workflow size={20} /></div></div>
                {!traces.length ? <EmptyState title="暂无 Trace" description="该会话还没有 Agent 运行记录。" /> : traces.map((run) => (
                  <article className="trace-run" key={run.id}>
                    <div className="trace-run__header"><div><strong>Run #{run.id}</strong><span>{run.model}</span></div><StatusBadge status={run.status} /></div>
                    <div className="trace-run__meta"><Clock3 size={14} />{run.latency_ms ?? 0} ms · {run.steps.length} steps</div>
                    {run.external_url && (
                      <div className="trace-run__meta"><span>关联 Issue：</span><a href={run.external_url} target="_blank" rel="noreferrer">#{run.external_id} ↗</a></div>
                    )}
                    <div className="trace-steps">
                      {run.steps.map((step) => (
                        <div className="trace-step" key={step.id}>
                          <i /><div><strong>Step {step.step_no} · {step.name ?? step.kind}</strong><span>{step.kind.toUpperCase()} · {step.latency_ms ?? 0} ms</span>{step.error && <p>{step.error}</p>}
                            {(step.input != null || step.output != null) && <details className="trace-payload"><summary>查看参数与结果</summary>{step.input != null && <><b>输入参数</b><pre>{JSON.stringify(step.input, null, 2)}</pre></>}{step.output != null && <><b>执行结果</b><pre>{JSON.stringify(step.output, null, 2)}</pre></>}</details>}
                          </div><StatusBadge status={step.status} />
                        </div>
                      ))}
                    </div>
                    {run.final_answer && <details className="trace-answer"><summary>查看最终答案</summary><p>{run.final_answer}</p></details>}
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

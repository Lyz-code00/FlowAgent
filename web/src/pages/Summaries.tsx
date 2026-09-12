import { Bug, CalendarClock, CheckCircle2, ClipboardList, Edit3, RefreshCw, Save, UserRound, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { ConversationSummary, SummaryActionItem } from "../types";

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

export default function Summaries() {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [editing, setEditing] = useState<ConversationSummary | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    setError("");
    api<ConversationSummary[]>("/api/v1/summaries").then(setItems).catch((reason) => setError(reason.message));
  }

  useEffect(load, []);

  function updateAction(index: number, patch: Partial<SummaryActionItem>) {
    if (!editing) return;
    setEditing({ ...editing, action_items: editing.action_items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) });
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError("");
    try {
      const updated = await api<ConversationSummary>(`/api/v1/summaries/${editing.id}`, {
        method: "PUT",
        body: JSON.stringify({ summary: editing.summary, decisions: editing.decisions, bugs: editing.bugs, action_items: editing.action_items }),
      });
      setItems((current) => current?.map((item) => item.id === editing.id ? { ...item, ...updated } : item) ?? []);
      setEditing(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader title="讨论沉淀" description="查看由显式指令生成的群聊总结、决策、Bug 和待办。" action={<button className="secondary-button" onClick={load}><RefreshCw size={16} />刷新</button>} />
      {error && <ErrorBanner message={error} />}
      {!items ? <LoadingBlock /> : items.length === 0 ? <section className="panel"><EmptyState title="暂无讨论总结" description="在飞书中明确要求 FlowAgent 总结讨论并提取待办后，结果会显示在这里。" /></section> : <div className="summary-list">
        {items.map((item) => <section className="panel summary-card" key={item.id}>
          <header><div className="summary-card__icon"><ClipboardList size={19} /></div><div><strong>{item.tenant_key}</strong><span>会话 {item.external_conversation_id} · {new Date(item.updated_at).toLocaleString("zh-CN")}</span></div><button className="secondary-button" onClick={() => setEditing(structuredClone(item))}><Edit3 size={15} />编辑</button></header>
          <p>{item.summary}</p>
          <div className="summary-columns">
            <div><h3><CheckCircle2 size={15} />决策</h3>{item.decisions.length ? <ul>{item.decisions.map((decision) => <li key={decision}>{decision}</li>)}</ul> : <span>未识别到明确决策</span>}</div>
            <div><h3><Bug size={15} />Bug</h3>{item.bugs.length ? <ul>{item.bugs.map((bug) => <li key={bug}>{bug}</li>)}</ul> : <span>未识别到 Bug</span>}</div>
          </div>
          <div className="todo-list"><h3>待办事项 <StatusBadge status={`${item.action_items.length} 项`} /></h3>{item.action_items.map((action, index) => <div className="todo-item" key={`${action.content}-${index}`}><div><strong>{action.content}</strong><span><UserRound size={13} />{action.owner || "未指定负责人"}<CalendarClock size={13} />{action.due_date || "未指定截止时间"}</span></div><StatusBadge status={action.status === "done" ? "已完成" : action.priority || "待处理"} /></div>)}</div>
        </section>)}
      </div>}

      {editing && <div className="modal-backdrop" role="presentation"><section className="panel summary-editor" role="dialog" aria-modal="true" aria-label="编辑讨论总结"><header><div><h2>编辑讨论总结</h2><p>修改后的内容会作为团队确认版本保存。</p></div><button className="icon-button" onClick={() => setEditing(null)} aria-label="关闭"><X size={18} /></button></header><div className="summary-editor__body">
        <label><span>摘要</span><textarea rows={4} value={editing.summary} onChange={(event) => setEditing({ ...editing, summary: event.target.value })} /></label>
        <div className="summary-editor__columns"><label><span>决策（每行一项）</span><textarea rows={5} value={editing.decisions.join("\n")} onChange={(event) => setEditing({ ...editing, decisions: lines(event.target.value) })} /></label><label><span>Bug（每行一项）</span><textarea rows={5} value={editing.bugs.join("\n")} onChange={(event) => setEditing({ ...editing, bugs: lines(event.target.value) })} /></label></div>
        <div className="action-editor"><span>待办事项</span>{editing.action_items.map((action, index) => <div className="action-editor__row" key={index}><input value={action.content} onChange={(event) => updateAction(index, { content: event.target.value })} placeholder="待办内容" /><input value={action.owner || ""} onChange={(event) => updateAction(index, { owner: event.target.value || null })} placeholder="负责人" /><input value={action.due_date || ""} onChange={(event) => updateAction(index, { due_date: event.target.value || null })} placeholder="截止时间" /><select value={action.status} onChange={(event) => updateAction(index, { status: event.target.value })}><option value="pending">待处理</option><option value="in_progress">进行中</option><option value="done">已完成</option></select></div>)}</div>
      </div><footer><button className="secondary-button" onClick={() => setEditing(null)}>取消</button><button className="primary-button compact" onClick={save} disabled={saving || !editing.summary.trim()}><Save size={16} />{saving ? "保存中…" : "保存修改"}</button></footer></section></div>}
    </>
  );
}

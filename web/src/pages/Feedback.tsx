import { MessageCircleWarning, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader } from "../components/Common";
import type { FeedbackRecord } from "../types";

type Filter = "all" | "positive" | "negative";

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

export default function Feedback() {
  const [items, setItems] = useState<FeedbackRecord[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function load(nextFilter: Filter = filter) {
    setLoading(true);
    setError("");
    const query = nextFilter === "all" ? "" : `?rating=${nextFilter}`;
    api<FeedbackRecord[]>(`/api/v1/feedback${query}`)
      .then(setItems)
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(filter); }, [filter]);

  return (
    <>
      <PageHeader title="反馈与 Bad Case" description="集中查看用户对 Agent 回复的评价，持续优化提示词、知识库和工具策略。" action={<button className="secondary-button" onClick={() => load()}><RefreshCw size={16} />刷新</button>} />
      {error && <ErrorBanner message={error} />}
      <section className="panel feedback-panel">
        <div className="feedback-toolbar">
          {(["all", "positive", "negative"] as Filter[]).map((value) => (
            <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>
              {value === "all" ? "全部" : value === "positive" ? "正向反馈" : "Bad Case"}
            </button>
          ))}
          <span>共 {items.length} 条</span>
        </div>
        {loading ? <LoadingBlock /> : !items.length ? <EmptyState title="暂无反馈" description="在会话详情中评价 Agent 回复后，记录会显示在这里。" /> : (
          <div className="feedback-list">
            {items.map((item) => (
              <article className={`feedback-card feedback-card--${item.rating}`} key={item.id}>
                <div className="feedback-card__icon">{item.rating === "positive" ? <ThumbsUp size={18} /> : <MessageCircleWarning size={18} />}</div>
                <div>
                  <header><strong>{item.rating === "positive" ? "正向反馈" : "Bad Case"}</strong><span>会话 #{item.conversation_id} · {item.tenant_key} · {formatTime(item.updated_at)}</span></header>
                  <p>{item.content}</p>
                  {item.reason && <blockquote>{item.reason}</blockquote>}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </>
  );
}

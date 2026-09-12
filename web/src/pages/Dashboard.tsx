import { Activity, BookOpenCheck, Bot, CircleAlert, GitPullRequest, MessagesSquare, Timer, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBanner, LoadingBlock, PageHeader } from "../components/Common";
import type { Metrics } from "../types";

const cards = [
  ["conversations_today", "今日会话", "个活跃协作会话", MessagesSquare],
  ["agent_runs_today", "Agent 调用", "次智能处理", Bot],
  ["tool_calls_today", "Tool 调用", "次外部能力执行", Wrench],
  ["knowledge_searches_today", "知识检索", "次内部证据查询", BookOpenCheck],
  ["github_issues_created_today", "Issue 创建", "个研发任务闭环", GitPullRequest],
  ["failed_calls_today", "失败调用", "项需要关注", CircleAlert]
] as const;

export default function Dashboard() {
  const [data, setData] = useState<Metrics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Metrics>("/api/v1/dashboard/metrics").then(setData).catch((reason) => setError(reason.message));
  }, []);

  return (
    <>
      <PageHeader title="运营概览" description="掌握今日 Agent 运行状态、业务闭环和异常情况。" />
      {error && <ErrorBanner message={error} />}
      {!data ? <LoadingBlock /> : (
        <>
          <section className="metric-grid">
            {cards.map(([key, title, note, Icon]) => (
              <article className="metric-card" key={key}>
                <div className={`metric-card__icon ${key === "failed_calls_today" ? "metric-card__icon--alert" : ""}`}><Icon size={21} /></div>
                <span>{title}</span>
                <strong>{data[key].toLocaleString()}</strong>
                <small>{note}</small>
              </article>
            ))}
          </section>
          <section className="dashboard-grid">
            <article className="panel service-panel">
              <div className="panel__header"><div><h2>服务健康度</h2><p>当前核心链路概况</p></div><span className="live-badge"><i />实时</span></div>
              <div className="service-score">
                <div className="service-score__ring"><Activity size={28} /><strong>{data.failed_calls_today === 0 ? "稳定" : "关注"}</strong></div>
                <div><h3>{data.failed_calls_today === 0 ? "所有已记录调用运行正常" : "检测到失败调用"}</h3><p>失败调用 {data.failed_calls_today} 次，建议前往会话 Trace 查看具体步骤。</p></div>
              </div>
            </article>
            <article className="panel latency-panel">
              <div className="panel__header"><div><h2>平均响应时间</h2><p>今日已完成 Agent Run</p></div><Timer size={20} /></div>
              <div className="latency-value"><strong>{data.average_response_ms.toLocaleString()}</strong><span>ms</span></div>
              <div className="latency-track"><i style={{ width: `${Math.min(100, data.average_response_ms / 50)}%` }} /></div>
              <p>{data.average_response_ms <= 3000 ? "处于首版目标范围内" : "高于 3 秒目标，建议检查外部 Tool 耗时"}</p>
            </article>
          </section>
        </>
      )}
    </>
  );
}

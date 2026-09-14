import { BarChart3, CheckCircle2, Clock3, DatabaseZap, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, LoadingBlock, PageHeader } from "../components/Common";
import type { QualityBenchmarkResponse, QualityMetric, QualityMetricsResponse } from "../types";

const failureLabels: Record<string, string> = {
  timeout: "执行超时",
  permission: "权限拒绝",
  rate_limit: "接口限流",
  validation: "参数校验",
  configuration: "配置缺失",
  confirmation: "确认失败",
  in_progress: "操作进行中",
  external_api: "外部接口",
  execution: "执行异常"
};

const stageLabels = { agent_run: "端到端 Agent Run", llm_step: "LLM 推理", tool_step: "Tool 执行" } as const;

function MetricCard({ metric }: { metric: QualityMetric }) {
  const measured = metric.value !== null;
  const sample = metric.denominator !== null ? `${metric.numerator ?? "—"} / ${metric.denominator}` : measured ? "已计算" : "无样本";
  return (
    <article className={`quality-card ${measured ? "" : "quality-card--empty"}`}>
      <div className="quality-card__top">
        <span className={`quality-source quality-source--${metric.source}`}>{metric.source === "production" ? "线上观测" : "离线基准"}</span>
        {measured ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}
      </div>
      <h2>{metric.label}</h2>
      <div className="quality-card__value"><strong>{metric.value === null ? "待积累" : metric.value.toLocaleString()}</strong>{metric.value !== null && <span>{metric.unit}</span>}</div>
      <p>{metric.note}</p>
      <small>样本：{sample}</small>
    </article>
  );
}

export default function Quality() {
  const [days, setDays] = useState(30);
  const [online, setOnline] = useState<QualityMetricsResponse | null>(null);
  const [benchmark, setBenchmark] = useState<QualityBenchmarkResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [onlineResult, benchmarkResult] = await Promise.all([
        api<QualityMetricsResponse>(`/api/v1/quality/metrics?days=${days}`),
        api<QualityBenchmarkResponse>("/api/v1/quality/benchmark")
      ]);
      setOnline(onlineResult); setBenchmark(benchmarkResult);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "量化数据加载失败"); }
    finally { setLoading(false); }
  }, [days]);
  useEffect(() => { void load(); }, [load]);
  const metrics = useMemo(() => [...(online?.metrics ?? []), ...(benchmark?.metrics ?? [])], [online, benchmark]);
  const measuredCount = metrics.filter((item) => item.value !== null).length;
  return (
    <>
      <PageHeader title="量化评估" description="用可复算的生产数据和离线基准判断 FlowAgent 是否达到收尾标准。" action={<div className="quality-actions"><select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option><option value={90}>最近 90 天</option></select><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>} />
      {error && <ErrorBanner message={error} />}
      {loading ? <LoadingBlock /> : <>
        <section className="quality-summary panel"><div><BarChart3 size={21} /><span><strong>{measuredCount}</strong> 项已有结果</span></div><div><DatabaseZap size={21} /><span>线上窗口 <strong>{online?.window_days ?? days}</strong> 天</span></div><p>“待积累”表示样本不足；离线基准不会冒充生产效果。</p></section>
        <section className="quality-grid">{metrics.map((metric) => <MetricCard key={metric.key} metric={metric} />)}</section>
        <section className="quality-analysis-grid">
          <article className="panel quality-detail">
            <div className="panel__header"><div><h2>按 Tool 拆分</h2><p>失败优先排序，快速定位稳定性短板</p></div></div>
            <div className="table-wrap"><table><thead><tr><th>Tool</th><th>成功/调用</th><th>成功率</th><th>平均</th><th>P95</th></tr></thead><tbody>
              {(online?.tool_breakdown ?? []).map((item) => <tr key={item.tool_name}><td><strong>{item.tool_name}</strong></td><td>{item.succeeded}/{item.attempts}</td><td>{item.success_rate === null ? "—" : `${item.success_rate}%`}</td><td>{item.average_latency_ms === null ? "—" : `${item.average_latency_ms} ms`}</td><td>{item.p95_latency_ms === null ? "—" : `${item.p95_latency_ms} ms`}</td></tr>)}
              {!online?.tool_breakdown.length && <tr><td colSpan={5}>当前窗口暂无 Tool 样本</td></tr>}
            </tbody></table></div>
          </article>
          <article className="panel quality-detail">
            <div className="panel__header"><div><h2>失败原因</h2><p>按错误类型聚合，不展示密钥和完整请求</p></div></div>
            <div className="quality-failures">{(online?.failure_categories ?? []).map((item) => <div key={item.category}><span className="quality-failure-count">{item.count}</span><div><strong>{failureLabels[item.category] ?? item.category}</strong><p>{item.tools.join("、")}</p>{item.examples[0] && <small>{item.examples[0]}</small>}</div></div>)}{!online?.failure_categories.length && <p className="quality-empty-note">当前窗口没有失败调用</p>}</div>
          </article>
        </section>
        <section className="panel quality-detail">
          <div className="panel__header"><div><h2>耗时拆分</h2><p>判断慢请求来自模型、Tool 还是整体编排</p></div></div>
          <div className="quality-latency-row">{(online?.latency_breakdown ?? []).map((item) => <div key={item.stage}><span>{stageLabels[item.stage]}</span><strong>{item.p95_ms === null ? "待积累" : `${item.p95_ms.toLocaleString()} ms`}</strong><small>平均 {item.average_ms === null ? "—" : `${item.average_ms.toLocaleString()} ms`} · {item.samples} 个样本</small></div>)}</div>
        </section>
        {benchmark?.rag_cases && <section className="panel quality-detail"><div className="panel__header"><div><h2>RAG Recall@5 明细</h2><p>{benchmark.suite} · 20 条可复跑问题集</p></div></div><div className="table-wrap"><table><thead><tr><th>问题</th><th>预期文档</th><th>Top 5</th><th>结果</th></tr></thead><tbody>{benchmark.rag_cases.map((item) => <tr key={item.query}><td>{item.query}</td><td>文档 {item.expected_document}</td><td>{item.top_k.join(", ")}</td><td><span className={`status ${item.passed ? "status--success" : "status--danger"}`}>{item.passed ? "命中" : "未命中"}</span></td></tr>)}</tbody></table></div></section>}
      </>}
    </>
  );
}

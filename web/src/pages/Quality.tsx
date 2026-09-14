import { BarChart3, CheckCircle2, Clock3, DatabaseZap, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ErrorBanner, LoadingBlock, PageHeader } from "../components/Common";
import type { QualityBenchmarkResponse, QualityMetric, QualityMetricsResponse } from "../types";

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
        {benchmark?.rag_cases && <section className="panel quality-detail"><div className="panel__header"><div><h2>RAG Recall@5 明细</h2><p>{benchmark.suite} · 20 条可复跑问题集</p></div></div><div className="table-wrap"><table><thead><tr><th>问题</th><th>预期文档</th><th>Top 5</th><th>结果</th></tr></thead><tbody>{benchmark.rag_cases.map((item) => <tr key={item.query}><td>{item.query}</td><td>文档 {item.expected_document}</td><td>{item.top_k.join(", ")}</td><td><span className={`status ${item.passed ? "status--success" : "status--danger"}`}>{item.passed ? "命中" : "未命中"}</span></td></tr>)}</tbody></table></div></section>}
      </>}
    </>
  );
}

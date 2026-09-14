import { AlertTriangle, ExternalLink, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { IncidentRecord } from "../types";

export default function Incidents() {
  const [items, setItems] = useState<IncidentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  function load() {
    setLoading(true); setError("");
    api<IncidentRecord[]>("/api/v1/incidents")
      .then(setItems)
      .catch((reason) => setError(reason.message))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  return <>
    <PageHeader title="Incident 故障库" description="查看由 Agent 显式沉淀的历史故障、证据与 Root Cause。" action={<button className="secondary-button" onClick={load}><RefreshCw size={16} />刷新</button>} />
    {error && <ErrorBanner message={error} />}
    <section className="panel table-panel">
      {loading ? <LoadingBlock /> : !items.length ? <EmptyState title="暂无 Incident" description="在飞书中明确要求 FlowAgent 记录故障后，结构化记录会出现在这里。" /> : <div className="table-scroll"><table><thead><tr><th>编号</th><th>故障</th><th>级别</th><th>状态</th><th>服务 / 错误码</th><th>证据</th><th>更新时间</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}>
        <td><strong>{item.incident_key}</strong></td>
        <td><div className="incident-title"><AlertTriangle size={17} /><div><strong>{item.title}</strong><span>{item.summary}</span>{item.root_cause && <span>Root Cause：{item.root_cause}</span>}</div></div></td>
        <td><StatusBadge status={item.severity} /></td>
        <td><StatusBadge status={item.status} /></td>
        <td>{item.service || "—"}<span className="cell-sub">{item.error_code || "无错误码"}</span></td>
        <td>{item.evidence.length} 条{item.source_url && <a className="issue-link" href={item.source_url} target="_blank" rel="noreferrer"><ExternalLink size={13} />来源</a>}</td>
        <td>{new Date(item.updated_at).toLocaleString("zh-CN")}</td>
      </tr>)}</tbody></table></div>}
    </section>
  </>;
}

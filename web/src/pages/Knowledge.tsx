import { FileText, Link2, Plus, RefreshCw, Trash2, UploadCloud } from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { KnowledgeDocument, TenantSummary } from "../types";

export default function Knowledge() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [tenantKey, setTenantKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [feishuUrl, setFeishuUrl] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  function endpoint(path = "") {
    return `/api/v1/knowledge/documents${path}?tenant_key=${encodeURIComponent(tenantKey)}`;
  }

  function load(selectedTenant = tenantKey) {
    if (!selectedTenant) return;
    setLoading(true);
    api<KnowledgeDocument[]>(`/api/v1/knowledge/documents?tenant_key=${encodeURIComponent(selectedTenant)}`).then(setDocuments).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }
  useEffect(() => {
    api<TenantSummary[]>("/api/v1/tenants")
      .then((items) => {
        setTenants(items);
        const selected = items[0]?.external_key ?? "";
        setTenantKey(selected);
        if (selected) load(selected);
        else setLoading(false);
      })
      .catch((reason) => { setError(reason.message); setLoading(false); });
  }, []);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true); setError("");
    const body = new FormData(); body.append("file", file);
    try { await api(endpoint(), { method: "POST", body }); load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "上传失败"); }
    finally { setUploading(false); event.target.value = ""; }
  }

  async function remove(document: KnowledgeDocument) {
    if (!window.confirm(`确认删除“${document.title}”及其全部索引吗？`)) return;
    try { await api(endpoint(`/${document.id}`), { method: "DELETE" }); setDocuments((items) => items.filter((item) => item.id !== document.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); }
  }

  async function importFeishu() {
    const tenant = tenants.find((item) => item.external_key === tenantKey);
    if (!tenant || !feishuUrl.trim()) return;
    setImporting(true); setError("");
    try {
      await api("/api/v1/knowledge/feishu/import", {
        method: "POST",
        body: JSON.stringify({ tenant_id: tenant.id, url: feishuUrl.trim() })
      });
      setFeishuUrl(""); load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "飞书文档同步失败");
    } finally { setImporting(false); }
  }

  return (
    <>
      <PageHeader title="知识库" description="管理研发规范、接口文档与历史故障资料，为 Agent 提供可信依据。" action={<><select className="tenant-select" value={tenantKey} onChange={(event) => { setTenantKey(event.target.value); load(event.target.value); }} aria-label="选择知识库租户">{tenants.map((tenant) => <option key={tenant.id} value={tenant.external_key}>{tenant.name} · {tenant.user_count} 用户</option>)}</select><input ref={input} type="file" accept=".md,.markdown,.txt,.pdf" hidden onChange={upload} /><button className="primary-button compact" onClick={() => input.current?.click()} disabled={uploading || !tenantKey}><Plus size={17} />{uploading ? "正在索引…" : "上传文档"}</button></>} />
      {error && <ErrorBanner message={error} />}
      <section className="knowledge-summary">
        <div><UploadCloud size={23} /><span><strong>{documents.length}</strong> 份知识文档</span></div>
        <div><FileText size={23} /><span><strong>{documents.reduce((sum, item) => sum + item.chunk_count, 0)}</strong> 个可检索分块</span></div>
        <button className="text-button" onClick={() => load()} disabled={!tenantKey}><RefreshCw size={16} />刷新状态</button>
      </section>
      <section className="panel feishu-import-panel">
        <div><Link2 size={20} /><div><h2>同步飞书文档</h2><p>支持飞书新版 docx 与 Wiki 链接；重复同步会安全替换旧版本。</p></div></div>
        <input value={feishuUrl} onChange={(event) => setFeishuUrl(event.target.value)} placeholder="https://example.feishu.cn/wiki/..." />
        <button className="primary-button compact" onClick={importFeishu} disabled={importing || !tenantKey || !feishuUrl.trim()}>{importing ? "同步中…" : "同步并索引"}</button>
      </section>
      <section className="panel table-panel">
        {loading ? <LoadingBlock /> : !documents.length ? <EmptyState title="知识库还是空的" description="上传 Markdown、TXT 或文本型 PDF，FlowAgent 就能基于内部证据回答。" /> : (
          <div className="table-scroll"><table><thead><tr><th>文档</th><th>状态</th><th>分块数</th><th>来源</th><th className="align-right">操作</th></tr></thead><tbody>
            {documents.map((document) => <tr key={document.id}><td><div className="document-name"><FileText size={18} /><div><strong>{document.title}</strong><span>Document #{document.id}</span></div></div></td><td><StatusBadge status={document.status} /></td><td>{document.chunk_count}</td><td>{document.source_url ? <a className="source-link" href={document.source_url} target="_blank" rel="noreferrer">飞书原文</a> : document.source_name}</td><td className="align-right"><button className="icon-button icon-button--danger" title="删除文档" onClick={() => remove(document)}><Trash2 size={17} /></button></td></tr>)}
          </tbody></table></div>
        )}
      </section>
    </>
  );
}

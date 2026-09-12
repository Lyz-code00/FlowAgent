import { FileText, Plus, RefreshCw, Trash2, UploadCloud } from "lucide-react";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { EmptyState, ErrorBanner, LoadingBlock, PageHeader, StatusBadge } from "../components/Common";
import type { KnowledgeDocument } from "../types";

export default function Knowledge() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  function load() {
    setLoading(true);
    api<KnowledgeDocument[]>("/api/v1/knowledge/documents").then(setDocuments).catch((reason) => setError(reason.message)).finally(() => setLoading(false));
  }
  useEffect(load, []);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true); setError("");
    const body = new FormData(); body.append("file", file);
    try { await api("/api/v1/knowledge/documents", { method: "POST", body }); load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "上传失败"); }
    finally { setUploading(false); event.target.value = ""; }
  }

  async function remove(document: KnowledgeDocument) {
    if (!window.confirm(`确认删除“${document.title}”及其全部索引吗？`)) return;
    try { await api(`/api/v1/knowledge/documents/${document.id}`, { method: "DELETE" }); setDocuments((items) => items.filter((item) => item.id !== document.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "删除失败"); }
  }

  return (
    <>
      <PageHeader title="知识库" description="管理研发规范、接口文档与历史故障资料，为 Agent 提供可信依据。" action={<><input ref={input} type="file" accept=".md,.markdown,.txt,.pdf" hidden onChange={upload} /><button className="primary-button compact" onClick={() => input.current?.click()} disabled={uploading}><Plus size={17} />{uploading ? "正在索引…" : "上传文档"}</button></>} />
      {error && <ErrorBanner message={error} />}
      <section className="knowledge-summary">
        <div><UploadCloud size={23} /><span><strong>{documents.length}</strong> 份知识文档</span></div>
        <div><FileText size={23} /><span><strong>{documents.reduce((sum, item) => sum + item.chunk_count, 0)}</strong> 个可检索分块</span></div>
        <button className="text-button" onClick={load}><RefreshCw size={16} />刷新状态</button>
      </section>
      <section className="panel table-panel">
        {loading ? <LoadingBlock /> : !documents.length ? <EmptyState title="知识库还是空的" description="上传 Markdown、TXT 或文本型 PDF，FlowAgent 就能基于内部证据回答。" /> : (
          <div className="table-scroll"><table><thead><tr><th>文档</th><th>状态</th><th>分块数</th><th>来源文件</th><th className="align-right">操作</th></tr></thead><tbody>
            {documents.map((document) => <tr key={document.id}><td><div className="document-name"><FileText size={18} /><div><strong>{document.title}</strong><span>Document #{document.id}</span></div></div></td><td><StatusBadge status={document.status} /></td><td>{document.chunk_count}</td><td>{document.source_name}</td><td className="align-right"><button className="icon-button icon-button--danger" title="删除文档" onClick={() => remove(document)}><Trash2 size={17} /></button></td></tr>)}
          </tbody></table></div>
        )}
      </section>
    </>
  );
}

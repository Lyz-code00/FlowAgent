# FlowAgent

FlowAgent 是面向软件研发团队的飞书 AI 研发协同工作台。当前已经完成飞书消息入口、数据库会话、多轮 Agent Loop、GitHub Issue、内部知识检索，以及蓝白企业风格的 Web 管理后台。

## 当前进度

- `POST /api/v1/channels/feishu/events` 支持飞书 URL Verification。
- 支持 verification token 与可选请求签名校验。
- 支持文本、图片、语音、Markdown、TXT 和文本型 PDF；群聊要求 @机器人，私聊可直接触发。
- 飞书事件转换为 `UnifiedMessage`，Agent 不读取渠道原始协议。
- 数据库唯一约束防止同一个 `message_id` 被重复处理。
- 通过飞书开放平台获取 tenant access token，并回复原消息。
- 用户要求生成/导出文档时，可创建企业蓝白风格的真实 Word `.docx`，上传飞书并作为附件回复。
- 自动建立 Tenant、User、ChannelAccount、Conversation 和 Message 映射。
- 使用“最近 10 轮原文 + 已保存讨论摘要/待办 + 历史 Issue、URL 与重要约束”的分层记忆。
- 支持 OpenAI-compatible `/chat/completions` Provider。
- Agent Loop 最多执行 5 步，并记录 LLM/Tool Step、耗时、状态和最终答案。
- Agent 最终回复受平台规章约束，不做字符过滤；真实 URL 与 Citation 会原样保留。
- 最终状态区分 `resolved`、`partial` 和 `blocked`，达到步骤上限不会冒充任务完成。
- 支持 `github_search_issue`、`github_get_issue` 和 `github_create_issue`。
- 支持 `github_recent_changes`，按时间合并展示近期 Commit 与 Pull Request。
- Tool 参数由严格 Pydantic Schema 校验，未知字段和非法值会返回给 Agent 修正。
- GitHub 写操作执行服务端 RBAC；默认只有 `lead` 和 `admin` 可以创建 Issue。
- 创建 Issue 使用数据库 `operation_id` 幂等，同一来源消息不会重复创建。
- GitHub 鉴权、限流、超时及 API 错误会转换为明确的 Tool 错误。
- GitHub 配置可在后台编辑并测试连接；Token 使用 AES-GCM 加密落库，接口永不回显明文。
- P0/P1 Issue 创建必须经过一次性确认码二次确认，确认码绑定用户、会话和完整操作参数。
- 只读 Tool 发生暂时性异常时最多重试 3 次并指数退避；外部写操作不会盲目重试。
- 支持 Markdown、TXT 和文本型 PDF 知识文档导入。
- 文档按自然边界重叠分块，并通过可配置的 Embedding Provider 建立索引。
- PostgreSQL 使用 pgvector 保存向量；SQLite 使用 JSON 便于本地开发和测试。
- `knowledge_search` 严格按当前 Tenant 检索并返回带编号的 Citation 证据。
- 知识检索融合 Dense Embedding 与 BM25，对中文短语、错误码和技术标识符进行混合排序。
- 未检索到可靠证据时明确返回空召回，不伪造引用。
- 未配置 LLM Key 时使用明确标记的本地开发响应，不会伪装成真实模型结果。
- 提供蓝白企业风格的 React 管理后台，覆盖运行看板、会话、实时 Agent Trace、知识库、讨论沉淀、用户权限、反馈与运行配置。
- 讨论摘要支持编辑、确认，并将待办幂等转换为真实 GitHub Issue。
- Agent 回复支持正向/负向反馈，负向反馈集中进入 Bad Case 页面。
- Agent Trace 通过鉴权 SSE 实时更新，可展开查看 Tool 参数、结果、异常与最终答案。
- 管理 API 与知识库 API 通过独立 Admin Token 保护，前端仅在当前浏览器会话中保存 Token。

## 本地运行

需要 Python 3.11+（推荐 3.12）。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp ../.env.example ../.env
uvicorn app.main:app --reload --port 8001
```

`.env.example` 默认使用本地 SQLite，便于直接开发。模型接口已按 DeepSeek OpenAI-compatible API 配置为 `https://api.deepseek.com` 和 `deepseek-v4-flash`；填写 `FLOWAGENT_LLM_API_KEY` 后启用真实模型。

图片理解默认使用 `deepseek-v4-flash-vision-exp`。飞书应用还需要开通读取消息资源的权限，图片和附件才能被机器人下载。语音默认由服务器上的 Whisper 离线转写，不发送给新的第三方；首次使用会下载一次 `base` 模型并写入持久缓存：

```env
FLOWAGENT_LLM_VISION_MODEL=deepseek-v4-flash-vision-exp
FLOWAGENT_TRANSCRIPTION_BACKEND=local
FLOWAGENT_TRANSCRIPTION_MODEL=base
FLOWAGENT_TRANSCRIPTION_DEVICE=cpu
FLOWAGENT_TRANSCRIPTION_COMPUTE_TYPE=int8
```

如需改用兼容 `/audio/transcriptions` 的外部服务，可将 backend 改为 `remote`，并配置 `FLOWAGENT_TRANSCRIPTION_BASE_URL`、`FLOWAGENT_TRANSCRIPTION_API_KEY` 和模型名。未配置可用转写服务时，机器人会明确提示，绝不会猜测语音内容。

生成 Word 文档会使用 `generate_document` 工具在内存中创建 `.docx`，Trace 只记录文件名、类型和大小，不记录文件二进制。飞书应用需要具备消息与资源相关权限，才能上传文件并回复给用户。

首次启动前必须修改后台管理 Token：

```env
FLOWAGENT_ADMIN_API_TOKEN=replace-with-a-long-random-token
```

真实 GitHub 集成需要配置：

```env
FLOWAGENT_GITHUB_TOKEN=github_pat_xxx
FLOWAGENT_GITHUB_OWNER=your-owner
FLOWAGENT_GITHUB_REPO=your-repo
FLOWAGENT_GITHUB_DEFAULT_LABELS=["bug"]
FLOWAGENT_GITHUB_DEFAULT_ASSIGNEE=
```

建议使用只授权目标仓库的 fine-grained token：Metadata 只读、Issues 读写。Token 不应提交到版本库。

Embedding 默认使用本地确定性实现，便于无密钥开发。接入真实服务：

```env
FLOWAGENT_EMBEDDING_API_KEY=your-key
FLOWAGENT_EMBEDDING_BASE_URL=https://api.openai.com/v1
FLOWAGENT_EMBEDDING_MODEL=text-embedding-3-small
FLOWAGENT_EMBEDDING_DIMENSIONS=1536
```

上传知识文档：

```bash
curl -X POST http://localhost:8001/api/v1/knowledge/documents \
  -H 'X-FlowAgent-Admin-Token: replace-with-a-long-random-token' \
  -F 'file=@./guide.md'
```

知识库接口还支持：

- `GET /api/v1/knowledge/documents`
- `DELETE /api/v1/knowledge/documents/{document_id}`

这些接口与管理查询接口都要求 `X-FlowAgent-Admin-Token` 请求头。公网部署时还应由反向代理启用 HTTPS，并把 Token 作为部署密钥管理。

前端本地开发：

```bash
cd web
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`，输入与后端一致的 Admin Token。Vite 会将 `/api` 和 `/health` 代理到本地 8001 端口，避免与机器上已有的 8000 端口服务冲突。

使用 PostgreSQL 启动完整基础设施：

```bash
cp .env.example .env
docker compose up --build
```

浏览器打开 `http://localhost:3000` 进入管理后台；后端 API 位于 `http://localhost:8001`。

容器启动时会先执行 Alembic 迁移。手动执行迁移：

```bash
cd backend
alembic upgrade head
```

健康检查：

```bash
curl http://localhost:8001/health
```

飞书事件地址配置为：

```text
https://your-domain.example/api/v1/channels/feishu/events
```

使用飞书“长连接接收事件”时，无需公网回调地址。后端 API 启动后，在另一个终端启动监听器：

```bash
cd backend
python -m app.workers.feishu_ws
```

长连接监听器接收 `im.message.receive_v1` 后，会将事件转发给本机 FlowAgent 消息网关处理。

## 测试

```bash
cd backend
pytest
```

## 目录

```text
backend/app/
├── agent/       多轮 Agent Loop 与最大步数保护
├── api/         HTTP 路由
├── channels/    渠道适配器
├── core/        配置
├── db/          SQLAlchemy 模型与异步 Session
├── llm/         OpenAI-compatible Provider
├── rag/         文档解析、分块与 Embedding
├── schemas/     统一领域模型
├── services/    身份、会话、Trace 与消息编排
└── tools/       Tool 接口和执行器
web/src/
├── components/  企业后台布局与通用组件
└── pages/       看板、会话、知识库、配置与登录页
```

## 下一里程碑

v0.1 PRD 核心闭环已完成。下一阶段可接入组织级单点登录（OIDC/SSO）、钉钉/企业微信 Channel Adapter、Sentry/Prometheus 监控工具，以及基于 Bad Case 的离线评估与 Rerank。

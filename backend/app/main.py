from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.loop import AgentLoop
from app.api.admin import router as admin_router
from app.api.feishu import router as feishu_router
from app.api.knowledge import router as knowledge_router
from app.channels.feishu import FeishuAdapter
from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory, create_tables
from app.llm.provider import DevelopmentProvider, OpenAICompatibleProvider
from app.rag.embedding import (
    DevelopmentHashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)
from app.services.conversation_service import ConversationService
from app.services.admin_query_service import AdminQueryService
from app.services.github_service import GitHubService
from app.services.identity_service import IdentityService
from app.services.knowledge_service import KnowledgeService
from app.services.message_gateway import MessageGateway
from app.services.permission_service import PermissionService
from app.services.tool_operation_service import ToolOperationService
from app.services.trace_service import TraceService
from app.tools.github import (
    GitHubCreateIssueTool,
    GitHubGetIssueTool,
    GitHubSearchIssueTool,
)
from app.tools.knowledge import KnowledgeSearchTool
from app.tools.runner import ToolRunner


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    engine = create_engine(settings.database_url)
    if settings.auto_create_tables:
        await create_tables(engine)
    session_factory = create_session_factory(engine)
    adapter = FeishuAdapter(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        verification_token=settings.feishu_verification_token,
        encrypt_key=settings.feishu_encrypt_key,
        bot_open_id=settings.feishu_bot_open_id,
    )
    trace_service = TraceService(session_factory)
    conversation_service = ConversationService(
        session_factory, IdentityService()
    )
    provider = (
        OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
        if settings.llm_api_key
        else DevelopmentProvider()
    )
    github_service = GitHubService(
        token=settings.github_token,
        owner=settings.github_owner,
        repo=settings.github_repo,
        base_url=settings.github_base_url,
        api_version=settings.github_api_version,
    )
    embedding_provider = (
        OpenAICompatibleEmbeddingProvider(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        if settings.embedding_api_key
        else DevelopmentHashEmbeddingProvider(
            dimensions=settings.embedding_dimensions
        )
    )
    knowledge_service = KnowledgeService(
        session_factory,
        embedding_provider,
        chunk_size=settings.knowledge_chunk_size,
        chunk_overlap=settings.knowledge_chunk_overlap,
        max_file_bytes=settings.knowledge_max_file_bytes,
        min_score=settings.knowledge_min_score,
    )
    operation_service = ToolOperationService(session_factory)
    tools = [
        KnowledgeSearchTool(
            knowledge_service, default_top_k=settings.knowledge_top_k
        ),
        GitHubSearchIssueTool(github_service),
        GitHubGetIssueTool(github_service),
        GitHubCreateIssueTool(
            github_service,
            operation_service,
            default_labels=settings.github_default_labels,
            default_assignee=settings.github_default_assignee,
        ),
    ]
    agent = AgentLoop(
        provider=provider,
        tool_runner=ToolRunner(
            trace_service=trace_service,
            permission_service=PermissionService(
                member_can_create_issue=settings.member_can_create_issue
            ),
            tools=tools,
            timeout_seconds=settings.tool_timeout_seconds,
        ),
        trace_service=trace_service,
        max_steps=settings.max_agent_steps,
    )
    app.state.db_engine = engine
    app.state.admin_query_service = AdminQueryService(session_factory)
    app.state.knowledge_service = knowledge_service
    app.state.feishu_adapter = adapter
    app.state.message_gateway = MessageGateway(
        adapter=adapter,
        agent=agent,
        conversation_service=conversation_service,
        trace_service=trace_service,
        context_turns=settings.context_turns,
    )
    yield
    await engine.dispose()


app = FastAPI(title="FlowAgent API", version="0.5.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-FlowAgent-Admin-Token"],
)
app.include_router(admin_router)
app.include_router(feishu_router)
app.include_router(knowledge_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "flowagent"}

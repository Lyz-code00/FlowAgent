from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.loop import SYSTEM_PROMPT, AgentLoop
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
from app.services.confirmation_service import ConfirmationService
from app.services.agent_config_service import AgentConfigService
from app.services.admin_query_service import AdminQueryService
from app.services.github_service import GitHubService
from app.services.feedback_service import FeedbackService
from app.services.github_config_service import GitHubConfigService, SecretCipher
from app.services.identity_service import IdentityService
from app.services.knowledge_service import KnowledgeService
from app.services.message_gateway import MessageGateway
from app.services.permission_service import PermissionService
from app.services.summary_service import SummaryService
from app.services.tool_operation_service import ToolOperationService
from app.services.trace_service import TraceService
from app.services.transcription_service import (
    LocalWhisperTranscriptionService,
    OpenAICompatibleTranscriptionService,
)
from app.services.document_service import DocumentService
from app.tools.document import GenerateDocumentTool
from app.tools.github import (
    GitHubCreateIssueTool,
    GitHubGetIssueTool,
    GitHubRecentChangesTool,
    GitHubSearchIssueTool,
)
from app.tools.knowledge import KnowledgeSearchTool
from app.tools.runner import ToolRunner
from app.tools.summary import SaveConversationSummaryTool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    engine = create_engine(settings.database_url)
    if settings.auto_create_tables:
        await create_tables(engine)
    session_factory = create_session_factory(engine)
    if settings.transcription_backend.lower() == "local":
        transcription_service = LocalWhisperTranscriptionService(
            model=settings.transcription_model or "base",
            device=settings.transcription_device,
            compute_type=settings.transcription_compute_type,
        )
    else:
        transcription_service = OpenAICompatibleTranscriptionService(
            base_url=settings.transcription_base_url,
            api_key=settings.transcription_api_key,
            model=settings.transcription_model,
        )
    adapter = FeishuAdapter(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        verification_token=settings.feishu_verification_token,
        encrypt_key=settings.feishu_encrypt_key,
        bot_open_id=settings.feishu_bot_open_id,
        max_attachment_bytes=settings.attachment_max_file_bytes,
        transcription_service=transcription_service,
    )
    trace_service = TraceService(session_factory)
    conversation_service = ConversationService(
        session_factory, IdentityService()
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
    confirmation_service = ConfirmationService(session_factory)
    summary_service = SummaryService(session_factory)
    github_config_service = GitHubConfigService(
        session_factory,
        SecretCipher(settings.config_encryption_key or settings.admin_api_token),
    )
    await github_config_service.ensure_default(
        owner=settings.github_owner,
        repo=settings.github_repo,
        token=settings.github_token,
        default_labels=settings.github_default_labels,
        default_assignee=settings.github_default_assignee,
        member_can_create_issue=settings.member_can_create_issue,
    )
    agent_config_service = AgentConfigService(session_factory)
    await agent_config_service.ensure_default(
        model=settings.llm_model,
        system_prompt=SYSTEM_PROMPT,
        max_steps=settings.max_agent_steps,
    )

    async def resolve_agent() -> AgentLoop:
        config = await agent_config_service.get()
        github_config = await github_config_service.get()
        github_service = GitHubService(
            token=github_config.token,
            owner=github_config.owner,
            repo=github_config.repo,
            base_url=settings.github_base_url,
            api_version=settings.github_api_version,
        )
        provider = (
            OpenAICompatibleProvider(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=config.model,
                vision_model=settings.llm_vision_model,
            )
            if settings.llm_api_key
            else DevelopmentProvider()
        )
        tools = [
            GenerateDocumentTool(DocumentService()),
            KnowledgeSearchTool(
                knowledge_service, default_top_k=settings.knowledge_top_k
            ),
            GitHubSearchIssueTool(github_service),
            GitHubGetIssueTool(github_service),
            GitHubRecentChangesTool(github_service),
            GitHubCreateIssueTool(
                github_service,
                operation_service,
                default_labels=github_config.default_labels,
                default_assignee=github_config.default_assignee,
                confirmations=confirmation_service,
            ),
            SaveConversationSummaryTool(summary_service),
        ]
        enabled_tools = [
            tool for tool in tools
            if (config.knowledge_enabled or tool.name != "knowledge_search")
            and (config.github_enabled or not tool.name.startswith("github_"))
        ]
        return AgentLoop(
            provider=provider,
            tool_runner=ToolRunner(
                trace_service=trace_service,
                permission_service=PermissionService(
                    member_can_create_issue=github_config.member_can_create_issue
                ),
                tools=enabled_tools,
                timeout_seconds=settings.tool_timeout_seconds,
            ),
            trace_service=trace_service,
            max_steps=config.max_steps,
            system_prompt=config.system_prompt,
        )

    app.state.db_engine = engine
    app.state.admin_query_service = AdminQueryService(session_factory)
    app.state.feedback_service = FeedbackService(session_factory)
    app.state.agent_config_service = agent_config_service
    app.state.github_config_service = github_config_service
    app.state.knowledge_service = knowledge_service
    async def resolve_github_service() -> GitHubService:
        config = await github_config_service.get()
        return GitHubService(
            token=config.token,
            owner=config.owner,
            repo=config.repo,
            base_url=settings.github_base_url,
            api_version=settings.github_api_version,
        )

    app.state.github_service_resolver = resolve_github_service
    app.state.tool_operation_service = operation_service
    app.state.summary_service = summary_service
    app.state.feishu_adapter = adapter
    app.state.message_gateway = MessageGateway(
        adapter=adapter,
        agent_resolver=resolve_agent,
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-FlowAgent-Admin-Token"],
)
app.include_router(admin_router)
app.include_router(feishu_router)
app.include_router(knowledge_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "flowagent"}

export interface Metrics {
  conversations_today: number;
  agent_runs_today: number;
  tool_calls_today: number;
  github_issues_created_today: number;
  knowledge_searches_today: number;
  failed_calls_today: number;
  average_response_ms: number;
}

export interface QualityMetric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  numerator: number | null;
  denominator: number | null;
  status: "measured" | "insufficient_data";
  source: "production" | "offline_builtin";
  note: string;
}

export interface QualityMetricsResponse {
  window_days: number;
  generated_at: string;
  metrics: QualityMetric[];
  tool_breakdown: Array<{
    tool_name: string;
    attempts: number;
    succeeded: number;
    failed: number;
    success_rate: number | null;
    average_latency_ms: number | null;
    p95_latency_ms: number | null;
  }>;
  failure_categories: Array<{
    category: string;
    count: number;
    tools: string[];
    examples: string[];
  }>;
  latency_breakdown: Array<{
    stage: "agent_run" | "llm_step" | "tool_step";
    samples: number;
    average_ms: number | null;
    p95_ms: number | null;
  }>;
}

export interface QualityBenchmarkResponse {
  suite: string;
  generated_at: string | null;
  metrics: QualityMetric[];
  rag_cases?: Array<{
    query: string;
    expected_document: number;
    top_k: number[];
    passed: boolean;
  }>;
}

export interface Conversation {
  id: number;
  tenant_key: string;
  platform: string;
  external_conversation_id: string;
  message_count: number;
  last_message: string | null;
  updated_at: string;
}

export interface Message {
  id: number;
  role: string;
  content: string;
  external_message_id: string | null;
  created_at: string;
  feedback: Pick<FeedbackRecord, "id" | "rating" | "reason"> | null;
}

export interface FeedbackRecord {
  id: number;
  message_id: number;
  rating: "positive" | "negative";
  reason: string | null;
  content: string;
  conversation_id: number;
  tenant_key: string;
  platform: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface TraceStep {
  id: number;
  step_no: number;
  kind: string;
  name: string | null;
  status: string;
  input: unknown;
  output: unknown;
  latency_ms: number | null;
  error: string | null;
}

export interface TraceRun {
  id: number;
  model: string;
  status: string;
  latency_ms: number | null;
  final_answer: string | null;
  error: string | null;
  external_id: string | null;
  external_url: string | null;
  started_at: string;
  completed_at: string | null;
  steps: TraceStep[];
}

export interface KnowledgeDocument {
  id: number;
  title: string;
  source_name: string;
  source_url: string | null;
  status: string;
  chunk_count: number;
  error: string | null;
}

export interface RuntimeConfig {
  environment: string;
  llm: { model: string; configured: boolean; max_steps: number; context_turns: number };
  github: {
    owner: string;
    repo: string;
    configured: boolean;
    default_labels: string[];
    default_assignee: string | null;
    member_can_create_issue: boolean;
  };
  knowledge: {
    embedding_model: string;
    external_embedding_configured: boolean;
    dimensions: number;
    default_top_k: number;
  };
  feishu: { configured: boolean };
  web_search: {
    backend: string;
    configured: boolean;
    timeout_seconds: number;
    max_attempts: number;
  };
  monitoring: {
    health_services: string[];
    prometheus: boolean;
    loki: boolean;
    sentry: boolean;
  };
}

export interface AgentConfig {
  name: string;
  model: string;
  system_prompt: string;
  max_steps: number;
  knowledge_enabled: boolean;
  github_enabled: boolean;
}

export interface GitHubConfig {
  owner: string;
  repo: string;
  token_configured: boolean;
  default_labels: string[];
  default_assignee: string | null;
  member_can_create_issue: boolean;
}

export interface SummaryActionItem {
  content: string;
  owner: string | null;
  due_date: string | null;
  priority: string | null;
  status: string;
  github_issue?: {
    number: number;
    title: string;
    state: string;
    html_url: string;
  } | null;
}

export interface ConversationSummary {
  id: number;
  conversation_id: number;
  tenant_key: string;
  external_conversation_id: string;
  summary: string;
  decisions: string[];
  bugs: string[];
  action_items: SummaryActionItem[];
  status: "draft" | "confirmed";
  created_at: string;
  updated_at: string;
}

export type UserRole = "member" | "lead" | "admin";

export interface ManagedUser {
  id: number;
  name: string;
  role: UserRole;
  tenant_key: string;
  channels: Array<{ platform: string; external_user_id: string }>;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface TenantSummary {
  id: number;
  external_key: string;
  name: string;
  status: string;
  user_count: number;
  conversation_count: number;
  document_count: number;
}

export interface OwnershipMapping {
  id: number;
  tenant_id: number;
  tenant_key: string;
  service: string;
  team: string;
  display_name: string;
  feishu_open_id: string;
  github_username: string;
  active: boolean;
}

export interface IncidentRecord {
  id: number;
  incident_key: string;
  title: string;
  status: string;
  severity: string;
  service: string | null;
  error_code: string | null;
  occurred_at: string | null;
  summary: string;
  root_cause: string | null;
  evidence: string[];
  source_url: string | null;
  created_by_user_id: number;
  created_at: string;
  updated_at: string;
}

export interface Metrics {
  conversations_today: number;
  agent_runs_today: number;
  tool_calls_today: number;
  github_issues_created_today: number;
  knowledge_searches_today: number;
  failed_calls_today: number;
  average_response_ms: number;
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
  started_at: string;
  completed_at: string | null;
  steps: TraceStep[];
}

export interface KnowledgeDocument {
  id: number;
  title: string;
  source_name: string;
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

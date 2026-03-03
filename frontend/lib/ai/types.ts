// frontend/lib/ai/types.ts
// Core types for BaselineMLB AI routing and prompt system

export type AIModel =
  | 'haiku-4.5'
  | 'sonnet-4.6'
  | 'opus-4.6'
  | 'deepseek-v3.2'
  | 'gpt-4o-mini';

export type TaskType =
  | 'user_question'
  | 'explain_projection'
  | 'qa_anomaly'
  | 'batch_classify'
  | 'batch_extract'
  | 'code_implementation'
  | 'architecture_decision'
  | 'marketing_copy'
  | 'seo_content'
  | 'welcome_email'
  | 'pipeline_report'
  | 'strategy_decision';

export type Criticality = 'low' | 'medium' | 'high' | 'critical';
export type Latency = 'interactive' | 'background' | 'batch';
export type RiskLevel = 'low' | 'medium' | 'high';

export interface TaskDescriptor {
  task_type: TaskType;
  criticality: Criticality;
  latency: Latency;
  description: string;
  context?: Record<string, unknown>;
}

export interface RoutingDecision {
  model: AIModel;
  reason: string;
  expected_risk: RiskLevel;
}

export interface PromptConfig {
  id: string;
  model_default: AIModel;
  system_prompt: string;
  temperature: number;
  max_tokens: number;
  extended_thinking_budget?: number;
}

export interface AIRequest {
  task: TaskDescriptor;
  payload: {
    system_prompt?: string;
    user_prompt: string;
    prompt_id?: string;
  };
  stream?: boolean;
}

export interface AIResponse {
  model: AIModel;
  prompt_id: string;
  content: string;
  usage: {
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
  };
  latency_ms: number;
}

export interface AILogEntry {
  id?: string;
  created_at?: string;
  model: AIModel;
  prompt_id: string;
  task_type: TaskType;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  user_id?: string;
  success: boolean;
  error_message?: string;
}

// Cost per 1M tokens (input/output)
export const MODEL_COSTS: Record<AIModel, { input: number; output: number }> = {
  'haiku-4.5': { input: 0.80, output: 4.00 },
  'sonnet-4.6': { input: 3.00, output: 15.00 },
  'opus-4.6': { input: 15.00, output: 75.00 },
  'deepseek-v3.2': { input: 0.27, output: 1.10 },
  'gpt-4o-mini': { input: 0.15, output: 0.60 },
};

// Model to API provider mapping
export const MODEL_PROVIDERS: Record<AIModel, 'anthropic' | 'deepseek' | 'openai'> = {
  'haiku-4.5': 'anthropic',
  'sonnet-4.6': 'anthropic',
  'opus-4.6': 'anthropic',
  'deepseek-v3.2': 'deepseek',
  'gpt-4o-mini': 'openai',
};

// Actual API model identifiers
export const MODEL_API_IDS: Record<AIModel, string> = {
  'haiku-4.5': 'claude-3-5-haiku-20241022',
  'sonnet-4.6': 'claude-sonnet-4-20250514',
  'opus-4.6': 'claude-opus-4-20250514',
  'deepseek-v3.2': 'deepseek-chat',
  'gpt-4o-mini': 'gpt-4o-mini',
};

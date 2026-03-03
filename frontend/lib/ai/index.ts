// frontend/lib/ai/index.ts
// Main entry point for BaselineMLB AI system
// Usage: import { routeAndCallAI } from '@/lib/ai';

import { routeTask } from './router';
import { callAI } from './clients';
import { getPromptConfig } from './prompts';
import type {
  TaskDescriptor,
  AIResponse,
  AILogEntry,
} from './types';

export type { AIModel, TaskDescriptor, AIResponse, PromptConfig } from './types';
export { routeTask } from './router';
export { callAI } from './clients';
export { getPromptConfig, PROMPT_REGISTRY } from './prompts';

/**
 * Top-level function: route a task to the right model, look up
 * the prompt config, call the AI, and return the response.
 *
 * This is the single function your API routes and n8n should call.
 */
export async function routeAndCallAI(
  task: TaskDescriptor,
  userPrompt: string,
  options?: {
    promptIdOverride?: string;
    modelOverride?: string;
  }
): Promise<AIResponse & { routing_reason: string }> {
  // 1. Route to model
  const routing = routeTask(task);
  const model = (options?.modelOverride as AIResponse['model']) || routing.model;

  // 2. Look up prompt config
  const promptId = options?.promptIdOverride || taskTypeToPromptId(task.task_type);
  const promptConfig = getPromptConfig(promptId);

  // 3. Call AI
  const response = await callAI({
    model,
    system_prompt: promptConfig.system_prompt,
    user_prompt: userPrompt,
    prompt_id: promptId,
    temperature: promptConfig.temperature,
    max_tokens: promptConfig.max_tokens,
  });

  // 4. Log (fire and forget)
  logAICall(response, task).catch(() => {});

  return {
    ...response,
    routing_reason: routing.reason,
  };
}

/** Map task types to their default prompt IDs */
function taskTypeToPromptId(taskType: string): string {
  const map: Record<string, string> = {
    user_question: 'support_bot_v1',
    explain_projection: 'explain_projection_v1',
    qa_anomaly: 'qa_projection_v1',
    batch_classify: 'batch_classify_props_v1',
    batch_extract: 'batch_weather_v1',
    welcome_email: 'welcome_email_v1',
    pipeline_report: 'pipeline_report_v1',
    marketing_copy: 'methodology_page_v1',
    seo_content: 'methodology_page_v1',
    code_implementation: 'support_bot_v1', // fallback
    architecture_decision: 'support_bot_v1', // fallback
    strategy_decision: 'support_bot_v1', // fallback
  };
  return map[taskType] || 'support_bot_v1';
}

/** Log AI call to Supabase (best-effort) */
async function logAICall(
  response: AIResponse,
  task: TaskDescriptor
): Promise<void> {
  try {
    const { createClient } = await import('@supabase/supabase-js');
    const supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );
    const entry: AILogEntry = {
      model: response.model,
      prompt_id: response.prompt_id,
      task_type: task.task_type,
      input_tokens: response.usage.input_tokens,
      output_tokens: response.usage.output_tokens,
      cost_usd: response.usage.cost_usd,
      latency_ms: response.latency_ms,
      success: true,
    };
    await supabase.from('ai_logs').insert(entry);
  } catch {
    // best-effort logging
  }
}

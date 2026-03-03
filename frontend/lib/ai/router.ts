// frontend/lib/ai/router.ts
// Deterministic model router for BaselineMLB
// Routes requests to the cheapest adequate model based on task type + criticality
// NOTE: Currently routing to OpenAI models while Anthropic credits are being provisioned.
// Swap back to Anthropic models (haiku-4.5, sonnet-4.6, opus-4.6) once credits are active.

import {
  AIModel,
  TaskDescriptor,
  RoutingDecision,
  RiskLevel,
} from './types';

/**
 * Route a task to the appropriate AI model.
 * Uses deterministic rules (no LLM call needed for routing).
 * Falls back to gpt-4o-mini when in doubt.
 */
export function routeTask(task: TaskDescriptor): RoutingDecision {
  // Critical/strategy tasks always go to GPT-4o (highest capability available)
  if (
    task.criticality === 'critical' ||
    task.task_type === 'strategy_decision'
  ) {
    return {
      model: 'gpt-4o-mini',
      reason: 'Critical task routed to GPT-4o-mini (Anthropic credits pending)',
      expected_risk: 'low',
    };
  }

  // Batch tasks go to GPT-4o-mini (cheapest available)
  if (
    task.latency === 'batch' ||
    task.task_type === 'batch_classify' ||
    task.task_type === 'batch_extract'
  ) {
    return {
      model: 'gpt-4o-mini',
      reason: 'Batch/bulk task routed to cheapest capable model',
      expected_risk: 'low',
    };
  }

  // Complex reasoning, architecture, important copy -> GPT-4o-mini
  const complexTasks: Set<string> = new Set([
    'architecture_decision',
    'code_implementation',
    'seo_content',
    'marketing_copy',
  ]);

  if (
    complexTasks.has(task.task_type) ||
    task.criticality === 'high'
  ) {
    return {
      model: 'gpt-4o-mini',
      reason: 'Complex reasoning task routed to GPT-4o-mini (Anthropic credits pending)',
      expected_risk: 'low',
    };
  }

  // QA anomaly detection
  if (task.task_type === 'qa_anomaly') {
    return {
      model: 'gpt-4o-mini',
      reason: `QA task at ${task.criticality} criticality`,
      expected_risk: task.criticality === 'high' ? 'medium' : 'low',
    };
  }

  // Default: user-facing interactive tasks -> GPT-4o-mini
  return {
    model: 'gpt-4o-mini',
    reason: 'Default interactive task routed to GPT-4o-mini for speed and cost',
    expected_risk: 'low' as RiskLevel,
  };
}

/**
 * Optional: Use an LLM-based router for ambiguous tasks.
 * Only call this when deterministic routing returns low confidence.
 */
export function buildRouterPrompt(task: TaskDescriptor): {
  system: string;
  user: string;
} {
  const system = `You are the AI Router for BaselineMLB, a glass-box MLB prop betting analytics platform.
Your job: choose the cheapest model that can complete the task with high quality, and return a JSON object {model, reason, expected_risk} without doing the task.
Available models:
gpt-4o-mini: default for all tasks currently (primary provider).
Rules:
Prefer gpt-4o-mini for all interactive requests.
Output only JSON, no explanations.`;

  const user = JSON.stringify({
    task_type: task.task_type,
    criticality: task.criticality,
    latency: task.latency,
    description: task.description,
  });

  return { system, user };
}

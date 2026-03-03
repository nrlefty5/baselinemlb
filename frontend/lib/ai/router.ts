// frontend/lib/ai/router.ts
// Deterministic model router for BaselineMLB
// Routes requests to the cheapest adequate model based on task type + criticality

import {
  AIModel,
  TaskDescriptor,
  RoutingDecision,
  RiskLevel,
} from './types';

/**
 * Route a task to the appropriate AI model.
 * Uses deterministic rules (no LLM call needed for routing).
 * Falls back to haiku-4.5 when in doubt.
 */
export function routeTask(task: TaskDescriptor): RoutingDecision {
  // Critical/strategy tasks always go to Opus
  if (
    task.criticality === 'critical' ||
    task.task_type === 'strategy_decision'
  ) {
    return {
      model: 'opus-4.6',
      reason: 'Critical task or strategic decision requires highest capability',
      expected_risk: 'low',
    };
  }

  // Batch tasks go to DeepSeek
  if (
    task.latency === 'batch' ||
    task.task_type === 'batch_classify' ||
    task.task_type === 'batch_extract'
  ) {
    return {
      model: 'deepseek-v3.2',
      reason: 'Batch/bulk task routed to cheapest capable model',
      expected_risk: 'low',
    };
  }

  // Complex reasoning, architecture, important copy -> Sonnet
  const sonnetTasks: Set<string> = new Set([
    'architecture_decision',
    'code_implementation',
    'seo_content',
    'marketing_copy',
  ]);
  if (
    sonnetTasks.has(task.task_type) ||
    task.criticality === 'high'
  ) {
    return {
      model: 'sonnet-4.6',
      reason: 'Complex reasoning or high-criticality task needs Sonnet',
      expected_risk: 'low',
    };
  }

  // QA anomaly detection: medium criticality -> Haiku, high -> Sonnet
  if (task.task_type === 'qa_anomaly') {
    const model: AIModel =
      task.criticality === 'high' ? 'sonnet-4.6' : 'haiku-4.5';
    return {
      model,
      reason: `QA task at ${task.criticality} criticality`,
      expected_risk: task.criticality === 'high' ? 'medium' : 'low',
    };
  }

  // Default: user-facing interactive tasks -> Haiku
  return {
    model: 'haiku-4.5',
    reason: 'Default interactive task routed to Haiku for speed and cost',
    expected_risk: 'low' as RiskLevel,
  };
}

/**
 * Optional: Use Sonnet as an LLM-based router for ambiguous tasks.
 * Only call this when deterministic routing returns low confidence.
 */
export function buildRouterPrompt(task: TaskDescriptor): {
  system: string;
  user: string;
} {
  const system = `You are the AI Router for BaselineMLB, a glass-box MLB prop betting analytics platform.
Your job: choose the cheapest model that can complete the task with high quality, and return a JSON object {model, reason, expected_risk} without doing the task.
Available models:
haiku-4.5: default for user-facing Q&A, explanations, moderate reasoning.
sonnet-4.6: complex reasoning, architecture, long multi-step analysis, important UX copy.
opus-4.6: rare, highest-stakes strategic planning or novel architecture.
deepseek-v3.2: batch-only: bulk classification/extraction/formatting where each individual error has low impact.
gpt-4o-mini: when the task explicitly requires OpenAI-native features (function calling, existing fine-tune).
Rules:
Prefer haiku-4.5 when in doubt for interactive requests.
Use deepseek-v3.2 only for offline batch work.
Use opus-4.6 for tasks explicitly marked "critical" or "strategy" or when failure would cause large financial or reputational damage.
Consider the user's tolerance for latency: if the task requires <1s response and is simple Q&A, choose haiku-4.5.
Output only JSON, no explanations.`;

  const user = JSON.stringify({
    task_type: task.task_type,
    criticality: task.criticality,
    latency: task.latency,
    description: task.description,
  });

  return { system, user };
}

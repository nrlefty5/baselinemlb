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
 *
 * Tier allocation:
 *   Haiku 4.5      – User Q&A, explanations, QA anomaly detection (~70%)
 *   DeepSeek V3.2  – Batch classification & extraction (~5%)
 *   Sonnet 4.6     – Complex reasoning, architecture, important copy (~20%)
 *   Opus 4.6       – Critical strategy decisions (~5%)
 *   GPT-4o Mini    – OpenAI-specific features (rare)
 */
export function routeTask(task: TaskDescriptor): RoutingDecision {
  // ── Tier 4: Critical / strategy → Opus 4.6 ──────────────────────────
  if (
    task.criticality === 'critical' ||
    task.task_type === 'strategy_decision'
  ) {
    return {
      model: 'opus-4.6',
      reason: 'Critical strategy task routed to Opus 4.6',
      expected_risk: 'high',
    };
  }

  // ── Tier 2: Batch tasks → DeepSeek V3.2 ─────────────────────────────
  if (
    task.latency === 'batch' ||
    task.task_type === 'batch_classify' ||
    task.task_type === 'batch_extract'
  ) {
    return {
      model: 'deepseek-v3.2',
      reason: 'Batch/bulk task routed to DeepSeek V3.2 for cost efficiency',
      expected_risk: 'low',
    };
  }

  // ── Tier 3: Complex reasoning / architecture / copy → Sonnet 4.6 ────
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
      model: 'sonnet-4.6',
      reason: 'Complex reasoning task routed to Sonnet 4.6',
      expected_risk: 'medium',
    };
  }

  // ── Tier 1: QA anomaly detection → Haiku 4.5 ────────────────────────
  if (task.task_type === 'qa_anomaly') {
    return {
      model: 'haiku-4.5',
      reason: `QA anomaly detection at ${task.criticality} criticality`,
      expected_risk: task.criticality === 'high' ? 'medium' : 'low',
    };
  }

    // — Tier 1 default: User Q&A, explanations, interactive → DeepSeek V3.2 —
  return {
          model: 'deepseek-v3.2',
          reason: 'Default interactive task routed to DeepSeek V3.2 (Anthropic credits depleted)',
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
Available models (cheapest → most capable):
haiku-4.5: Fast, cheap Anthropic model for Q&A, explanations, QA (~70% of calls).
deepseek-v3.2: Budget model for batch classification and extraction (~5%).
sonnet-4.6: Mid-tier Anthropic model for complex reasoning, architecture (~20%).
opus-4.6: Top-tier Anthropic model for critical strategy decisions (~5%).
gpt-4o-mini: OpenAI model for OpenAI-specific features only (rare).
Rules:
Prefer haiku-4.5 for interactive user requests.
Use deepseek-v3.2 for batch workloads.
Use sonnet-4.6 for complex reasoning or high-criticality tasks.
Reserve opus-4.6 for critical decisions only.
Output only JSON, no explanations.`;

  const user = JSON.stringify({
    task_type: task.task_type,
    criticality: task.criticality,
    latency: task.latency,
    description: task.description,
  });

  return { system, user };
}

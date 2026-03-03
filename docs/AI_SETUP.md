# BaselineMLB AI System Setup

## Architecture Overview

The AI system uses a tiered model approach with deterministic routing:

| Model | Usage | % of Calls | Cost/1M input |
|-------|-------|------------|---------------|
| Haiku 4.5 | User Q&A, explanations, QA | ~70% | $0.80 |
| DeepSeek V3.2 | Batch classification, extraction | ~5% | $0.27 |
| Sonnet 4.6 | Complex reasoning, architecture | ~20% | $3.00 |
| Opus 4.6 | Critical strategy decisions | ~5% | $15.00 |
| GPT-4o Mini | OpenAI-specific features | rare | $0.15 |

## Files Created

```
frontend/lib/ai/
  types.ts          # All TypeScript types, cost tables, model mappings
  router.ts         # Deterministic task-to-model routing
  clients.ts        # Multi-provider API client (Anthropic/DeepSeek/OpenAI)
  prompts.ts        # Centralized prompt registry (10 prompts)
  index.ts          # Main entry: routeAndCallAI()

frontend/app/api/
  ai/route/route.ts       # Internal AI endpoint (n8n + admin)
  support/ask/route.ts    # User-facing support bot with RAG

frontend/components/
  AskBaselineMLB.tsx      # Floating chat widget
  ExplainProjection.tsx   # Inline "Why this projection?" button

supabase/migrations/
  007_ai_system.sql       # ai_logs + ai_prompts tables + views
```

## Setup Steps

### 1. Environment Variables (Vercel)

Add these to Vercel > Settings > Environment Variables:

```
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
INTERNAL_API_KEY=<generate a random 32-char string>
```

Generate INTERNAL_API_KEY:
```bash
openssl rand -hex 32
```

### 2. Supabase Migration

Run `supabase/migrations/007_ai_system.sql` in your Supabase SQL Editor.

This creates:
- `ai_logs` table (tracks every AI call with cost, latency, tokens)
- `ai_prompts` table (optional DB-backed prompt registry)
- `ai_daily_costs` view (daily cost breakdown by model)
- `ai_prompt_performance` view (per-prompt success rates)

### 3. Wire Chat Widget into Layout

Add to `frontend/app/layout.tsx`:

```tsx
import AskBaselineMLB from '@/components/AskBaselineMLB';

// Inside body, before closing </body>:
<AskBaselineMLB />
```

### 4. Add ExplainProjection to Prop Cards

Wherever you display a prop/projection:

```tsx
import ExplainProjection from '@/components/ExplainProjection';

<ExplainProjection
  propName="Gerrit Cole strikeouts O/U 7.5"
  projection={8.2}
  marketLine="-120 over / -105 under"
  marketOdds="-120"
  context="Orioles, 26.5% K rate vs RHP"
/>
```

## Usage from n8n

Call the internal AI endpoint:

```json
POST /api/ai/route
Headers: { "x-api-key": "<INTERNAL_API_KEY>" }
Body: {
  "task": {
    "task_type": "qa_anomaly",
    "criticality": "medium",
    "latency": "background",
    "description": "Check today's projections for anomalies"
  },
  "user_prompt": "<JSON array of props>"
}
```

## Monitoring

Query costs and performance in Supabase:

```sql
-- Daily costs
SELECT * FROM ai_daily_costs;

-- Prompt performance
SELECT * FROM ai_prompt_performance;
```

## Prompt Registry

All prompts live in `frontend/lib/ai/prompts.ts`. To add a new prompt:

1. Add entry to `PROMPT_REGISTRY` in `prompts.ts`
2. Add task type to `TaskType` in `types.ts`
3. Add routing rule to `router.ts` if needed
4. Map task type to prompt ID in `index.ts` `taskTypeToPromptId()`

No redeploy needed if using the DB-backed `ai_prompts` table instead.

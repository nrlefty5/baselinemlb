// frontend/app/api/support/ask/route.ts
// "Ask BaselineMLB" support bot endpoint
// POST /api/support/ask

import { NextRequest, NextResponse } from 'next/server';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import { routeAndCallAI } from '@/lib/ai';
import type { TaskDescriptor } from '@/lib/ai';

// Lazy-init Supabase client to avoid build-time crashes
let _supabase: ReturnType<typeof createClient> | null = null;
function getSupabase() {
  if (!_supabase) {
    _supabase = createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY!
    );
  }
  return _supabase;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { question, context } = body as {
      question: string;
      context?: {
        prop_id?: string;
        player_name?: string;
        game_id?: string;
      };
    };

    if (!question || question.trim().length === 0) {
      return NextResponse.json(
        { error: 'Question is required' },
        { status: 400 }
      );
    }

    const supabase = getSupabase();

    // Build context from Supabase if prop/player context provided
    const supabase = getSupabase();

    let ragContext = '';
    if (context?.prop_id) {
      const { data: prop } = await supabase
        .from('props')
        .select('*')
        .eq('id', context.prop_id)
        .single();
      if (prop) {
        ragContext += `\nRelevant prop data: ${JSON.stringify(prop)}`;
      }
    }

    if (context?.player_name) {
      const { data: projections } = await supabase
        .from('projections')
        .select('*')
        .ilike('player_name', `%${context.player_name}%`)
        .limit(5);
      if (projections?.length) {
        ragContext += `\nRecent projections: ${JSON.stringify(projections)}`;
      }
    }

    // Build the user prompt with RAG context
    const userPrompt = ragContext
      ? `Context from our database:\n${ragContext}\n\nUser question: ${question}`
      : question;

    // Determine task complexity
    const isComplex = question.length > 200 || question.includes('explain') || question.includes('methodology');

    const task: TaskDescriptor = {
      task_type: 'user_question',
      criticality: isComplex ? 'medium' : 'low',
      latency: 'interactive',
      description: question.slice(0, 100),
    };

    const result = await routeAndCallAI(task, userPrompt);

    return NextResponse.json({
      answer: result.content,
      model: result.model,
      prompt_id: result.prompt_id,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[Support Ask]', message);
    return NextResponse.json(
      { error: 'Failed to process question. Please try again.' },
      { status: 500 }
    );
  }
}

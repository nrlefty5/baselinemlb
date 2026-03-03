'use client';

import { useState } from 'react';

interface ExplainProjectionProps {
  propName: string;
  projection: number;
  marketLine: string;
  marketOdds: string;
  context?: string; // e.g. "Orioles, 26.5% K rate vs RHP, hitter-friendly park"
}

export default function ExplainProjection({
  propName,
  projection,
  marketLine,
  marketOdds,
  context,
}: ExplainProjectionProps) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);

  async function fetchExplanation() {
    if (explanation) {
      setIsOpen(!isOpen);
      return;
    }
    setLoading(true);
    setIsOpen(true);

    try {
      const userPrompt = [
        `Prop: ${propName}`,
        `Our projection: ${projection}`,
        `Market: ${marketLine}`,
        `Odds: ${marketOdds}`,
        context ? `Context: ${context}` : '',
      ]
        .filter(Boolean)
        .join('\n');

      const res = await fetch('/api/support/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: `Explain this projection: ${userPrompt}`,
          context: { player_name: propName.split(' ').slice(0, 2).join(' ') },
        }),
      });
      const data = await res.json();
      setExplanation(data.answer || data.error || 'Unable to generate explanation.');
    } catch {
      setExplanation('Failed to load explanation. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="inline-block">
      <button
        onClick={fetchExplanation}
        disabled={loading}
        className="text-xs text-purple-400 hover:text-purple-300 underline underline-offset-2 transition-colors disabled:text-slate-500"
      >
        {loading ? 'Explaining...' : isOpen ? 'Hide explanation' : 'Why this projection?'}
      </button>
      {isOpen && explanation && (
        <div className="mt-2 p-3 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-300 max-w-md">
          <p className="whitespace-pre-wrap">{explanation}</p>
          <p className="text-[10px] text-slate-600 mt-2">
            AI-generated explanation. Not financial advice.
          </p>
        </div>
      )}
    </div>
  );
}

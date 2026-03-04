import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Zap, BarChart3, GitBranch, Target } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

export default function Strategies() {
  const [result, setResult] = useState<any>(null);
  const [symbol, setSymbol] = useState('AAPL');

  const scoreStock = useMutation({
    mutationFn: () => api.scoreStock(symbol),
    onSuccess: (data) => setResult({ type: 'stock-score', data }),
  });

  const rankStocks = useMutation({
    mutationFn: () => api.rankStocks(),
    onSuccess: (data) => setResult({ type: 'stock-rank', data }),
  });

  const scanArb = useMutation({
    mutationFn: () => api.scanArbitrage(),
    onSuccess: (data) => setResult({ type: 'arb', data }),
  });

  const scanProbability = useMutation({
    mutationFn: () => api.scanProbability(),
    onSuccess: (data) => setResult({ type: 'probability', data }),
  });

  const loading = scoreStock.isPending || rankStocks.isPending || scanArb.isPending || scanProbability.isPending;

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Strategies</h2>

      <div className="grid grid-cols-2 gap-4">
        <Card title="Stock Scorer">
          <p className="text-sm text-slate-400 mb-3">
            Multi-signal analysis: technicals + fundamentals + AI sentiment
          </p>
          <div className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              placeholder="Symbol"
            />
            <button
              onClick={() => scoreStock.mutate()}
              disabled={loading}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium text-white disabled:opacity-50"
            >
              <Zap size={16} className="inline mr-1" />
              Score
            </button>
          </div>
        </Card>

        <Card title="Watchlist Ranker">
          <p className="text-sm text-slate-400 mb-3">
            Rank all watchlist stocks by composite score
          </p>
          <button
            onClick={() => rankStocks.mutate()}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium text-white disabled:opacity-50"
          >
            <BarChart3 size={16} className="inline mr-1" />
            Rank Stocks
          </button>
        </Card>

        <Card title="Arbitrage Scanner">
          <p className="text-sm text-slate-400 mb-3">
            Scan Polymarket for multi-outcome arbitrage opportunities
          </p>
          <button
            onClick={() => scanArb.mutate()}
            disabled={loading}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded text-sm font-medium text-white disabled:opacity-50"
          >
            <GitBranch size={16} className="inline mr-1" />
            Scan Arb
          </button>
        </Card>

        <Card title="Probability Edge">
          <p className="text-sm text-slate-400 mb-3">
            Find markets where AI probability differs from market price
          </p>
          <button
            onClick={() => scanProbability.mutate()}
            disabled={loading}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded text-sm font-medium text-white disabled:opacity-50"
          >
            <Target size={16} className="inline mr-1" />
            Scan Probability
          </button>
        </Card>
      </div>

      {loading && (
        <div className="text-center text-slate-400 py-8">
          <div className="animate-spin inline-block w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full mb-2" />
          <p className="text-sm">Running strategy...</p>
        </div>
      )}

      {result && (
        <Card title={`Result: ${result.type}`}>
          <pre className="text-xs text-slate-300 overflow-auto max-h-96 whitespace-pre-wrap">
            {JSON.stringify(result.data, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import Card from '../components/Card';

export default function Trade() {
  const [tab, setTab] = useState<'stock' | 'market'>('stock');
  const [symbol, setSymbol] = useState('');
  const [conditionId, setConditionId] = useState('');
  const [sizeUsd, setSizeUsd] = useState('100');
  const [side, setSide] = useState('buy');
  const [result, setResult] = useState<any>(null);

  const tradeStock = useMutation({
    mutationFn: () => api.tradeStock(symbol),
    onSuccess: (data) => setResult(data),
    onError: (err) => setResult({ error: err.message }),
  });

  const tradeMarket = useMutation({
    mutationFn: () => api.tradeMarket(conditionId, Number(sizeUsd), side),
    onSuccess: (data) => setResult(data),
    onError: (err) => setResult({ error: err.message }),
  });

  const analyzeStock = useMutation({
    mutationFn: () => api.analyzeStock(symbol),
    onSuccess: (data) => setResult({ analysis: data }),
    onError: (err) => setResult({ error: err.message }),
  });

  const loading = tradeStock.isPending || tradeMarket.isPending || analyzeStock.isPending;

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Trade</h2>

      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setTab('stock')}
          className={`px-4 py-2 rounded text-sm font-medium ${tab === 'stock' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'}`}
        >
          Stock
        </button>
        <button
          onClick={() => setTab('market')}
          className={`px-4 py-2 rounded text-sm font-medium ${tab === 'market' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400'}`}
        >
          Polymarket
        </button>
      </div>

      {tab === 'stock' ? (
        <Card title="Stock Trade">
          <div className="space-y-3">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol (e.g., AAPL)"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            />
            <div className="flex gap-2">
              <button
                onClick={() => analyzeStock.mutate()}
                disabled={!symbol || loading}
                className="flex-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-sm font-medium text-white disabled:opacity-50"
              >
                Analyze Only
              </button>
              <button
                onClick={() => tradeStock.mutate()}
                disabled={!symbol || loading}
                className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 rounded text-sm font-medium text-white disabled:opacity-50"
              >
                Analyze & Trade
              </button>
            </div>
          </div>
        </Card>
      ) : (
        <Card title="Polymarket Trade">
          <div className="space-y-3">
            <input
              value={conditionId}
              onChange={(e) => setConditionId(e.target.value)}
              placeholder="Condition ID"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            />
            <div className="flex gap-2">
              <select
                value={side}
                onChange={(e) => setSide(e.target.value)}
                className="px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              >
                <option value="buy">BUY</option>
                <option value="sell">SELL</option>
              </select>
              <input
                value={sizeUsd}
                onChange={(e) => setSizeUsd(e.target.value)}
                placeholder="Size (USD)"
                type="number"
                className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              />
            </div>
            <button
              onClick={() => tradeMarket.mutate()}
              disabled={!conditionId || loading}
              className="w-full px-4 py-2 bg-green-600 hover:bg-green-700 rounded text-sm font-medium text-white disabled:opacity-50"
            >
              Execute Trade
            </button>
          </div>
        </Card>
      )}

      {loading && (
        <div className="text-center text-slate-400 py-4">
          <div className="animate-spin inline-block w-6 h-6 border-2 border-slate-600 border-t-blue-500 rounded-full" />
        </div>
      )}

      {result && (
        <Card title="Result">
          <pre className="text-xs text-slate-300 overflow-auto max-h-96 whitespace-pre-wrap">
            {JSON.stringify(result, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}

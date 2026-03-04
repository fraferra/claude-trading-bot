import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

export default function Markets() {
  const [query, setQuery] = useState('');
  const [stockSymbol, setStockSymbol] = useState('');

  const searchMarkets = useMutation({
    mutationFn: () => api.searchMarkets(query),
  });

  const stockData = useQuery({
    queryKey: ['stock', stockSymbol],
    queryFn: () => api.getStockData(stockSymbol),
    enabled: !!stockSymbol,
  });

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Markets</h2>

      <div className="grid grid-cols-2 gap-4">
        <Card title="Stock Lookup">
          <div className="flex gap-2">
            <input
              value={stockSymbol}
              onChange={(e) => setStockSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol (e.g., AAPL)"
              className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              onKeyDown={(e) => e.key === 'Enter' && stockData.refetch()}
            />
          </div>
          {stockData.data && (
            <div className="mt-3 space-y-2 text-sm">
              {stockData.data.data && (
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-slate-500">Price: </span>
                    <span className="text-white">${stockData.data.data.current_price?.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Volume: </span>
                    <span className="text-white">{stockData.data.data.volume?.toLocaleString()}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">RSI: </span>
                    <span className="text-white">{stockData.data.data.rsi_14?.toFixed(1) || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">MACD: </span>
                    <span className="text-white">{stockData.data.data.macd?.toFixed(3) || 'N/A'}</span>
                  </div>
                </div>
              )}
              {stockData.data.fundamentals && (
                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-800">
                  <div>
                    <span className="text-slate-500">P/E: </span>
                    <span className="text-white">{stockData.data.fundamentals.pe_ratio?.toFixed(1) || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Beta: </span>
                    <span className="text-white">{stockData.data.fundamentals.beta?.toFixed(2) || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Sector: </span>
                    <span className="text-white">{stockData.data.fundamentals.sector || 'N/A'}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Mkt Cap: </span>
                    <span className="text-white">
                      {stockData.data.fundamentals.market_cap
                        ? `$${(stockData.data.fundamentals.market_cap / 1e9).toFixed(1)}B`
                        : 'N/A'}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card title="Polymarket Search">
          <div className="flex gap-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search markets..."
              className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
              onKeyDown={(e) => e.key === 'Enter' && searchMarkets.mutate()}
            />
            <button
              onClick={() => searchMarkets.mutate()}
              disabled={!query || searchMarkets.isPending}
              className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded text-white disabled:opacity-50"
            >
              <Search size={16} />
            </button>
          </div>
        </Card>
      </div>

      {searchMarkets.data && (
        <Card title={`Search Results (${searchMarkets.data.length})`}>
          <div className="space-y-2">
            {searchMarkets.data.map((m: any, i: number) => (
              <div key={i} className="flex items-center justify-between p-2 rounded bg-slate-800/50 text-sm">
                <div className="flex-1">
                  <div className="text-white">{m.question?.slice(0, 80)}</div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    Vol: ${Number(m.volume || 0).toLocaleString()} | End: {m.end_date?.slice(0, 10) || 'N/A'}
                  </div>
                </div>
                <code className="text-xs text-slate-500 ml-2">{m.condition_id?.slice(0, 12)}...</code>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

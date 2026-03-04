import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

export default function Kalshi() {
  const queryClient = useQueryClient();
  const { data: portfolio } = useQuery({ queryKey: ['kalshi-portfolio'], queryFn: api.getKalshiPortfolio, refetchInterval: 30000 });
  const { data: estimates } = useQuery({ queryKey: ['kalshi-estimates'], queryFn: () => api.getKalshiEstimates(30), refetchInterval: 15000 });

  const scanMut = useMutation({
    mutationFn: api.scanKalshi,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kalshi-estimates'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-portfolio'] });
    },
  });

  const hasPortfolio = portfolio && !portfolio.error;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Kalshi Prediction Markets</h1>
        <button
          onClick={() => scanMut.mutate()}
          disabled={scanMut.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          <RefreshCw size={16} className={scanMut.isPending ? 'animate-spin' : ''} />
          {scanMut.isPending ? 'Scanning...' : 'Scan Markets'}
        </button>
      </div>

      {/* Portfolio Summary */}
      {hasPortfolio && (
        <div className="grid grid-cols-3 gap-4">
          <Card title="Balance">
            <p className="text-2xl font-bold text-white">${portfolio.cash?.toFixed(2) ?? '0.00'}</p>
          </Card>
          <Card title="Total Equity">
            <p className="text-2xl font-bold text-white">${portfolio.equity?.toFixed(2) ?? '0.00'}</p>
          </Card>
          <Card title="Positions">
            <p className="text-2xl font-bold text-white">{portfolio.positions?.length ?? 0}</p>
          </Card>
        </div>
      )}

      {!hasPortfolio && (
        <Card title="Kalshi Not Connected">
          <p className="text-slate-400">
            Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY environment variables to connect.
          </p>
        </Card>
      )}

      {/* Scan Results */}
      {scanMut.data && (
        <Card title={`Scan Results — ${scanMut.data.analyzed} markets analyzed`}>
          <p className="text-sm text-slate-400 mb-2">
            Found {scanMut.data.markets_found} markets, analyzed {scanMut.data.analyzed}
          </p>
        </Card>
      )}

      {/* Recent Probability Estimates */}
      <Card title="Recent AI Probability Estimates">
        {!estimates || estimates.length === 0 ? (
          <p className="text-slate-500 text-sm">No estimates yet. Run a scan to generate probability estimates.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-right py-2">Market Price</th>
                  <th className="text-right py-2">AI Probability</th>
                  <th className="text-right py-2">Edge</th>
                  <th className="text-right py-2">Kelly</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-right py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {(estimates as any[]).map((e: any, i: number) => {
                  const edge = e.edge_pct * 100;
                  const isPositive = edge > 0;
                  return (
                    <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="py-2 max-w-xs truncate text-white" title={e.title}>
                        <span className="font-mono text-xs text-slate-500 mr-2">{e.ticker}</span>
                        {e.title?.substring(0, 60)}
                      </td>
                      <td className="py-2 text-right text-slate-300">{(e.market_price * 100).toFixed(0)}%</td>
                      <td className="py-2 text-right text-white font-medium">{(e.ai_probability * 100).toFixed(0)}%</td>
                      <td className={`py-2 text-right font-medium ${isPositive ? 'text-green-400' : edge < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                        {edge > 0 ? '+' : ''}{edge.toFixed(1)}%
                      </td>
                      <td className="py-2 text-right text-slate-300">{(e.kelly_fraction * 100).toFixed(1)}%</td>
                      <td className="py-2 text-center">
                        {e.suggested_side === 'buy' ? (
                          <span className="flex items-center justify-center gap-1 text-green-400"><TrendingUp size={14} /> Buy</span>
                        ) : e.suggested_side === 'sell' ? (
                          <span className="flex items-center justify-center gap-1 text-red-400"><TrendingDown size={14} /> Sell</span>
                        ) : (
                          <span className="flex items-center justify-center gap-1 text-slate-500"><Minus size={14} /> —</span>
                        )}
                      </td>
                      <td className="py-2 text-right text-slate-500 text-xs">
                        {new Date(e.created_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Positions */}
      {hasPortfolio && portfolio.positions?.length > 0 && (
        <Card title="Open Positions">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-right py-2">Quantity</th>
                  <th className="text-right py-2">Avg Entry</th>
                  <th className="text-right py-2">Current</th>
                  <th className="text-right py-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.positions.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white">{p.symbol}</td>
                    <td className="py-2 text-right text-slate-300">{p.quantity}</td>
                    <td className="py-2 text-right text-slate-300">{(p.avg_entry_price * 100).toFixed(0)}c</td>
                    <td className="py-2 text-right text-white">{(p.current_price * 100).toFixed(0)}c</td>
                    <td className={`py-2 text-right font-medium ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${p.unrealized_pnl?.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

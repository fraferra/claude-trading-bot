import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

export default function Crypto() {
  const queryClient = useQueryClient();
  const { data: portfolio } = useQuery({ queryKey: ['crypto-portfolio'], queryFn: api.getCryptoPortfolio, refetchInterval: 30000 });
  const { data: signals } = useQuery({ queryKey: ['crypto-signals'], queryFn: () => api.getCryptoSignals(), refetchInterval: 15000 });

  const scanMut = useMutation({
    mutationFn: api.scanCrypto,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crypto-signals'] });
      queryClient.invalidateQueries({ queryKey: ['crypto-portfolio'] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Crypto Momentum</h1>
        <button
          onClick={() => scanMut.mutate()}
          disabled={scanMut.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50"
        >
          <RefreshCw size={16} className={scanMut.isPending ? 'animate-spin' : ''} />
          {scanMut.isPending ? 'Scanning...' : 'Scan Watchlist'}
        </button>
      </div>

      {/* Portfolio Summary */}
      <div className="grid grid-cols-3 gap-4">
        <Card title="Crypto Positions">
          <p className="text-2xl font-bold text-white">{portfolio?.positions?.length ?? 0}</p>
        </Card>
        <Card title="Total Value">
          <p className="text-2xl font-bold text-white">${portfolio?.total_value?.toFixed(2) ?? '0.00'}</p>
        </Card>
        <Card title="Scan Interval">
          <p className="text-2xl font-bold text-white">15 min</p>
          <p className="text-xs text-slate-500">24/7 trading</p>
        </Card>
      </div>

      {/* Scan Results */}
      {scanMut.data && (
        <Card title={`Scan Results`}>
          <p className="text-sm text-slate-400">
            Scanned {scanMut.data.symbols_scanned} pairs, found {scanMut.data.signals_found} signals
          </p>
          {scanMut.data.decisions?.length > 0 && (
            <div className="mt-2 space-y-1">
              {scanMut.data.decisions.map((d: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-sm bg-slate-800/50 rounded p-2">
                  <span className="text-white font-medium">{d.symbol}</span>
                  <span className={d.action === 'buy' ? 'text-green-400' : d.action === 'sell' ? 'text-red-400' : 'text-slate-400'}>
                    {d.action.toUpperCase()} — {(d.confidence * 100).toFixed(0)}% confidence
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Recent Technical Signals */}
      <Card title="Recent Technical Signals">
        {!signals || signals.length === 0 ? (
          <p className="text-slate-500 text-sm">No signals yet. Start the crypto monitor or run a manual scan.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Pair</th>
                  <th className="text-right py-2">Price</th>
                  <th className="text-right py-2">RSI</th>
                  <th className="text-right py-2">MACD</th>
                  <th className="text-right py-2">BB %B</th>
                  <th className="text-right py-2">Momentum</th>
                  <th className="text-right py-2">Mean Rev</th>
                  <th className="text-right py-2">Composite</th>
                  <th className="text-center py-2">Signal</th>
                  <th className="text-right py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {(signals as any[]).map((s: any, i: number) => {
                  const rsiColor = s.rsi_14 > 70 ? 'text-red-400' : s.rsi_14 < 30 ? 'text-green-400' : 'text-slate-300';
                  const compositeColor = s.composite_signal > 0 ? 'text-green-400' : s.composite_signal < 0 ? 'text-red-400' : 'text-slate-400';
                  return (
                    <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="py-2 text-white font-medium">{s.symbol}</td>
                      <td className="py-2 text-right text-white">${s.current_price?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className={`py-2 text-right ${rsiColor}`}>{s.rsi_14?.toFixed(1) ?? '—'}</td>
                      <td className="py-2 text-right text-slate-300">{s.macd?.toFixed(2) ?? '—'}</td>
                      <td className="py-2 text-right text-slate-300">{s.bb_pct_b?.toFixed(3) ?? '—'}</td>
                      <td className={`py-2 text-right ${s.momentum_score > 0 ? 'text-green-400' : s.momentum_score < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                        {s.momentum_score?.toFixed(3) ?? '—'}
                      </td>
                      <td className={`py-2 text-right ${s.mean_reversion_score > 0 ? 'text-green-400' : s.mean_reversion_score < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                        {s.mean_reversion_score?.toFixed(3) ?? '—'}
                      </td>
                      <td className={`py-2 text-right font-medium ${compositeColor}`}>
                        {s.composite_signal?.toFixed(3) ?? '—'}
                      </td>
                      <td className="py-2 text-center">
                        {s.signal_direction === 'buy' ? (
                          <span className="flex items-center justify-center gap-1 text-green-400"><ArrowUp size={14} /> Buy</span>
                        ) : s.signal_direction === 'sell' ? (
                          <span className="flex items-center justify-center gap-1 text-red-400"><ArrowDown size={14} /> Sell</span>
                        ) : (
                          <span className="flex items-center justify-center gap-1 text-slate-500"><Minus size={14} /> Hold</span>
                        )}
                      </td>
                      <td className="py-2 text-right text-slate-500 text-xs">
                        {new Date(s.created_at).toLocaleTimeString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Crypto Positions */}
      {portfolio?.positions?.length > 0 && (
        <Card title="Open Crypto Positions">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Pair</th>
                  <th className="text-right py-2">Quantity</th>
                  <th className="text-right py-2">Avg Entry</th>
                  <th className="text-right py-2">Current</th>
                  <th className="text-right py-2">Value</th>
                  <th className="text-right py-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {portfolio.positions.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-medium">{p.symbol}</td>
                    <td className="py-2 text-right text-slate-300">{p.quantity?.toFixed(6)}</td>
                    <td className="py-2 text-right text-slate-300">${p.avg_entry_price?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td className="py-2 text-right text-white">${p.current_price?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td className="py-2 text-right text-white">${p.market_value?.toFixed(2)}</td>
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

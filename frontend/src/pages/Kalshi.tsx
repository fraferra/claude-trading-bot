import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronRight, CheckCircle, XCircle } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    executed: 'bg-green-500/20 text-green-400',
    scan_result: 'bg-blue-500/20 text-blue-400',
    pending_execution: 'bg-blue-500/20 text-blue-400',
    rejected_risk: 'bg-red-500/20 text-red-400',
    filtered_edge: 'bg-yellow-500/20 text-yellow-400',
    filtered_signal: 'bg-slate-500/20 text-slate-400',
    llm_vetoed: 'bg-orange-500/20 text-orange-400',
    skipped: 'bg-slate-500/20 text-slate-400',
    settled_win: 'bg-green-500/20 text-green-400',
    settled_loss: 'bg-red-500/20 text-red-400',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[outcome] || 'bg-slate-700 text-slate-300'}`}>
      {outcome.replace(/_/g, ' ')}
    </span>
  );
}

function DecisionRow({ d }: { d: any }) {
  const [expanded, setExpanded] = useState(false);
  let signals: Record<string, any> = {};
  try {
    signals = typeof d.signals_json === 'string' ? JSON.parse(d.signals_json) : d.signals_json || {};
  } catch { signals = {}; }

  return (
    <>
      <tr
        className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="py-2 text-slate-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
        <td className="py-2 text-xs text-slate-500">{new Date(d.created_at).toLocaleTimeString()}</td>
        <td className="py-2 text-white font-mono text-xs">{d.symbol}</td>
        <td className="py-2">
          <span className={d.action === 'buy' ? 'text-green-400' : d.action === 'sell' ? 'text-red-400' : 'text-slate-500'}>
            {d.action?.toUpperCase()}
          </span>
        </td>
        <td className="py-2 text-right text-white">{d.confidence ? `${(d.confidence * 100).toFixed(0)}%` : '—'}</td>
        <td className="py-2 text-center"><OutcomeBadge outcome={d.outcome} /></td>
      </tr>
      {expanded && (
        <tr className="border-b border-slate-800/50">
          <td colSpan={6} className="px-4 py-3 bg-slate-800/20">
            <div className="space-y-2">
              {d.reasoning && (
                <div>
                  <span className="text-xs font-medium text-slate-400">Reasoning:</span>
                  <p className="text-sm text-slate-300 mt-1 whitespace-pre-wrap">{d.reasoning}</p>
                </div>
              )}
              {Object.keys(signals).length > 0 && (
                <div>
                  <span className="text-xs font-medium text-slate-400">Signals:</span>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-1">
                    {Object.entries(signals).map(([key, val]) => (
                      <div key={key} className="text-xs">
                        <span className="text-slate-500">{key}: </span>
                        <span className="text-slate-300">
                          {typeof val === 'number' ? (Math.abs(val) < 1 ? val.toFixed(4) : val.toFixed(2))
                            : typeof val === 'string' ? val.substring(0, 100) : String(val)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {d.trade_id && (
                <div className="text-xs text-slate-500">Trade ID: {d.trade_id}</div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Kalshi() {
  const queryClient = useQueryClient();
  const { data: portfolio } = useQuery({ queryKey: ['kalshi-portfolio'], queryFn: api.getKalshiPortfolio, refetchInterval: 30000 });
  const { data: orders } = useQuery({ queryKey: ['kalshi-orders'], queryFn: () => api.getKalshiOrders(), refetchInterval: 15000 });
  const { data: trades } = useQuery({ queryKey: ['kalshi-trades'], queryFn: () => api.getKalshiTrades(50), refetchInterval: 15000 });
  const { data: estimates } = useQuery({ queryKey: ['kalshi-estimates'], queryFn: () => api.getKalshiEstimates(30), refetchInterval: 15000 });
  const { data: decisions } = useQuery({ queryKey: ['kalshi-decisions'], queryFn: () => api.getKalshiDecisions(50), refetchInterval: 15000 });
  const { data: settlements } = useQuery({ queryKey: ['kalshi-settlements'], queryFn: () => api.getKalshiSettlements(50), refetchInterval: 30000 });

  const restingOrders = orders?.orders?.filter((o: any) => o.status === 'resting') || [];
  const executedOrders = orders?.orders?.filter((o: any) => o.status === 'executed') || [];

  const scanMut = useMutation({
    mutationFn: api.scanKalshi,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['kalshi-estimates'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-decisions'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-orders'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-trades'] });
      queryClient.invalidateQueries({ queryKey: ['kalshi-settlements'] });
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
      {hasPortfolio && (() => {
        const settledPnl = (settlements as any[] || []).reduce((sum: number, s: any) => sum + (s.total_pnl || 0), 0);
        const wins = (settlements as any[] || []).filter((s: any) => s.total_pnl > 0).length;
        const losses = (settlements as any[] || []).filter((s: any) => s.total_pnl <= 0).length;
        return (
          <div className="grid grid-cols-4 gap-4">
            <Card title="Balance">
              <p className="text-2xl font-bold text-white">${portfolio.cash?.toFixed(2) ?? '0.00'}</p>
            </Card>
            <Card title="Total Equity">
              <p className="text-2xl font-bold text-white">${portfolio.equity?.toFixed(2) ?? '0.00'}</p>
            </Card>
            <Card title="Open Positions">
              <p className="text-2xl font-bold text-white">{portfolio.positions?.length ?? 0}</p>
            </Card>
            <Card title="Settled P&L">
              <p className={`text-2xl font-bold ${settledPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {settledPnl >= 0 ? '+' : ''}${settledPnl.toFixed(2)}
              </p>
              {(wins + losses) > 0 && (
                <p className="text-xs text-slate-500 mt-1">
                  <span className="text-green-400">{wins}W</span> / <span className="text-red-400">{losses}L</span>
                </p>
              )}
            </Card>
          </div>
        );
      })()}

      {!hasPortfolio && (
        <Card title="Kalshi Not Connected">
          <p className="text-slate-400">
            {portfolio?.error || 'Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY environment variables to connect.'}
          </p>
        </Card>
      )}

      {/* Resting Orders (unfilled limit orders) */}
      {restingOrders.length > 0 && (
        <Card title={`Open Orders (${restingOrders.length} resting)`}>
          <p className="text-xs text-slate-500 mb-2">Limit orders waiting to be matched on Kalshi</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-center py-2">Action</th>
                  <th className="text-right py-2">Price</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Remaining</th>
                  <th className="text-right py-2">Created</th>
                </tr>
              </thead>
              <tbody>
                {restingOrders.map((o: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs">{o.ticker}</td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${o.side === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                        {o.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-center">
                      <span className={o.action === 'buy' ? 'text-green-400' : 'text-red-400'}>
                        {o.action?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right text-white">
                      {o.yes_price ? `${(o.yes_price * 100).toFixed(0)}c` : o.no_price ? `${(o.no_price * 100).toFixed(0)}c NO` : '—'}
                    </td>
                    <td className="py-2 text-right text-slate-300">{o.count}</td>
                    <td className="py-2 text-right text-yellow-400">{o.remaining_count}</td>
                    <td className="py-2 text-right text-slate-500 text-xs">
                      {o.created_time ? new Date(o.created_time).toLocaleTimeString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Recently Executed Orders */}
      {executedOrders.length > 0 && (
        <Card title={`Filled Orders (${executedOrders.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-center py-2">Action</th>
                  <th className="text-right py-2">Price</th>
                  <th className="text-right py-2">Contracts</th>
                  <th className="text-right py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {executedOrders.slice(0, 20).map((o: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs">{o.ticker}</td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${o.side === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                        {o.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-center">
                      <span className={o.action === 'buy' ? 'text-green-400' : 'text-red-400'}>
                        {o.action?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right text-white">
                      {o.yes_price ? `${(o.yes_price * 100).toFixed(0)}c` : '—'}
                    </td>
                    <td className="py-2 text-right text-slate-300">
                      {o.filled_count || o.count || '—'}
                    </td>
                    <td className="py-2 text-right text-slate-500 text-xs">
                      {o.created_time ? new Date(o.created_time).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Trade History from DB */}
      {trades && (trades as any[]).length > 0 && (
        <Card title={`Trade History (${(trades as any[]).length})`}>
          <p className="text-xs text-slate-500 mb-2">All Kalshi trades placed by the agent (from local DB)</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Price</th>
                  <th className="text-center py-2">Status</th>
                  <th className="text-left py-2">Source</th>
                  <th className="text-right py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {(trades as any[]).map((t: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs">{t.symbol}</td>
                    <td className="py-2 text-center">
                      <span className={t.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                        {t.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right text-slate-300">{t.quantity}</td>
                    <td className="py-2 text-right text-white">
                      {t.filled_price ? `${(t.filled_price * 100).toFixed(0)}c` : '—'}
                    </td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.status === 'filled' ? 'bg-green-500/20 text-green-400'
                          : t.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400'
                          : 'bg-slate-500/20 text-slate-400'
                      }`}>
                        {t.status}
                      </span>
                    </td>
                    <td className="py-2 text-slate-500 text-xs">{t.source}</td>
                    <td className="py-2 text-right text-slate-500 text-xs">
                      {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Scan Results */}
      {scanMut.data && (
        <Card title={`Scan Results — ${scanMut.data.analyzed} markets analyzed`}>
          <p className="text-sm text-slate-400 mb-3">
            Found {scanMut.data.markets_found} markets, analyzed {scanMut.data.analyzed}
          </p>
          {scanMut.data.estimates?.length > 0 && (
            <div className="space-y-2">
              {scanMut.data.estimates.map((e: any, i: number) => {
                const edge = e.edge_pct * 100;
                return (
                  <div key={i} className="p-3 bg-slate-800/50 rounded">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-white font-medium">{e.ticker}</span>
                      <span className={`text-sm font-medium ${edge > 0 ? 'text-green-400' : edge < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                        {edge > 0 ? '+' : ''}{edge.toFixed(1)}% edge
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-1 truncate">{e.title}</p>
                    {e.reasoning && (
                      <p className="text-xs text-slate-500 mt-2 whitespace-pre-wrap">{e.reasoning}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
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

      {/* Decision Log */}
      <Card title={`Decision Log (${decisions?.length || 0})`}>
        {!decisions || decisions.length === 0 ? (
          <p className="text-slate-500 text-sm">No decisions logged yet. Run a scan or start the Kalshi monitor.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="w-6"></th>
                  <th className="text-left py-2">Time</th>
                  <th className="text-left py-2">Market</th>
                  <th className="text-left py-2">Action</th>
                  <th className="text-right py-2">Confidence</th>
                  <th className="text-center py-2">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {(decisions as any[]).map((d: any) => (
                  <DecisionRow key={d.id} d={d} />
                ))}
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

      {/* Settled Bets */}
      <Card title={`Settled Bets (${(settlements as any[] || []).length})`}>
        {!settlements || (settlements as any[]).length === 0 ? (
          <p className="text-slate-500 text-sm">No bets have settled yet. When a market you traded concludes, the payout or loss will appear here.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Market</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Entry</th>
                  <th className="text-center py-2">Result</th>
                  <th className="text-right py-2">Payout/Contract</th>
                  <th className="text-right py-2">Total P&L</th>
                  <th className="text-right py-2">Settled</th>
                </tr>
              </thead>
              <tbody>
                {(settlements as any[]).map((s: any, i: number) => {
                  const isWin = s.total_pnl > 0;
                  return (
                    <tr key={i} className="border-b border-slate-800/50">
                      <td className="py-2 text-white font-mono text-xs">{s.ticker}</td>
                      <td className="py-2 text-center">
                        <span className={s.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                          {s.side?.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-2 text-right text-slate-300">{s.quantity}</td>
                      <td className="py-2 text-right text-slate-300">{(s.entry_price * 100).toFixed(0)}c</td>
                      <td className="py-2 text-center">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                          s.result === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                        }`}>
                          {s.result === 'yes' ? <CheckCircle size={12} /> : <XCircle size={12} />}
                          {s.result?.toUpperCase()}
                        </span>
                      </td>
                      <td className={`py-2 text-right font-medium ${s.payout_per_contract >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {s.payout_per_contract >= 0 ? '+' : ''}{(s.payout_per_contract * 100).toFixed(0)}c
                      </td>
                      <td className={`py-2 text-right font-bold ${isWin ? 'text-green-400' : 'text-red-400'}`}>
                        {isWin ? '+' : ''}${s.total_pnl?.toFixed(2)}
                      </td>
                      <td className="py-2 text-right text-slate-500 text-xs">
                        {s.settled_at ? new Date(s.settled_at).toLocaleString() : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-700">
                  <td colSpan={6} className="py-2 text-right text-slate-400 font-medium">Total Settled P&L:</td>
                  {(() => {
                    const total = (settlements as any[]).reduce((sum: number, s: any) => sum + (s.total_pnl || 0), 0);
                    return (
                      <td className={`py-2 text-right font-bold text-lg ${total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {total >= 0 ? '+' : ''}${total.toFixed(2)}
                      </td>
                    );
                  })()}
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

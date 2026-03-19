import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle, XCircle,
  ChevronDown, ChevronRight, Zap, Link,
} from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';

function PnlBadge({ value }: { value: number }) {
  const positive = value >= 0;
  return (
    <span className={`font-medium ${positive ? 'text-green-400' : 'text-red-400'}`}>
      {positive ? '+' : ''}${value.toFixed(2)}
    </span>
  );
}

function EdgeBadge({ edge }: { edge: number }) {
  const pct = (edge * 100).toFixed(2);
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
      edge >= 0.03 ? 'bg-green-500/20 text-green-400'
      : edge >= 0.01 ? 'bg-yellow-500/20 text-yellow-400'
      : 'bg-slate-500/20 text-slate-400'
    }`}>
      {pct}%
    </span>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    executed: 'bg-green-500/20 text-green-400',
    settled_win: 'bg-green-500/20 text-green-400',
    settled_loss: 'bg-red-500/20 text-red-400',
    rejected_risk: 'bg-red-500/20 text-red-400',
    filtered_stale: 'bg-yellow-500/20 text-yellow-400',
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
        <td className="py-2 text-white font-mono text-xs truncate max-w-[120px]" title={d.symbol}>
          {d.symbol?.substring(0, 16)}…
        </td>
        <td className="py-2">
          <span className={d.action === 'buy' ? 'text-green-400' : d.action === 'sell' ? 'text-red-400' : 'text-slate-400'}>
            {d.action?.toUpperCase()}
          </span>
        </td>
        <td className="py-2 text-right text-white">
          {d.confidence ? `${(d.confidence * 100).toFixed(0)}%` : '—'}
        </td>
        <td className="py-2 text-center"><OutcomeBadge outcome={d.outcome} /></td>
      </tr>
      {expanded && (
        <tr className="border-b border-slate-800/50">
          <td colSpan={6} className="px-4 py-3 bg-slate-800/20">
            <div className="space-y-2">
              {d.reasoning && (
                <div>
                  <span className="text-xs font-medium text-slate-400">Reasoning:</span>
                  <p className="text-sm text-slate-300 mt-1 break-all">{d.reasoning?.substring(0, 400)}</p>
                </div>
              )}
              {Object.keys(signals).length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-1">
                  {Object.entries(signals).map(([key, val]) => (
                    <div key={key} className="text-xs">
                      <span className="text-slate-500">{key}: </span>
                      <span className="text-slate-300">
                        {typeof val === 'number'
                          ? (Math.abs(val) < 1 ? val.toFixed(4) : val.toFixed(2))
                          : String(val).substring(0, 80)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function Polymarket() {
  const queryClient = useQueryClient();

  const { data: portfolio } = useQuery({
    queryKey: ['poly-portfolio'],
    queryFn: api.getPolymarketPortfolio,
    refetchInterval: 30_000,
  });
  const { data: posData } = useQuery({
    queryKey: ['poly-positions'],
    queryFn: api.getPolymarketPositions,
    refetchInterval: 30_000,
  });
  const { data: trades } = useQuery({
    queryKey: ['poly-trades'],
    queryFn: () => api.getPolymarketTrades(50),
    refetchInterval: 15_000,
  });
  const { data: settlements } = useQuery({
    queryKey: ['poly-settlements'],
    queryFn: () => api.getPolymarketSettlements(50),
    refetchInterval: 30_000,
  });
  const { data: pnlData } = useQuery({
    queryKey: ['poly-pnl'],
    queryFn: api.getPolymarketPnlHistory,
    refetchInterval: 60_000,
  });
  const { data: monitorData } = useQuery({
    queryKey: ['poly-monitors'],
    queryFn: api.getPolymarketMonitorStats,
    refetchInterval: 30_000,
  });
  const { data: decisionsData } = useQuery({
    queryKey: ['poly-decisions'],
    queryFn: () => api.getPolymarketDecisions(50),
    refetchInterval: 15_000,
  });
  const { data: pairsData } = useQuery({
    queryKey: ['poly-pairs'],
    queryFn: () => api.getPolymarketCrossPlatformPairs(),
    refetchInterval: 30_000,
  });

  const arbScanMut = useMutation({
    mutationFn: api.scanPolymarketArb,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['poly-decisions'] });
      queryClient.invalidateQueries({ queryKey: ['poly-trades'] });
    },
  });

  const crossScanMut = useMutation({
    mutationFn: api.scanPolymarketCrossPlatform,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['poly-pairs'] });
      queryClient.invalidateQueries({ queryKey: ['poly-decisions'] });
    },
  });

  const positions = posData?.positions || [];
  const settledList: any[] = Array.isArray(settlements) ? settlements : [];
  const tradeList: any[] = Array.isArray(trades) ? trades : [];
  const pnlHistory = pnlData?.pnl_history || [];
  const monitors = monitorData?.monitors || [];
  const decisions: any[] = decisionsData?.decisions || [];
  const pairs: any[] = pairsData?.pairs || [];

  const settledPnl = settledList.reduce((s: number, x: any) => s + (x.total_pnl || 0), 0);
  const wins = settledList.filter((s: any) => s.total_pnl > 0).length;
  const losses = settledList.filter((s: any) => s.total_pnl <= 0).length;
  const hasPortfolio = portfolio && !portfolio.error;

  // Unrealized P&L = sum of position-level unrealized P&L from live market prices
  const unrealizedPnl = positions.reduce((s: number, p: any) => s + (p.unrealized_pnl || 0), 0);
  const totalPnl = unrealizedPnl + settledPnl;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Polymarket Arbitrage</h1>
        <div className="flex gap-2">
          <button
            onClick={() => arbScanMut.mutate()}
            disabled={arbScanMut.isPending}
            className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            <Zap size={14} className={arbScanMut.isPending ? 'animate-pulse' : ''} />
            {arbScanMut.isPending ? 'Scanning…' : 'Arb Scan'}
          </button>
          <button
            onClick={() => crossScanMut.mutate()}
            disabled={crossScanMut.isPending}
            className="flex items-center gap-2 px-3 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 text-sm"
          >
            <Link size={14} className={crossScanMut.isPending ? 'animate-pulse' : ''} />
            {crossScanMut.isPending ? 'Scanning…' : 'Cross-Platform Scan'}
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <Card title="USDC Balance">
          <p className="text-2xl font-bold text-white">
            ${hasPortfolio ? (portfolio.cash || 0).toFixed(2) : '—'}
          </p>
        </Card>
        <Card title="Open Positions">
          <p className="text-2xl font-bold text-white">{positions.length}</p>
          {positions.length > 0 && (
            <p className="text-xs text-slate-500 mt-1">
              ${positions.reduce((s: number, p: any) => s + (p.market_value || 0), 0).toFixed(2)} exposure
            </p>
          )}
        </Card>
        <Card title="Unrealized P&L">
          <p className={`text-2xl font-bold ${unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
          </p>
          <p className="text-xs text-slate-500 mt-1">open positions vs entry</p>
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
        <Card title="Total P&L">
          <p className={`text-2xl font-bold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
          </p>
          <p className="text-xs text-slate-500 mt-1">unrealized + settled</p>
        </Card>
      </div>

      {!hasPortfolio && (
        <Card title="Polymarket Not Connected">
          <p className="text-slate-400 text-sm">
            {portfolio?.error || 'Set POLYMARKET_PRIVATE_KEY and credentials, or enable paper mode.'}
          </p>
        </Card>
      )}

      {/* Monitor Status */}
      {monitors.length > 0 && (
        <Card title="Monitor Status">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {monitors.map((m: any) => (
              <div key={m.monitor_id} className="p-3 bg-slate-800/50 rounded">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-slate-300">{m.monitor_type}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    m.status === 'running' ? 'bg-green-500/20 text-green-400'
                    : m.status === 'paused' ? 'bg-yellow-500/20 text-yellow-400'
                    : 'bg-slate-500/20 text-slate-400'
                  }`}>{m.status}</span>
                </div>
                <div className="text-xs text-slate-500 space-y-0.5">
                  <div>Trades: {m.total_trades}</div>
                  <div>P&L: <PnlBadge value={m.total_pnl || 0} /></div>
                  {m.last_run && <div>Last: {new Date(m.last_run).toLocaleTimeString()}</div>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Cumulative P&L Chart */}
      {pnlHistory.length > 1 && (
        <Card title="Cumulative P&L">
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={pnlHistory} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                tickFormatter={(d) => d.slice(5)}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#94a3b8' }}
                tickFormatter={(v) => `$${v.toFixed(0)}`}
                width={52}
              />
              <Tooltip
                formatter={(v: any) => [`$${Number(v).toFixed(2)}`, 'Cumulative P&L']}
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
                labelStyle={{ color: '#94a3b8', fontSize: 11 }}
              />
              <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
              <Line
                type="monotone"
                dataKey="cumulative_pnl"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* Manual Scan Results */}
      {arbScanMut.data && (
        <Card title={`Arb Scan Results — ${arbScanMut.data.opportunities_found || 0} opportunities`}>
          <p className="text-xs text-slate-500 mb-3">
            Scanned {arbScanMut.data.events_scanned} events
          </p>
          {(arbScanMut.data.opportunities || []).length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-800">
                    <th className="text-left py-2">Event</th>
                    <th className="text-center py-2">Direction</th>
                    <th className="text-right py-2">Price Sum</th>
                    <th className="text-right py-2">Net Edge</th>
                  </tr>
                </thead>
                <tbody>
                  {(arbScanMut.data.opportunities || []).map((o: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/50">
                      <td className="py-2 text-white text-xs">{o.event_title?.substring(0, 60)}</td>
                      <td className="py-2 text-center">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          o.direction === 'buy_all' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                        }`}>{o.direction}</span>
                      </td>
                      <td className="py-2 text-right text-slate-300">{o.price_sum?.toFixed(4)}</td>
                      <td className="py-2 text-right"><EdgeBadge edge={o.edge_pct || 0} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No opportunities found — markets are efficiently priced.</p>
          )}
        </Card>
      )}

      {/* Cross-Platform Scan Results */}
      {crossScanMut.data && (
        <Card title={`Cross-Platform Scan — ${crossScanMut.data.opportunities_found || 0} opportunities`}>
          <p className="text-xs text-slate-500 mb-3">
            {crossScanMut.data.pairs_matched} Polymarket ↔ Kalshi pairs matched
          </p>
          {(crossScanMut.data.opportunities || []).length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-800">
                    <th className="text-left py-2">Polymarket</th>
                    <th className="text-left py-2">Kalshi</th>
                    <th className="text-center py-2">Direction</th>
                    <th className="text-right py-2">Combined Cost</th>
                    <th className="text-right py-2">Net Edge</th>
                  </tr>
                </thead>
                <tbody>
                  {(crossScanMut.data.opportunities || []).map((o: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/50">
                      <td className="py-2 text-white text-xs">{o.poly_question?.substring(0, 40)}</td>
                      <td className="py-2 text-slate-300 text-xs">{o.kalshi_question?.substring(0, 40)}</td>
                      <td className="py-2 text-center">
                        <span className="text-xs text-purple-400">{o.direction?.replace(/_/g, ' ')}</span>
                      </td>
                      <td className="py-2 text-right text-slate-300">{o.combined_cost?.toFixed(4)}</td>
                      <td className="py-2 text-right"><EdgeBadge edge={o.net_edge || 0} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-slate-500 text-sm">No cross-platform opportunities found.</p>
          )}
        </Card>
      )}

      {/* Open Positions */}
      {positions.length > 0 && (
        <Card title={`Open Positions (${positions.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Token ID</th>
                  <th className="text-right py-2">Quantity</th>
                  <th className="text-right py-2">Avg Entry</th>
                  <th className="text-right py-2">Current</th>
                  <th className="text-right py-2">Unrealized P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs truncate max-w-[180px]" title={p.symbol}>
                      {p.symbol?.substring(0, 20)}…
                    </td>
                    <td className="py-2 text-right text-slate-300">{p.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right text-slate-300">${p.avg_entry_price?.toFixed(4)}</td>
                    <td className="py-2 text-right text-white">${p.current_price?.toFixed(4)}</td>
                    <td className="py-2 text-right">
                      <PnlBadge value={p.unrealized_pnl || 0} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Cross-Platform Arb Pairs */}
      {pairs.length > 0 && (
        <Card title={`Cross-Platform Arb Pairs (${pairs.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Created</th>
                  <th className="text-center py-2">Status</th>
                  <th className="text-right py-2">Gross Edge</th>
                  <th className="text-right py-2">Net Edge</th>
                  <th className="text-right py-2">Realized P&L</th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-slate-500 text-xs">
                      {new Date(p.created_at).toLocaleString()}
                    </td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        p.status === 'closed' ? 'bg-green-500/20 text-green-400'
                        : p.status === 'open' ? 'bg-blue-500/20 text-blue-400'
                        : 'bg-yellow-500/20 text-yellow-400'
                      }`}>{p.status}</span>
                    </td>
                    <td className="py-2 text-right"><EdgeBadge edge={p.gross_edge || 0} /></td>
                    <td className="py-2 text-right"><EdgeBadge edge={p.net_edge || 0} /></td>
                    <td className="py-2 text-right">
                      {p.realized_pnl != null ? <PnlBadge value={p.realized_pnl} /> : <span className="text-slate-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Settlement History */}
      <Card title={`Settled Markets (${settledList.length})`}>
        {settledList.length === 0 ? (
          <p className="text-slate-500 text-sm">
            No markets settled yet. Arb profits appear here after market resolution.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Token</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Entry</th>
                  <th className="text-center py-2">Result</th>
                  <th className="text-right py-2">Payout/Share</th>
                  <th className="text-right py-2">Total P&L</th>
                  <th className="text-right py-2">Settled</th>
                </tr>
              </thead>
              <tbody>
                {settledList.map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs truncate max-w-[120px]" title={s.token_id}>
                      {s.token_id?.substring(0, 14)}…
                    </td>
                    <td className="py-2 text-center">
                      <span className={s.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                        {s.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right text-slate-300">{s.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right text-slate-300">${s.entry_price?.toFixed(4)}</td>
                    <td className="py-2 text-center">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${
                        s.result === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                      }`}>
                        {s.result === 'yes' ? <CheckCircle size={12} /> : <XCircle size={12} />}
                        {s.result?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right">
                      <span className={s.payout_per_contract >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {s.payout_per_contract >= 0 ? '+' : ''}${s.payout_per_contract?.toFixed(4)}
                      </span>
                    </td>
                    <td className="py-2 text-right font-bold">
                      <PnlBadge value={s.total_pnl || 0} />
                    </td>
                    <td className="py-2 text-right text-slate-500 text-xs">
                      {s.settled_at ? new Date(s.settled_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-slate-700">
                  <td colSpan={6} className="py-2 text-right text-slate-400 font-medium">Total:</td>
                  <td className="py-2 text-right font-bold text-lg">
                    <PnlBadge value={settledPnl} />
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Card>

      {/* Trade History */}
      {tradeList.length > 0 && (
        <Card title={`Trade History (${tradeList.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Token ID</th>
                  <th className="text-center py-2">Side</th>
                  <th className="text-right py-2">Qty</th>
                  <th className="text-right py-2">Price</th>
                  <th className="text-center py-2">Status</th>
                  <th className="text-left py-2">Strategy</th>
                  <th className="text-right py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {tradeList.map((t: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-white font-mono text-xs truncate max-w-[140px]" title={t.symbol}>
                      {t.symbol?.substring(0, 16)}…
                    </td>
                    <td className="py-2 text-center">
                      <span className={t.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
                        {t.side?.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 text-right text-slate-300">{t.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right text-white">
                      ${t.filled_price?.toFixed(4) ?? '—'}
                    </td>
                    <td className="py-2 text-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        t.status === 'filled' ? 'bg-green-500/20 text-green-400'
                        : t.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400'
                        : 'bg-slate-500/20 text-slate-400'
                      }`}>{t.status}</span>
                    </td>
                    <td className="py-2 text-slate-500 text-xs">{t.strategy_name}</td>
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

      {/* Decision Log */}
      <Card title={`Decision Log (${decisions.length})`}>
        {decisions.length === 0 ? (
          <p className="text-slate-500 text-sm">
            No decisions logged yet. Start the Polymarket arb monitor or run a scan.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="w-6"></th>
                  <th className="text-left py-2">Time</th>
                  <th className="text-left py-2">Token</th>
                  <th className="text-left py-2">Action</th>
                  <th className="text-right py-2">Confidence</th>
                  <th className="text-center py-2">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map((d: any) => (
                  <DecisionRow key={d.id} d={d} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

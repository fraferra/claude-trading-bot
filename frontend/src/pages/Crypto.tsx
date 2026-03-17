import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, ArrowUp, ArrowDown, Minus, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    executed: 'bg-green-500/20 text-green-400',
    scan_result: 'bg-blue-500/20 text-blue-400',
    rejected_risk: 'bg-red-500/20 text-red-400',
    filtered_signal: 'bg-slate-500/20 text-slate-400',
    llm_vetoed: 'bg-orange-500/20 text-orange-400',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[outcome] || 'bg-slate-700 text-slate-300'}`}>
      {outcome.replace(/_/g, ' ')}
    </span>
  );
}

function CryptoDecisionRow({ d }: { d: any }) {
  const [expanded, setExpanded] = useState(false);
  let signals: Record<string, any> = {};
  try {
    signals = typeof d.signals_json === 'string' ? JSON.parse(d.signals_json) : d.signals_json || {};
  } catch { signals = {}; }

  const isLLMOverride = signals.llm_override === true || d.outcome === 'llm_vetoed';

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
        <td className="py-2 text-white font-medium">{d.symbol}</td>
        <td className="py-2">
          <span className={d.action === 'buy' ? 'text-green-400' : d.action === 'sell' ? 'text-red-400' : 'text-slate-500'}>
            {d.action?.toUpperCase()}
          </span>
        </td>
        <td className="py-2 text-right">
          {signals.composite_signal !== undefined ? (
            <span className={`font-mono ${signals.composite_signal > 0 ? 'text-green-400' : signals.composite_signal < 0 ? 'text-red-400' : 'text-slate-400'}`}>
              {Number(signals.composite_signal).toFixed(3)}
            </span>
          ) : '—'}
        </td>
        <td className="py-2 text-right text-white">{d.confidence ? `${(d.confidence * 100).toFixed(0)}%` : '—'}</td>
        <td className="py-2 text-center">
          <div className="flex items-center justify-center gap-1">
            <OutcomeBadge outcome={d.outcome} />
            {isLLMOverride && (
              <span className="px-1.5 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400">LLM</span>
            )}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-slate-800/50">
          <td colSpan={7} className="px-4 py-3 bg-slate-800/20">
            <div className="space-y-2">
              {d.reasoning && (
                <div>
                  <span className="text-xs font-medium text-slate-400">Reasoning:</span>
                  <p className="text-sm text-slate-300 mt-1 whitespace-pre-wrap">{d.reasoning}</p>
                </div>
              )}
              {Object.keys(signals).length > 0 && (
                <div>
                  <span className="text-xs font-medium text-slate-400">Technical Signals:</span>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-1">
                    {signals.rsi_14 != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">RSI: </span>
                        <span className={`${Number(signals.rsi_14) > 70 ? 'text-red-400' : Number(signals.rsi_14) < 30 ? 'text-green-400' : 'text-slate-300'}`}>
                          {Number(signals.rsi_14).toFixed(1)}
                        </span>
                      </div>
                    )}
                    {signals.macd != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">MACD: </span>
                        <span className="text-slate-300">{Number(signals.macd).toFixed(4)}</span>
                      </div>
                    )}
                    {signals.bb_pct_b != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">BB %B: </span>
                        <span className="text-slate-300">{Number(signals.bb_pct_b).toFixed(3)}</span>
                      </div>
                    )}
                    {signals.momentum_score != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">Momentum: </span>
                        <span className={`${Number(signals.momentum_score) > 0 ? 'text-green-400' : Number(signals.momentum_score) < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                          {Number(signals.momentum_score).toFixed(3)}
                        </span>
                      </div>
                    )}
                    {signals.mean_reversion_score != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">Mean Rev: </span>
                        <span className={`${Number(signals.mean_reversion_score) > 0 ? 'text-green-400' : Number(signals.mean_reversion_score) < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                          {Number(signals.mean_reversion_score).toFixed(3)}
                        </span>
                      </div>
                    )}
                    {signals.current_price != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">Price: </span>
                        <span className="text-white">${Number(signals.current_price).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                      </div>
                    )}
                    {signals.qty != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">Qty: </span>
                        <span className="text-slate-300">{Number(signals.qty).toFixed(6)}</span>
                      </div>
                    )}
                    {signals.filled != null && (
                      <div className="text-xs">
                        <span className="text-slate-500">Filled: </span>
                        <span className="text-slate-300">${Number(signals.filled).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              {signals.llm_reasoning && (
                <div>
                  <span className="text-xs font-medium text-purple-400">LLM Reasoning:</span>
                  <p className="text-sm text-slate-300 mt-1">{signals.llm_reasoning}</p>
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

export default function Crypto() {
  const queryClient = useQueryClient();
  const { data: portfolio } = useQuery({ queryKey: ['crypto-portfolio'], queryFn: api.getCryptoPortfolio, refetchInterval: 30000 });
  const { data: signals } = useQuery({ queryKey: ['crypto-signals'], queryFn: () => api.getCryptoSignals(), refetchInterval: 15000 });
  const { data: decisions } = useQuery({ queryKey: ['crypto-decisions'], queryFn: () => api.getCryptoDecisions(50), refetchInterval: 15000 });

  const scanMut = useMutation({
    mutationFn: api.scanCrypto,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['crypto-signals'] });
      queryClient.invalidateQueries({ queryKey: ['crypto-portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['crypto-decisions'] });
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
        <Card title="Scan Results">
          <p className="text-sm text-slate-400 mb-2">
            Scanned {scanMut.data.symbols_scanned} pairs, found {scanMut.data.signals_found} signals
          </p>
          {scanMut.data.decisions?.length > 0 && (
            <div className="space-y-1 mb-3">
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
          {scanMut.data.all_scanned?.length > 0 && (
            <div className="text-xs text-slate-500">
              <p className="font-medium mb-1">Filtered out:</p>
              {scanMut.data.all_scanned.map((s: any, i: number) => (
                <p key={i}>{s.symbol}: {s.filtered_reason}</p>
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
                      <td className="py-2 text-white font-medium">
                        {s.symbol}
                        {s.llm_override && <span className="ml-1 px-1 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400">LLM</span>}
                      </td>
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

      {/* Decision Log */}
      <Card title={`Decision Log (${decisions?.length || 0})`}>
        {!decisions || decisions.length === 0 ? (
          <p className="text-slate-500 text-sm">No decisions logged yet. Run a scan or start the crypto monitor.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="w-6"></th>
                  <th className="text-left py-2">Time</th>
                  <th className="text-left py-2">Pair</th>
                  <th className="text-left py-2">Action</th>
                  <th className="text-right py-2">Signal</th>
                  <th className="text-right py-2">Confidence</th>
                  <th className="text-center py-2">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {(decisions as any[]).map((d: any) => (
                  <CryptoDecisionRow key={d.id} d={d} />
                ))}
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

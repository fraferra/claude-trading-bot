import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Play, Square, Pause, RotateCw } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';
import StatusBadge from '../components/StatusBadge';

const MONITOR_TYPES = [
  { id: 'research_agent', label: 'Research Agent', desc: 'Autonomous stock discovery & trading pipeline' },
  { id: 'strategy_review', label: 'Strategy Review', desc: 'Weekly performance review & parameter tuning' },
  { id: 'stock_watchlist', label: 'Stock Watchlist', desc: 'Score & trade watchlist stocks' },
  { id: 'polymarket_arb', label: 'Polymarket Arbitrage', desc: 'Multi-outcome arbitrage scanner' },
  { id: 'polymarket_probability', label: 'Probability Edge', desc: 'AI probability vs market price' },
  { id: 'cross_market', label: 'Cross-Market', desc: 'Logical arbitrage between markets' },
  { id: 'kalshi_prediction', label: 'Kalshi Prediction', desc: 'Autonomous Kalshi prediction market trading' },
  { id: 'crypto_momentum', label: 'Crypto Momentum', desc: '15-min crypto momentum/mean-reversion strategy' },
];

export default function Monitors() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['monitors'], queryFn: api.getMonitors, refetchInterval: 5000 });

  const startMut = useMutation({
    mutationFn: api.startMonitor,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
  });
  const stopMut = useMutation({
    mutationFn: api.stopMonitor,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
  });
  const pauseMut = useMutation({
    mutationFn: api.pauseMonitor,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
  });
  const resumeMut = useMutation({
    mutationFn: api.resumeMonitor,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['monitors'] }),
  });

  const active = data?.active || [];
  const allStates = data?.all_states || [];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Monitors</h2>

      <Card title="Start New Monitor">
        <div className="grid grid-cols-2 gap-3">
          {MONITOR_TYPES.map((mt) => (
            <button
              key={mt.id}
              onClick={() => startMut.mutate(mt.id)}
              disabled={startMut.isPending}
              className="flex items-center gap-3 p-3 bg-slate-800 hover:bg-slate-700 rounded text-left transition-colors"
            >
              <Play size={16} className="text-green-400 shrink-0" />
              <div>
                <div className="text-sm font-medium text-white">{mt.label}</div>
                <div className="text-xs text-slate-400">{mt.desc}</div>
              </div>
            </button>
          ))}
        </div>
      </Card>

      <Card title={`Active Monitors (${active.length})`}>
        {active.length === 0 ? (
          <p className="text-sm text-slate-500">No active monitors</p>
        ) : (
          <div className="space-y-3">
            {active.map((m: any) => (
              <div key={m.monitor_id} className="flex items-center justify-between p-3 bg-slate-800/50 rounded">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">{m.monitor_id}</span>
                    <StatusBadge status={m.status} />
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">{m.monitor_type}</div>
                </div>
                <div className="flex gap-1">
                  {m.status === 'running' && (
                    <button onClick={() => pauseMut.mutate(m.monitor_id)} className="p-1.5 hover:bg-slate-700 rounded" title="Pause">
                      <Pause size={14} className="text-yellow-400" />
                    </button>
                  )}
                  {m.status === 'paused' && (
                    <button onClick={() => resumeMut.mutate(m.monitor_id)} className="p-1.5 hover:bg-slate-700 rounded" title="Resume">
                      <RotateCw size={14} className="text-green-400" />
                    </button>
                  )}
                  <button onClick={() => stopMut.mutate(m.monitor_id)} className="p-1.5 hover:bg-slate-700 rounded" title="Stop">
                    <Square size={14} className="text-red-400" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {allStates.length > 0 && (
        <Card title="Monitor History">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2">ID</th>
                <th className="pb-2">Type</th>
                <th className="pb-2">Status</th>
                <th className="pb-2 text-right">Trades</th>
                <th className="pb-2 text-right">P&L</th>
                <th className="pb-2 text-right">Scale</th>
              </tr>
            </thead>
            <tbody>
              {allStates.map((s: any) => (
                <tr key={s.monitor_id} className="border-t border-slate-800">
                  <td className="py-2 text-white">{s.monitor_id}</td>
                  <td className="py-2 text-slate-400">{s.monitor_type}</td>
                  <td className="py-2"><StatusBadge status={s.status} /></td>
                  <td className="py-2 text-right">{s.total_trades}</td>
                  <td className={`py-2 text-right ${(s.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${(s.total_pnl || 0).toFixed(2)}
                  </td>
                  <td className="py-2 text-right">{(s.current_position_scale || 1).toFixed(1)}x</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

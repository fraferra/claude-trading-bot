import { useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, Cell, ReferenceLine,
} from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';

function MetricCard({ label, value, sub, color = 'text-white' }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <span className="text-xs text-slate-500 uppercase">{label}</span>
      <div className={`text-xl font-bold mt-1 ${color}`}>{value}</div>
      {sub && <span className="text-xs text-slate-500">{sub}</span>}
    </div>
  );
}

export default function Analytics() {
  const { data: perf } = useQuery({ queryKey: ['performance'], queryFn: () => api.getPerformance() });
  const { data: calendar } = useQuery({ queryKey: ['calendar-returns'], queryFn: api.getCalendarReturns });

  const pnl = perf?.total_realized_pnl ?? 0;
  const kalshiPnl = perf?.kalshi_realized_pnl ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white">Performance Analytics</h2>
        <a
          href="/api/analytics/export-csv"
          download
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded text-sm text-slate-300"
        >
          <Download size={14} /> Export CSV
        </a>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <MetricCard
          label="Realized P&L"
          value={`$${pnl.toFixed(2)}`}
          color={pnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <MetricCard
          label="Kalshi P&L"
          value={`$${kalshiPnl.toFixed(2)}`}
          color={kalshiPnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <MetricCard
          label="Win Rate"
          value={`${perf?.win_rate ?? 0}%`}
          sub={`${perf?.winning_trades ?? 0}W / ${perf?.losing_trades ?? 0}L`}
          color={Number(perf?.win_rate ?? 0) >= 50 ? 'text-green-400' : 'text-red-400'}
        />
        <MetricCard
          label="Sharpe Ratio"
          value={String(perf?.sharpe_ratio ?? 0)}
          color={Number(perf?.sharpe_ratio ?? 0) >= 1 ? 'text-green-400' : 'text-yellow-400'}
        />
        <MetricCard
          label="Sortino Ratio"
          value={String(perf?.sortino_ratio ?? 0)}
        />
        <MetricCard
          label="Max Drawdown"
          value={`$${perf?.max_drawdown_usd ?? 0}`}
          color="text-red-400"
        />
      </div>

      {/* Trade Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Total Trades" value={String(perf?.total_trades ?? 0)} />
        <MetricCard
          label="Avg Win"
          value={`$${perf?.avg_win ?? 0}`}
          color="text-green-400"
        />
        <MetricCard
          label="Avg Loss"
          value={`$${perf?.avg_loss ?? 0}`}
          color="text-red-400"
        />
        <MetricCard
          label="Best Trade"
          value={`$${perf?.best_trade ?? 0}`}
          color="text-green-400"
        />
        <MetricCard
          label="Worst Trade"
          value={`$${perf?.worst_trade ?? 0}`}
          color="text-red-400"
        />
      </div>

      {/* Kalshi Stats */}
      {(perf?.kalshi_wins > 0 || perf?.kalshi_losses > 0) && (
        <div className="grid grid-cols-3 gap-3">
          <MetricCard label="Kalshi Wins" value={String(perf?.kalshi_wins ?? 0)} color="text-green-400" />
          <MetricCard label="Kalshi Losses" value={String(perf?.kalshi_losses ?? 0)} color="text-red-400" />
          <MetricCard label="Kalshi Win Rate" value={`${perf?.kalshi_win_rate ?? 0}%`}
            color={Number(perf?.kalshi_win_rate ?? 0) >= 50 ? 'text-green-400' : 'text-red-400'} />
        </div>
      )}

      {/* Daily Returns Chart */}
      <Card title="Daily Realized Returns">
        {(perf?.daily_returns || []).length === 0 ? (
          <p className="text-sm text-slate-500">No daily return data yet</p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={perf.daily_returns}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" stroke="#64748b" fontSize={11} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v: number) => `$${v}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'P&L']}
              />
              <ReferenceLine y={0} stroke="#475569" />
              <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
                {(perf.daily_returns || []).map((entry: any, i: number) => (
                  <Cell key={i} fill={entry.pnl >= 0 ? '#22c55e' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Card>

      {/* Calendar Heatmap */}
      <Card title="Daily P&L Calendar">
        {(calendar || []).length === 0 ? (
          <p className="text-sm text-slate-500">No calendar data yet</p>
        ) : (
          <div className="grid grid-cols-7 gap-1">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
              <div key={d} className="text-xs text-slate-600 text-center py-1">{d}</div>
            ))}
            {(calendar || []).slice(-90).map((day: any, i: number) => {
              const intensity = Math.min(Math.abs(day.pnl) / 100, 1);
              const bg = day.pnl > 0
                ? `rgba(34, 197, 94, ${0.15 + intensity * 0.6})`
                : day.pnl < 0
                ? `rgba(239, 68, 68, ${0.15 + intensity * 0.6})`
                : 'rgba(100, 116, 139, 0.1)';
              return (
                <div
                  key={i}
                  title={`${day.date}: $${day.pnl.toFixed(2)}`}
                  className="aspect-square rounded text-[9px] flex items-center justify-center text-slate-400"
                  style={{ backgroundColor: bg }}
                >
                  {day.date?.slice(8)}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* P&L by Symbol */}
      <Card title="P&L by Symbol">
        {!perf?.pnl_by_symbol || Object.keys(perf.pnl_by_symbol).length === 0 ? (
          <p className="text-sm text-slate-500">No symbol breakdown yet</p>
        ) : (
          <div className="space-y-2 max-h-64 overflow-auto">
            {Object.entries(perf.pnl_by_symbol).map(([symbol, pnl]: [string, any]) => (
              <div key={symbol} className="flex items-center justify-between text-sm">
                <span className="text-white font-mono">{symbol}</span>
                <span className={Number(pnl) >= 0 ? 'text-green-400' : 'text-red-400'}>
                  ${Number(pnl).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

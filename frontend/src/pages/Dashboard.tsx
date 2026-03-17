import { useQuery } from '@tanstack/react-query';
import { TrendingUp, TrendingDown, DollarSign, BarChart3 } from 'lucide-react';
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid,
} from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';
import StatusBadge from '../components/StatusBadge';

function StatCard({ label, value, icon: Icon, color }: {
  label: string; value: string; icon: any; color: string;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-400">{label}</span>
        <Icon size={18} className={color} />
      </div>
      <div className="mt-2 text-2xl font-bold text-white">{value}</div>
    </div>
  );
}

function PnlChart({ title, data, id, benchmark }: { title: string; data: any[]; id: string; benchmark?: any[] }) {
  if (!data || data.length === 0) {
    return (
      <Card title={title}>
        <p className="text-sm text-slate-500">No P&L data yet</p>
      </Card>
    );
  }

  const lastPoint = data[data.length - 1];
  const totalPnl = lastPoint?.cumulative_pnl ?? 0;
  const isPositive = totalPnl >= 0;
  const color = isPositive ? '#22c55e' : '#ef4444';

  // Merge benchmark data into main data by date for dual-line chart
  const hasBenchmark = benchmark && benchmark.length > 0;
  let chartData = data;
  if (hasBenchmark) {
    const benchMap = new Map(benchmark.map((b: any) => [b.date, b.cumulative_pnl]));
    chartData = data.map((d: any) => ({
      ...d,
      sp500_pnl: benchMap.get(d.date) ?? null,
    }));
  }

  // S&P 500 last value for the header
  const sp500Last = hasBenchmark ? benchmark[benchmark.length - 1]?.cumulative_pnl ?? null : null;

  return (
    <Card
      title={title}
      action={
        <div className="flex items-center gap-3">
          {sp500Last !== null && (
            <span className={`text-xs ${sp500Last >= 0 ? 'text-blue-400' : 'text-blue-300'}`}>
              S&P: {sp500Last >= 0 ? '+' : ''}${sp500Last.toFixed(2)}
            </span>
          )}
          <span className={`text-sm font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}>
            {isPositive ? '+' : ''}${totalPnl.toFixed(2)}
          </span>
        </div>
      }
    >
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chartData}>
          <defs>
            <linearGradient id={`pnlGrad-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis dataKey="date" stroke="#64748b" fontSize={11} tickFormatter={(v: string) => v.slice(5)} />
          <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v: number) => `$${v}`} />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
            formatter={(value: any, name: any) => {
              const label = name === 'sp500_pnl' ? 'S&P 500' : 'Portfolio';
              return [`$${Number(value).toFixed(2)}`, label];
            }}
            labelFormatter={(label: any) => `Date: ${label}`}
          />
          <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
          {hasBenchmark && (
            <Line
              type="monotone"
              dataKey="sp500_pnl"
              stroke="#60a5fa"
              strokeWidth={1.5}
              strokeDasharray="6 3"
              dot={false}
              connectNulls
            />
          )}
          <Area
            type="monotone"
            dataKey="cumulative_pnl"
            stroke={color}
            strokeWidth={2}
            fill={`url(#pnlGrad-${id})`}
          />
        </AreaChart>
      </ResponsiveContainer>
      {hasBenchmark && (
        <div className="flex items-center gap-4 mt-2 text-[10px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 h-0.5" style={{ backgroundColor: color }} /> Portfolio
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-4 h-0.5 border-t border-dashed border-blue-400" /> S&P 500
          </span>
        </div>
      )}
    </Card>
  );
}

export default function Dashboard() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.getPortfolio });
  const { data: positions } = useQuery({ queryKey: ['positions'], queryFn: api.getPositions });
  const { data: trades } = useQuery({ queryKey: ['trades'], queryFn: () => api.getTrades(10) });
  const { data: snapshots } = useQuery({ queryKey: ['snapshots'], queryFn: () => api.getSnapshots() });
  const { data: cumulativePnl } = useQuery({ queryKey: ['cumulative-pnl'], queryFn: api.getCumulativePnl });

  const totalEquity = Object.values(portfolio || {}).reduce(
    (sum: number, p: any) => sum + (p.equity || 0), 0
  );
  const totalCash = Object.values(portfolio || {}).reduce(
    (sum: number, p: any) => sum + (p.cash || 0), 0
  );

  // Daily P&L = sum of each position's intraday unrealized P&L (matches "Today" column)
  const dailyPnl = (positions || []).reduce(
    (sum: number, p: any) => sum + (p.unrealized_intraday_pl || 0), 0
  );
  // Total unrealized P&L = sum of each position's total unrealized P&L (matches "Total P&L" column)
  const totalUnrealizedPnl = (positions || []).reduce(
    (sum: number, p: any) => sum + (p.unrealized_pnl || 0), 0
  );

  const chartData = (snapshots || [])
    .slice(0, 30)
    .reverse()
    .map((s: any) => ({
      date: s.created_at?.slice(5, 10) || '',
      equity: s.equity,
    }));

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Dashboard</h2>

      <div className="grid grid-cols-5 gap-4">
        <StatCard label="Total Equity" value={`$${totalEquity.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} icon={DollarSign} color="text-blue-400" />
        <StatCard label="Cash Available" value={`$${totalCash.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} icon={BarChart3} color="text-slate-400" />
        <StatCard label="Today's P&L" value={`${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`} icon={dailyPnl >= 0 ? TrendingUp : TrendingDown} color={dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
        <StatCard label="Unrealized P&L" value={`${totalUnrealizedPnl >= 0 ? '+' : ''}$${totalUnrealizedPnl.toFixed(2)}`} icon={totalUnrealizedPnl >= 0 ? TrendingUp : TrendingDown} color={totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
        <StatCard label="Open Positions" value={String((positions || []).length)} icon={BarChart3} color="text-purple-400" />
      </div>

      {chartData.length > 1 && (
        <Card title="Equity Over Time">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={chartData}>
              <XAxis dataKey="date" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }} />
              <Line type="monotone" dataKey="equity" stroke="#3b82f6" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <PnlChart title="Stocks — Total P&L" data={cumulativePnl?.alpaca || []} id="stocks" benchmark={cumulativePnl?.sp500} />
        <PnlChart title="Kalshi — Total P&L" data={cumulativePnl?.kalshi || []} id="kalshi" />
        <PnlChart title="Crypto — Total P&L" data={cumulativePnl?.alpaca_crypto || []} id="crypto" />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Card title="Open Positions">
          {(positions || []).length === 0 ? (
            <p className="text-sm text-slate-500">No open positions</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-left">
                  <th className="pb-2">Symbol</th>
                  <th className="pb-2 text-right">Qty</th>
                  <th className="pb-2 text-right">Value</th>
                  <th className="pb-2 text-right">Today</th>
                  <th className="pb-2 text-right">Total P&L</th>
                </tr>
              </thead>
              <tbody>
                {(positions || []).map((p: any, i: number) => (
                  <tr key={i} className="border-t border-slate-800">
                    <td className="py-2 text-white">{p.symbol}</td>
                    <td className="py-2 text-right">{p.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right">${p.market_value?.toFixed(2)}</td>
                    <td className={`py-2 text-right ${(p.unrealized_intraday_pl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${(p.unrealized_intraday_pl || 0)?.toFixed(2)}
                    </td>
                    <td className={`py-2 text-right ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${p.unrealized_pnl?.toFixed(2)}
                    </td>
                  </tr>
                ))}
                {(positions || []).length > 1 && (
                  <tr className="border-t-2 border-slate-700 font-medium">
                    <td className="py-2 text-slate-300">Total</td>
                    <td className="py-2" />
                    <td className="py-2 text-right text-slate-300">
                      ${(positions || []).reduce((s: number, p: any) => s + (p.market_value || 0), 0).toFixed(2)}
                    </td>
                    <td className={`py-2 text-right ${dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${dailyPnl.toFixed(2)}
                    </td>
                    <td className={`py-2 text-right ${totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${totalUnrealizedPnl.toFixed(2)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Recent Trades">
          {(trades || []).length === 0 ? (
            <p className="text-sm text-slate-500">No trades yet</p>
          ) : (
            <div className="space-y-2">
              {(trades || []).slice(0, 5).map((t: any) => (
                <div key={t.id} className="flex items-center justify-between text-sm border-b border-slate-800 pb-2">
                  <div>
                    <span className="text-white">{t.symbol}</span>
                    <StatusBadge status={t.side} />
                  </div>
                  <div className="text-right text-slate-400">
                    {t.quantity} @ ${t.filled_price?.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

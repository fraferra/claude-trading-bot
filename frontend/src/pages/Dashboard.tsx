import { useQuery } from '@tanstack/react-query';
import { TrendingUp, TrendingDown, DollarSign, BarChart3 } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
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

export default function Dashboard() {
  const { data: portfolio } = useQuery({ queryKey: ['portfolio'], queryFn: api.getPortfolio });
  const { data: positions } = useQuery({ queryKey: ['positions'], queryFn: api.getPositions });
  const { data: trades } = useQuery({ queryKey: ['trades'], queryFn: () => api.getTrades(10) });
  const { data: snapshots } = useQuery({ queryKey: ['snapshots'], queryFn: () => api.getSnapshots() });

  const totalEquity = Object.values(portfolio || {}).reduce(
    (sum: number, p: any) => sum + (p.equity || 0), 0
  );
  const totalCash = Object.values(portfolio || {}).reduce(
    (sum: number, p: any) => sum + (p.cash || 0), 0
  );
  const totalPnl = Object.values(portfolio || {}).reduce(
    (sum: number, p: any) => sum + (p.daily_pnl || 0), 0
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

      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Equity" value={`$${totalEquity.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} icon={DollarSign} color="text-blue-400" />
        <StatCard label="Cash Available" value={`$${totalCash.toLocaleString(undefined, { minimumFractionDigits: 2 })}`} icon={BarChart3} color="text-slate-400" />
        <StatCard label="Daily P&L" value={`$${totalPnl.toFixed(2)}`} icon={totalPnl >= 0 ? TrendingUp : TrendingDown} color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'} />
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
                  <th className="pb-2 text-right">P&L</th>
                </tr>
              </thead>
              <tbody>
                {(positions || []).map((p: any, i: number) => (
                  <tr key={i} className="border-t border-slate-800">
                    <td className="py-2 text-white">{p.symbol}</td>
                    <td className="py-2 text-right">{p.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right">${p.market_value?.toFixed(2)}</td>
                    <td className={`py-2 text-right ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      ${p.unrealized_pnl?.toFixed(2)}
                    </td>
                  </tr>
                ))}
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

import { useQuery } from '@tanstack/react-query';
import { Shield, AlertTriangle } from 'lucide-react';
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';

const COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16'];

export default function RiskDashboard() {
  const { data: risk } = useQuery({ queryKey: ['risk-metrics'], queryFn: api.getRiskMetrics, refetchInterval: 30000 });
  const { data: corr } = useQuery({ queryKey: ['correlation'], queryFn: api.getCorrelation });

  const positions = risk?.positions || [];
  const sectors = risk?.sector_exposure || {};
  const sectorData = Object.entries(sectors).map(([name, value]: [string, any], i) => ({
    name, value: Math.abs(value), fill: COLORS[i % COLORS.length],
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white flex items-center gap-2">
        <Shield size={22} /> Risk Dashboard
      </h2>

      {/* Exposure Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {[
          { label: 'Equity', value: `$${(risk?.equity ?? 0).toLocaleString()}` },
          { label: 'Long Exposure', value: `$${(risk?.total_long_value ?? 0).toLocaleString()}`, color: 'text-green-400' },
          { label: 'Short Exposure', value: `$${(risk?.total_short_value ?? 0).toLocaleString()}`, color: 'text-red-400' },
          { label: 'Net Exposure', value: `$${(risk?.net_exposure ?? 0).toLocaleString()}` },
          { label: 'Positions', value: String(risk?.position_count ?? 0) },
          { label: 'Largest %', value: `${risk?.largest_position_pct ?? 0}%`, color: Number(risk?.largest_position_pct ?? 0) > 15 ? 'text-yellow-400' : 'text-white' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
            <span className="text-xs text-slate-500 uppercase">{label}</span>
            <div className={`text-lg font-bold mt-1 ${color || 'text-white'}`}>{value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Sector Pie Chart */}
        <Card title="Sector Exposure">
          {sectorData.length === 0 ? (
            <p className="text-sm text-slate-500">No sector data available</p>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={sectorData}
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  dataKey="value"
                  label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                  fontSize={10}
                >
                  {sectorData.map((entry, i) => (
                    <Cell key={i} fill={entry.fill} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                  formatter={(value: any) => [`$${Number(value).toFixed(2)}`, 'Value']}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Position Concentration */}
        <Card title="Position Concentration">
          {positions.length === 0 ? (
            <p className="text-sm text-slate-500">No positions</p>
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={positions.slice(0, 10)} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis type="number" stroke="#64748b" fontSize={11} tickFormatter={(v: number) => `${v}%`} />
                <YAxis type="category" dataKey="symbol" stroke="#64748b" fontSize={11} width={60} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                  formatter={(value: any) => [`${Number(value).toFixed(1)}%`, 'Portfolio %']}
                />
                <Bar dataKey="pct_of_portfolio" radius={[0, 4, 4, 0]}>
                  {positions.slice(0, 10).map((p: any, i: number) => (
                    <Cell key={i} fill={p.is_short ? '#ef4444' : '#3b82f6'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* Correlation Matrix */}
      <Card title="Correlation Matrix">
        {!corr?.symbols || corr.symbols.length < 2 ? (
          <p className="text-sm text-slate-500">Need 2+ positions for correlation analysis</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="p-1" />
                  {corr.symbols.map((s: string) => (
                    <th key={s} className="p-1 text-slate-400 font-mono">{s}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {corr.symbols.map((row: string) => (
                  <tr key={row}>
                    <td className="p-1 text-slate-400 font-mono">{row}</td>
                    {corr.symbols.map((col: string) => {
                      const val = corr.matrix?.[row]?.[col] ?? 0;
                      const intensity = Math.abs(val);
                      const bg = val > 0.5 ? `rgba(34, 197, 94, ${intensity * 0.6})` :
                        val < -0.5 ? `rgba(239, 68, 68, ${intensity * 0.6})` :
                        'transparent';
                      return (
                        <td key={col} className="p-1 text-center text-slate-300" style={{ backgroundColor: bg }}>
                          {row === col ? '1.00' : val.toFixed(2)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>

            {corr.high_correlation_pairs?.length > 0 && (
              <div className="mt-3 space-y-1">
                <div className="flex items-center gap-1 text-yellow-400 text-xs">
                  <AlertTriangle size={12} /> Highly Correlated Pairs:
                </div>
                {corr.high_correlation_pairs.map((p: any, i: number) => (
                  <div key={i} className="text-xs text-slate-400">
                    {p.pair}: <span className="text-yellow-400">{p.correlation}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* Position Details Table */}
      <Card title="Position Details">
        {positions.length === 0 ? (
          <p className="text-sm text-slate-500">No open positions</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2">Symbol</th>
                <th className="pb-2 text-right">Qty</th>
                <th className="pb-2 text-right">Value</th>
                <th className="pb-2 text-right">% Portfolio</th>
                <th className="pb-2 text-right">P&L</th>
                <th className="pb-2 text-right">P&L %</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any, i: number) => (
                <tr key={i} className="border-t border-slate-800">
                  <td className="py-2 text-white">
                    {p.symbol} {p.is_short && <span className="text-red-400 text-xs">(SHORT)</span>}
                  </td>
                  <td className="py-2 text-right">{p.quantity}</td>
                  <td className="py-2 text-right">${Math.abs(p.market_value).toFixed(2)}</td>
                  <td className="py-2 text-right">{p.pct_of_portfolio}%</td>
                  <td className={`py-2 text-right ${p.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${p.unrealized_pnl.toFixed(2)}
                  </td>
                  <td className={`py-2 text-right ${p.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {p.pnl_pct > 0 ? '+' : ''}{p.pnl_pct}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

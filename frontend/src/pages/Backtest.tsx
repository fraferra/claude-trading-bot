import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { FlaskConical, Play } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';

function InputField({ label, value, onChange, type = 'text', step, help }: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; step?: string; help?: string;
}) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        step={step}
        className="w-full px-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white"
      />
      {help && <p className="text-[10px] text-slate-600 mt-0.5">{help}</p>}
    </div>
  );
}

function MetricBox({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
      <span className="text-xs text-slate-500 uppercase">{label}</span>
      <div className={`text-lg font-bold mt-1 ${color || 'text-white'}`}>{value}</div>
    </div>
  );
}

export default function Backtest() {
  /* ── Parameter state ── */
  const [symbols, setSymbols] = useState('AAPL, MSFT, GOOGL, NVDA, META');
  const [startDate, setStartDate] = useState(() => {
    const d = new Date(); d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [capital, setCapital] = useState('10000');
  const [tradeAmt, setTradeAmt] = useState('500');
  const [stopLoss, setStopLoss] = useState('8');
  const [takeProfit, setTakeProfit] = useState('25');
  const [techWeight, setTechWeight] = useState('0.35');
  const [fundWeight, setFundWeight] = useState('0.35');
  const [momWeight, setMomWeight] = useState('0.30');
  const [buyThreshold, setBuyThreshold] = useState('0.15');
  const [sellThreshold] = useState('-0.15');

  const backtestMut = useMutation({
    mutationFn: (params: Record<string, any>) => api.runBacktest(params),
  });

  const handleRun = () => {
    backtestMut.mutate({
      symbols: symbols.split(',').map((s) => s.trim()).filter(Boolean),
      start_date: startDate,
      end_date: endDate,
      initial_capital: Number(capital),
      trade_amount_usd: Number(tradeAmt),
      stop_loss_pct: Number(stopLoss),
      take_profit_pct: Number(takeProfit),
      technical_weight: Number(techWeight),
      fundamental_weight: Number(fundWeight),
      momentum_weight: Number(momWeight),
      buy_threshold: Number(buyThreshold),
      sell_threshold: Number(sellThreshold),
    });
  };

  const result = backtestMut.data;
  const metrics = result?.metrics;
  const equityCurve = result?.equity_curve || [];
  const trades = result?.trades || [];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white flex items-center gap-2">
        <FlaskConical size={22} /> Backtesting
      </h2>

      {/* Parameter Form */}
      <Card title="Backtest Parameters">
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs text-slate-400 mb-1">Symbols (comma-separated)</label>
              <input
                value={symbols}
                onChange={(e) => setSymbols(e.target.value)}
                className="w-full px-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-sm text-white"
                placeholder="AAPL, MSFT, GOOGL, ..."
              />
            </div>
            <InputField label="Start Date" value={startDate} onChange={setStartDate} type="date" />
            <InputField label="End Date" value={endDate} onChange={setEndDate} type="date" />
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            <InputField label="Initial Capital ($)" value={capital} onChange={setCapital} type="number" />
            <InputField label="Trade Amount ($)" value={tradeAmt} onChange={setTradeAmt} type="number" />
            <InputField label="Stop-Loss %" value={stopLoss} onChange={setStopLoss} type="number" step="0.5" />
            <InputField label="Take-Profit %" value={takeProfit} onChange={setTakeProfit} type="number" step="1" />
            <InputField label="Buy Threshold" value={buyThreshold} onChange={setBuyThreshold} type="number" step="0.05" help="Signal score to buy" />
          </div>

          <div className="grid grid-cols-3 lg:grid-cols-4 gap-3">
            <InputField label="Technical Weight" value={techWeight} onChange={setTechWeight} type="number" step="0.05" />
            <InputField label="Fundamental Weight" value={fundWeight} onChange={setFundWeight} type="number" step="0.05" />
            <InputField label="Momentum Weight" value={momWeight} onChange={setMomWeight} type="number" step="0.05" />
            <div className="flex items-end">
              <button
                onClick={handleRun}
                disabled={backtestMut.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium text-white disabled:opacity-50 w-full justify-center"
              >
                <Play size={16} />
                {backtestMut.isPending ? 'Running...' : 'Run Backtest'}
              </button>
            </div>
          </div>
        </div>
      </Card>

      {backtestMut.isError && (
        <div className="bg-red-900/30 border border-red-800 rounded p-3 text-sm text-red-400">
          Error: {(backtestMut.error as Error).message}
        </div>
      )}

      {/* Results */}
      {metrics && (
        <>
          {/* Metric Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <MetricBox
              label="Total Return"
              value={`${metrics.total_return_pct > 0 ? '+' : ''}${metrics.total_return_pct}%`}
              color={metrics.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}
            />
            <MetricBox
              label="Buy & Hold"
              value={`${metrics.buy_hold_return_pct > 0 ? '+' : ''}${metrics.buy_hold_return_pct}%`}
              color={metrics.buy_hold_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}
            />
            <MetricBox label="Sharpe Ratio" value={String(metrics.sharpe_ratio)} color={metrics.sharpe_ratio > 1 ? 'text-green-400' : 'text-white'} />
            <MetricBox label="Max Drawdown" value={`${metrics.max_drawdown_pct}%`} color={metrics.max_drawdown_pct > 15 ? 'text-red-400' : 'text-yellow-400'} />
            <MetricBox label="Win Rate" value={`${metrics.win_rate}%`} color={metrics.win_rate >= 50 ? 'text-green-400' : 'text-red-400'} />
            <MetricBox label="Final Equity" value={`$${metrics.final_equity.toLocaleString()}`} />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricBox label="Total Trades" value={String(metrics.total_trades)} />
            <MetricBox label="Profit Factor" value={String(metrics.profit_factor)} color={metrics.profit_factor > 1 ? 'text-green-400' : 'text-red-400'} />
            <MetricBox label="Avg Win" value={`$${metrics.avg_win}`} color="text-green-400" />
            <MetricBox label="Avg Loss" value={`$${metrics.avg_loss}`} color="text-red-400" />
          </div>

          {/* Equity Curve */}
          <Card
            title="Equity Curve"
            action={
              <span className="text-xs text-slate-500">
                {result.params.start_date} → {result.params.end_date}
              </span>
            }
          >
            {equityCurve.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={equityCurve}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" stroke="#64748b" fontSize={10} tickFormatter={(v: any) => v.slice(5)} />
                  <YAxis stroke="#64748b" fontSize={11} tickFormatter={(v: any) => `$${Number(v).toLocaleString()}`} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155' }}
                    formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Equity']}
                    labelFormatter={(label: any) => label}
                  />
                  <ReferenceLine y={Number(capital)} stroke="#64748b" strokeDasharray="3 3" label={{ value: 'Start', fill: '#64748b', fontSize: 10 }} />
                  <Area type="monotone" dataKey="equity" stroke="#3b82f6" fill="url(#eqGrad)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-slate-500">No equity data</p>
            )}
          </Card>

          {/* Trade Log */}
          <Card title={`Trade Log (${trades.length} trades)`}>
            {trades.length === 0 ? (
              <p className="text-sm text-slate-500">No trades executed</p>
            ) : (
              <div className="max-h-80 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-slate-900">
                    <tr className="text-slate-500 text-left">
                      <th className="pb-2">Date</th>
                      <th className="pb-2">Symbol</th>
                      <th className="pb-2">Side</th>
                      <th className="pb-2 text-right">Price</th>
                      <th className="pb-2 text-right">Qty</th>
                      <th className="pb-2 text-right">P&L</th>
                      <th className="pb-2">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t: any, i: number) => (
                      <tr key={i} className="border-t border-slate-800">
                        <td className="py-1.5 text-slate-400 text-xs">{t.date}</td>
                        <td className="py-1.5 text-white">{t.symbol}</td>
                        <td className="py-1.5">
                          <span className={`text-xs font-medium ${t.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>
                            {t.side.toUpperCase()}
                          </span>
                        </td>
                        <td className="py-1.5 text-right">${t.price}</td>
                        <td className="py-1.5 text-right">{t.quantity}</td>
                        <td className={`py-1.5 text-right ${t.pnl > 0 ? 'text-green-400' : t.pnl < 0 ? 'text-red-400' : 'text-slate-500'}`}>
                          {t.side === 'sell' ? `$${t.pnl.toFixed(2)}` : '—'}
                        </td>
                        <td className="py-1.5 text-xs text-slate-500">{t.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}

      {!result && !backtestMut.isPending && (
        <Card title="How It Works">
          <div className="text-sm text-slate-400 space-y-2">
            <p>The backtesting engine replays historical price data through the stock scoring strategy:</p>
            <ul className="list-disc list-inside space-y-1 text-slate-500">
              <li><span className="text-slate-300">Technical signals</span> — SMA crossovers, RSI, momentum</li>
              <li><span className="text-slate-300">Fundamental signals</span> — P/E ratio, forward P/E, beta</li>
              <li><span className="text-slate-300">Risk management</span> — Stop-loss, trailing stop, take-profit</li>
              <li><span className="text-slate-300">Weighted scoring</span> — Adjust weights to find optimal parameters</li>
            </ul>
            <p className="text-xs text-slate-600 mt-3">
              Note: Backtests use simplified scoring (no LLM sentiment). Past performance does not guarantee future results.
            </p>
          </div>
        </Card>
      )}
    </div>
  );
}

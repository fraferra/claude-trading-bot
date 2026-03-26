import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Zap, RefreshCw, BarChart2,
  ChevronDown, ChevronRight, ArrowUpDown, Activity,
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { api } from '../api/client';
import Card from '../components/Card';

/* ─── helpers ─────────────────────────────────────────────────── */
function fmt(n: number | undefined, prefix = '$') {
  if (n == null) return '—';
  const abs = Math.abs(n);
  const s = abs >= 1000 ? `${prefix}${(abs / 1000).toFixed(1)}k` : `${prefix}${abs.toFixed(2)}`;
  return n < 0 ? `-${s}` : s;
}

function pct(n: number | undefined) {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function ts(s: string | undefined) {
  if (!s) return '—';
  return new Date(s).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function StatCard({ label, value, sub, color = 'text-white' }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome?: string }) {
  if (!outcome || outcome === 'pending') return <span className="text-xs text-slate-500">pending</span>;
  if (outcome === 'won') return <span className="px-2 py-0.5 rounded text-xs bg-green-900/50 text-green-400">won</span>;
  if (outcome === 'lost') return <span className="px-2 py-0.5 rounded text-xs bg-red-900/50 text-red-400">lost</span>;
  return <span className="px-2 py-0.5 rounded text-xs bg-blue-900/50 text-blue-400">{outcome}</span>;
}

function DecisionRow({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr
        className="border-b border-slate-800/50 hover:bg-slate-800/30 cursor-pointer"
        onClick={() => setOpen(o => !o)}
      >
        <td className="py-2 px-3 text-xs text-slate-500">{ts(d.created_at)}</td>
        <td className="py-2 px-3 text-xs text-slate-300 max-w-[260px] truncate">{d.symbol || '—'}</td>
        <td className="py-2 px-3">
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
            d.action === 'BUY' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
          }`}>{d.action}</span>
        </td>
        <td className="py-2 px-3 text-xs text-slate-300">{d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : '—'}</td>
        <td className="py-2 px-3"><OutcomeBadge outcome={d.outcome} /></td>
        <td className="py-2 px-3 text-slate-500">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-800/20">
          <td colSpan={6} className="px-4 py-3">
            <p className="text-xs text-slate-400 leading-relaxed">{d.reasoning || 'No reasoning.'}</p>
            {d.signals_json && (
              <pre className="text-xs text-slate-500 mt-2 overflow-auto max-h-32 whitespace-pre-wrap">
                {typeof d.signals_json === 'string'
                  ? d.signals_json
                  : JSON.stringify(d.signals_json, null, 2)}
              </pre>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

/* ─── strategy tabs ────────────────────────────────────────────── */
type Tab = 'multi' | 'cross' | 'momentum';

function MultiOutcomeTab() {
  const qc = useQueryClient();
  const { data: arb } = useQuery({ queryKey: ['arb-opps'], queryFn: () => api.getPolymarketArbOpportunities(30), refetchInterval: 15_000 });
  const { data: decisions } = useQuery({ queryKey: ['poly-decisions-arb'], queryFn: () => api.getPolymarketDecisions(50, 'polymarket_arb'), refetchInterval: 15_000 });
  const scan = useMutation({ mutationFn: api.scanPolymarketArb, onSuccess: () => qc.invalidateQueries({ queryKey: ['arb-opps'] }) });

  const items: any[] = decisions?.decisions ?? arb?.opportunities ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          Buys all outcomes when their prices sum to less than $1 — guaranteed profit regardless of resolution.
        </p>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 rounded text-xs text-white"
        >
          <RefreshCw size={13} className={scan.isPending ? 'animate-spin' : ''} />
          {scan.isPending ? 'Scanning…' : 'Scan Now'}
        </button>
      </div>
      {scan.data && (
        <div className="bg-slate-800/50 rounded p-3 text-xs text-slate-300">
          Scanned {scan.data.events_scanned} events → {scan.data.opportunities_found} opportunities found
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-left">
              <th className="py-2 px-3 text-xs text-slate-500">Time</th>
              <th className="py-2 px-3 text-xs text-slate-500">Market</th>
              <th className="py-2 px-3 text-xs text-slate-500">Action</th>
              <th className="py-2 px-3 text-xs text-slate-500">Confidence</th>
              <th className="py-2 px-3 text-xs text-slate-500">Outcome</th>
              <th className="py-2 px-3" />
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-slate-600 text-sm">No executions yet — run a scan to find opportunities.</td></tr>
            )}
            {items.map((d: any, i: number) => <DecisionRow key={i} d={d} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CrossPlatformTab() {
  const qc = useQueryClient();
  const { data: pairs } = useQuery({ queryKey: ['cross-pairs'], queryFn: () => api.getPolymarketCrossPlatformPairs(), refetchInterval: 15_000 });
  const { data: decisions } = useQuery({ queryKey: ['poly-decisions-cross'], queryFn: () => api.getPolymarketDecisions(50, 'cross_platform_arb'), refetchInterval: 15_000 });
  const scan = useMutation({ mutationFn: api.scanPolymarketCrossPlatform, onSuccess: () => qc.invalidateQueries({ queryKey: ['cross-pairs'] }) });

  const pairList: any[] = pairs?.pairs ?? [];
  const decList: any[] = decisions?.decisions ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          Matches equivalent questions on Polymarket and Kalshi, then buys the cheaper side.
        </p>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 rounded text-xs text-white"
        >
          <RefreshCw size={13} className={scan.isPending ? 'animate-spin' : ''} />
          {scan.isPending ? 'Scanning…' : 'Scan Now'}
        </button>
      </div>

      {pairList.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Arb Pairs</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-left">
                  <th className="py-2 px-3 text-xs text-slate-500">Status</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Gross Edge</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Net Edge</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Realized P&L</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Created</th>
                </tr>
              </thead>
              <tbody>
                {pairList.map((p: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${p.status === 'open' ? 'bg-blue-900/50 text-blue-400' : 'bg-slate-700 text-slate-400'}`}>{p.status}</span>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-300">{p.gross_edge != null ? pct(p.gross_edge) : '—'}</td>
                    <td className="py-2 px-3 text-xs text-slate-300">{p.net_edge != null ? pct(p.net_edge) : '—'}</td>
                    <td className={`py-2 px-3 text-xs font-medium ${(p.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{fmt(p.realized_pnl)}</td>
                    <td className="py-2 px-3 text-xs text-slate-500">{ts(p.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div>
        <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Decision Log</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-left">
              <th className="py-2 px-3 text-xs text-slate-500">Time</th>
              <th className="py-2 px-3 text-xs text-slate-500">Market</th>
              <th className="py-2 px-3 text-xs text-slate-500">Action</th>
              <th className="py-2 px-3 text-xs text-slate-500">Confidence</th>
              <th className="py-2 px-3 text-xs text-slate-500">Outcome</th>
              <th className="py-2 px-3" />
            </tr>
          </thead>
          <tbody>
            {decList.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-slate-600 text-sm">No cross-platform trades yet.</td></tr>
            )}
            {decList.map((d: any, i: number) => <DecisionRow key={i} d={d} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MomentumTab() {
  const qc = useQueryClient();
  const { data: signals } = useQuery({ queryKey: ['tm-signals'], queryFn: api.getTemporalMomentumSignals, refetchInterval: 3_000 });
  const { data: decisions } = useQuery({ queryKey: ['tm-decisions'], queryFn: () => api.getTemporalMomentumDecisions(50), refetchInterval: 5_000 });
  const scan = useMutation({ mutationFn: api.scanTemporalMomentum, onSuccess: () => { qc.invalidateQueries({ queryKey: ['tm-signals'] }); qc.invalidateQueries({ queryKey: ['tm-decisions'] }); } });

  const sigs: Record<string, any> = signals?.signals ?? {};
  const opps: any[] = signals?.opportunities ?? [];
  const decs: any[] = decisions?.decisions ?? [];

  const SYMBOLS = ['BTC', 'ETH', 'SOL'];
  const dirColor = (d: string) => d === 'up' ? 'text-green-400' : d === 'down' ? 'text-red-400' : 'text-slate-500';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-400">
          Detects strong BTC/ETH/SOL momentum on Binance and enters Polymarket binary crypto markets before they reprice.
        </p>
        <button
          onClick={() => scan.mutate()}
          disabled={scan.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 rounded text-xs text-white"
        >
          <RefreshCw size={13} className={scan.isPending ? 'animate-spin' : ''} />
          {scan.isPending ? 'Scanning…' : 'Scan Now'}
        </button>
      </div>

      {/* Live momentum gauges */}
      <div className="grid grid-cols-3 gap-3">
        {SYMBOLS.map(sym => {
          const s = sigs[sym] ?? {};
          const strength = (s.strength ?? 0) * 100;
          return (
            <div key={sym} className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-white">{sym}</span>
                <span className={`text-xs font-medium ${dirColor(s.direction)}`}>
                  {s.direction?.toUpperCase() ?? 'FLAT'}
                </span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-1.5 mb-2">
                <div
                  className={`h-1.5 rounded-full transition-all ${s.direction === 'up' ? 'bg-green-500' : s.direction === 'down' ? 'bg-red-500' : 'bg-slate-600'}`}
                  style={{ width: `${strength}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-slate-500">
                <span>Str: {strength.toFixed(0)}%</span>
                <span>1m: {s.change_1m_pct != null ? `${(s.change_1m_pct * 100).toFixed(2)}%` : '—'}</span>
                <span>${s.current_price?.toLocaleString() ?? '—'}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Active opportunities */}
      {opps.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Live Opportunities</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-left">
                  <th className="py-2 px-3 text-xs text-slate-500">Symbol</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Direction</th>
                  <th className="py-2 px-3 text-xs text-slate-500">YES Price</th>
                  <th className="py-2 px-3 text-xs text-slate-500">True Prob</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Edge</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Expiry</th>
                </tr>
              </thead>
              <tbody>
                {opps.map((o: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 px-3 text-xs font-medium text-white">{o.momentum_signal?.symbol ?? '—'}</td>
                    <td className="py-2 px-3 text-xs">
                      <span className={dirColor(o.momentum_signal?.direction)}>{o.momentum_signal?.direction?.toUpperCase() ?? '—'}</span>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-300">{o.market_yes_price != null ? pct(o.market_yes_price) : '—'}</td>
                    <td className="py-2 px-3 text-xs text-slate-300">{o.estimated_true_prob != null ? pct(o.estimated_true_prob) : '—'}</td>
                    <td className="py-2 px-3 text-xs text-green-400">{o.edge_pct != null ? pct(o.edge_pct) : '—'}</td>
                    <td className="py-2 px-3 text-xs text-slate-500">{o.minutes_to_expiry != null ? `${o.minutes_to_expiry.toFixed(1)}m` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Decision log */}
      <div>
        <p className="text-xs text-slate-500 mb-2 uppercase tracking-wider">Decision Log</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-left">
              <th className="py-2 px-3 text-xs text-slate-500">Time</th>
              <th className="py-2 px-3 text-xs text-slate-500">Market</th>
              <th className="py-2 px-3 text-xs text-slate-500">Action</th>
              <th className="py-2 px-3 text-xs text-slate-500">Confidence</th>
              <th className="py-2 px-3 text-xs text-slate-500">Outcome</th>
              <th className="py-2 px-3" />
            </tr>
          </thead>
          <tbody>
            {decs.length === 0 && (
              <tr><td colSpan={6} className="py-6 text-center text-slate-600 text-sm">No momentum trades yet — start the Temporal Momentum monitor.</td></tr>
            )}
            {decs.map((d: any, i: number) => <DecisionRow key={i} d={d} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── main page ────────────────────────────────────────────────── */
export default function ArbDashboard() {
  const [tab, setTab] = useState<Tab>('multi');

  const { data: pnlHistory } = useQuery({ queryKey: ['arb-pnl'], queryFn: api.getPolymarketPnlHistory, refetchInterval: 30_000 });
  const { data: settlements } = useQuery({ queryKey: ['arb-settlements'], queryFn: () => api.getPolymarketSettlements(100), refetchInterval: 30_000 });
  const { data: monitors } = useQuery({ queryKey: ['arb-monitors'], queryFn: api.getPolymarketMonitorStats, refetchInterval: 10_000 });
  const { data: multiDecisions } = useQuery({ queryKey: ['arb-multi-stats'], queryFn: () => api.getPolymarketDecisions(200, 'polymarket_arb'), refetchInterval: 30_000 });
  const { data: crossDecisions } = useQuery({ queryKey: ['arb-cross-stats'], queryFn: () => api.getPolymarketDecisions(200, 'cross_platform_arb'), refetchInterval: 30_000 });
  const { data: tmDecisions } = useQuery({ queryKey: ['arb-tm-stats'], queryFn: () => api.getTemporalMomentumDecisions(200), refetchInterval: 30_000 });

  const settleList: any[] = Array.isArray(settlements) ? settlements : [];

  // Aggregate stats
  const totalPnl = settleList.reduce((s, x) => s + (x.realized_pnl ?? 0), 0);
  const wins = settleList.filter(x => (x.realized_pnl ?? 0) > 0).length;
  const winRate = settleList.length > 0 ? wins / settleList.length : null;

  const allDecs: any[] = [
    ...(multiDecisions?.decisions ?? []),
    ...(crossDecisions?.decisions ?? []),
    ...(tmDecisions?.decisions ?? []),
  ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const activeMonitors: any[] = monitors?.monitors?.filter((m: any) => m.status === 'running') ?? [];

  // P&L chart data
  const chartData = (pnlHistory?.pnl_history ?? []).map((p: any) => ({
    date: p.date ? new Date(p.date).toLocaleDateString([], { month: 'short', day: 'numeric' }) : '?',
    pnl: parseFloat((p.cumulative_pnl ?? 0).toFixed(2)),
  }));

  const TABS: { id: Tab; label: string; icon: React.ComponentType<any> }[] = [
    { id: 'multi', label: 'Multi-Outcome Arb', icon: BarChart2 },
    { id: 'cross', label: 'Cross-Platform', icon: ArrowUpDown },
    { id: 'momentum', label: 'Temporal Momentum', icon: Activity },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white flex items-center gap-2">
          <Zap size={20} className="text-yellow-400" />
          Arbitrage Dashboard
        </h2>
        <p className="text-slate-400 text-sm mt-0.5">Live monitoring across all three arb strategies</p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Arb P&L"
          value={fmt(totalPnl)}
          sub={`${settleList.length} settled markets`}
          color={totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Win Rate"
          value={winRate != null ? `${(winRate * 100).toFixed(0)}%` : '—'}
          sub={`${wins}W / ${settleList.length - wins}L`}
          color="text-blue-400"
        />
        <StatCard
          label="Total Executions"
          value={String(allDecs.filter(d => d.outcome === 'executed' || d.action === 'BUY').length)}
          sub="across all strategies"
          color="text-slate-200"
        />
        <StatCard
          label="Active Arb Monitors"
          value={String(activeMonitors.length)}
          sub={activeMonitors.map((m: any) => m.monitor_type).join(', ') || 'none running'}
          color={activeMonitors.length > 0 ? 'text-green-400' : 'text-slate-500'}
        />
      </div>

      {/* P&L chart */}
      {chartData.length > 0 && (
        <Card title="Cumulative Arb P&L">
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 11, fill: '#64748b' }} tickFormatter={v => `$${v}`} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 12 }}
                formatter={(v: any) => [`$${v}`, 'P&L']}
              />
              <Line type="monotone" dataKey="pnl" stroke="#22c55e" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* Monitor status strip */}
      {activeMonitors.length > 0 && (
        <div className="flex gap-3 flex-wrap">
          {activeMonitors.map((m: any) => (
            <div key={m.id} className="flex items-center gap-2 bg-slate-900 border border-green-800/40 rounded-lg px-3 py-2">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-xs text-slate-300">{m.monitor_type}</span>
              <span className="text-xs text-slate-500">#{m.id?.slice(0, 8)}</span>
              <span className="text-xs text-green-400">{fmt(m.pnl)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Strategy tabs */}
      <Card title="Strategy Breakdown">
        <div className="flex gap-1 mb-4 border-b border-slate-800 pb-2">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors ${
                tab === id
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-800'
              }`}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>
        {tab === 'multi' && <MultiOutcomeTab />}
        {tab === 'cross' && <CrossPlatformTab />}
        {tab === 'momentum' && <MomentumTab />}
      </Card>

      {/* Recent settlements */}
      {settleList.length > 0 && (
        <Card title="Settled Markets">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-left">
                  <th className="py-2 px-3 text-xs text-slate-500">Market</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Result</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Realized P&L</th>
                  <th className="py-2 px-3 text-xs text-slate-500">Settled</th>
                </tr>
              </thead>
              <tbody>
                {settleList.slice(0, 20).map((s: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 px-3 text-xs text-slate-300 max-w-[300px] truncate">{s.question ?? s.token_id ?? '—'}</td>
                    <td className="py-2 px-3">
                      <span className={`px-2 py-0.5 rounded text-xs ${s.result === 'YES' ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'}`}>
                        {s.result ?? '—'}
                      </span>
                    </td>
                    <td className={`py-2 px-3 text-xs font-medium ${(s.realized_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmt(s.realized_pnl)}
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-500">{ts(s.settled_at ?? s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
              {settleList.length > 0 && (
                <tfoot>
                  <tr className="border-t border-slate-700">
                    <td colSpan={2} className="py-2 px-3 text-xs text-slate-500 font-medium">Total</td>
                    <td className={`py-2 px-3 text-xs font-bold ${totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{fmt(totalPnl)}</td>
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, TrendingDown, Check, X, ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

function ScoreBar({ score }: { score: number }) {
  // score is -1.0 to 0.0; wider bar = stronger signal
  const pct = Math.min(100, Math.abs(score) * 100);
  const color = pct > 60 ? 'bg-red-500' : pct > 30 ? 'bg-orange-500' : 'bg-yellow-500';
  return (
    <div className="w-24 h-2 bg-slate-700 rounded overflow-hidden">
      <div className={`h-full ${color} rounded`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: string }) {
  const colors: Record<string, string> = {
    pending_approval: 'bg-amber-500/20 text-amber-400',
    approved: 'bg-green-500/20 text-green-400',
    rejected: 'bg-slate-500/20 text-slate-400',
    rejected_risk: 'bg-red-500/20 text-red-400',
    expired: 'bg-slate-600/20 text-slate-500',
    filtered_score: 'bg-slate-500/20 text-slate-400',
    execution_failed: 'bg-red-500/20 text-red-400',
    rejected_error: 'bg-red-500/20 text-red-400',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[outcome] || 'bg-slate-700 text-slate-300'}`}>
      {outcome.replace(/_/g, ' ')}
    </span>
  );
}

function SignalBreakdown({ signals }: { signals: Record<string, any> }) {
  const breakdown = signals.signal_breakdown || {};
  const entries = Object.entries(breakdown);
  if (entries.length === 0) return <span className="text-slate-500 text-xs">No signals</span>;

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {entries.map(([key, val]) => (
        <div key={key} className="flex justify-between">
          <span className="text-slate-400">{key.replace(/_/g, ' ')}</span>
          <span className={Number(val) < 0 ? 'text-red-400' : 'text-green-400'}>
            {Number(val) > 0 ? '+' : ''}{Number(val).toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function ProposalCard({
  proposal,
  onApprove,
  onReject,
  approving,
}: {
  proposal: any;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  approving: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  let signals: Record<string, any> = {};
  try {
    signals = typeof proposal.signals_json === 'string'
      ? JSON.parse(proposal.signals_json)
      : proposal.signals_json || {};
  } catch { signals = {}; }

  return (
    <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <TrendingDown size={18} className="text-red-400" />
          <span className="font-semibold text-white text-lg">{proposal.symbol}</span>
          <span className="text-slate-400 text-sm">${signals.current_price?.toFixed(2)}</span>
        </div>
        <div className="flex items-center gap-2">
          <ScoreBar score={signals.short_score || 0} />
          <span className="text-red-400 font-mono text-sm">
            {(signals.short_score || 0).toFixed(2)}
          </span>
        </div>
      </div>

      {/* Signal details */}
      <div className="grid grid-cols-4 gap-3 text-xs mb-3">
        {signals.rsi_2 != null && (
          <div>
            <span className="text-slate-500">RSI(2)</span>
            <div className={signals.rsi_2 > 95 ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.rsi_2.toFixed(1)}
            </div>
          </div>
        )}
        {signals.rsi_14 != null && (
          <div>
            <span className="text-slate-500">RSI(14)</span>
            <div className={signals.rsi_14 > 70 ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.rsi_14.toFixed(1)}
            </div>
          </div>
        )}
        {signals.bb_pct_b != null && (
          <div>
            <span className="text-slate-500">BB %B</span>
            <div className={signals.bb_pct_b > 1.0 ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.bb_pct_b.toFixed(3)}
            </div>
          </div>
        )}
        {signals.volume_ratio != null && (
          <div>
            <span className="text-slate-500">Vol Ratio</span>
            <div className={signals.volume_ratio > 1.5 ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.volume_ratio.toFixed(2)}x
            </div>
          </div>
        )}
        {signals.macd_histogram != null && (
          <div>
            <span className="text-slate-500">MACD Hist</span>
            <div className={signals.macd_hist_declining ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.macd_histogram.toFixed(4)}
              {signals.macd_hist_declining && ' (declining)'}
            </div>
          </div>
        )}
        {signals.pe_ratio != null && (
          <div>
            <span className="text-slate-500">P/E</span>
            <div className={signals.pe_ratio > 35 ? 'text-red-400 font-medium' : 'text-slate-300'}>
              {signals.pe_ratio.toFixed(1)}
            </div>
          </div>
        )}
        {signals.atr_14 != null && (
          <div>
            <span className="text-slate-500">ATR(14)</span>
            <div className="text-slate-300">${signals.atr_14.toFixed(2)}</div>
          </div>
        )}
        {signals.price_vs_sma200 != null && (
          <div>
            <span className="text-slate-500">vs SMA200</span>
            <div className={signals.price_vs_sma200 > 0 ? 'text-green-400' : 'text-red-400'}>
              {(signals.price_vs_sma200 * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {/* Expandable breakdown */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 mb-3"
      >
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Signal breakdown
      </button>
      {expanded && (
        <div className="mb-3 p-2 bg-slate-900/50 rounded">
          <SignalBreakdown signals={signals} />
        </div>
      )}

      {/* Time + Actions */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500">
          {new Date(proposal.created_at).toLocaleString()}
        </span>
        <div className="flex gap-2">
          <button
            onClick={() => onReject(proposal.id)}
            disabled={approving}
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm transition-colors disabled:opacity-50"
          >
            <X size={14} /> Reject
          </button>
          <button
            onClick={() => onApprove(proposal.id)}
            disabled={approving}
            className="flex items-center gap-1 px-3 py-1.5 rounded bg-red-600 hover:bg-red-500 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            <Check size={14} /> Approve Short
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Shorts() {
  const qc = useQueryClient();

  const { data: proposals = [], isLoading: loadingProposals } = useQuery({
    queryKey: ['short-proposals'],
    queryFn: () => api.getShortProposals('pending_approval'),
    refetchInterval: 30_000,
  });

  const { data: decisions = [], isLoading: loadingDecisions } = useQuery({
    queryKey: ['short-decisions'],
    queryFn: () => api.getShortDecisions(50),
  });

  const scanMutation = useMutation({
    mutationFn: () => api.scanShorts(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['short-proposals'] });
      qc.invalidateQueries({ queryKey: ['short-decisions'] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: number) => api.approveShort(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['short-proposals'] });
      qc.invalidateQueries({ queryKey: ['short-decisions'] });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: number) => api.rejectShort(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['short-proposals'] });
      qc.invalidateQueries({ queryKey: ['short-decisions'] });
    },
  });

  // Filter decisions to show non-pending ones
  const historyDecisions = decisions.filter(
    (d: any) => d.outcome !== 'pending_approval' && d.outcome !== 'filtered_score',
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-white">Short Proposals</h1>
          <p className="text-sm text-slate-400 mt-1">
            Broad market scan: S&P 500 + NASDAQ-100 → pre-filter overbought → detailed scoring. All shorts require manual approval.
          </p>
        </div>
        <button
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-white transition-colors disabled:opacity-50"
        >
          <RefreshCw size={16} className={scanMutation.isPending ? 'animate-spin' : ''} />
          {scanMutation.isPending ? 'Scanning market...' : 'Scan Market'}
        </button>
      </div>

      {/* Scan result */}
      {scanMutation.data && (
        <div className="bg-slate-800/50 rounded p-3 text-sm text-slate-300">
          Scanned {scanMutation.data.scanned}
          {scanMutation.data.scored != null && ` → ${scanMutation.data.scored} scored`}
          {' → '}<strong className="text-white">{scanMutation.data.proposals} proposals</strong> created
        </div>
      )}

      {/* Error */}
      {(approveMutation.error || rejectMutation.error) && (
        <div className="bg-red-500/10 border border-red-500/30 rounded p-3 text-sm text-red-400">
          {(approveMutation.error as Error)?.message || (rejectMutation.error as Error)?.message}
        </div>
      )}

      {/* Pending Proposals */}
      <Card title={`Pending Proposals (${proposals.length})`}>
        {loadingProposals ? (
          <div className="text-slate-500 text-sm">Loading...</div>
        ) : proposals.length === 0 ? (
          <div className="text-slate-500 text-sm py-4 text-center">
            No pending short proposals. Run a scan or start the Short Candidate monitor.
          </div>
        ) : (
          <div className="space-y-3">
            {proposals.map((p: any) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                onApprove={(id) => approveMutation.mutate(id)}
                onReject={(id) => rejectMutation.mutate(id)}
                approving={approveMutation.isPending}
              />
            ))}
          </div>
        )}
      </Card>

      {/* Decision History */}
      <Card title="Decision History">
        {loadingDecisions ? (
          <div className="text-slate-500 text-sm">Loading...</div>
        ) : historyDecisions.length === 0 ? (
          <div className="text-slate-500 text-sm py-4 text-center">No decision history yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500 border-b border-slate-800">
                  <th className="py-2 font-medium">Time</th>
                  <th className="py-2 font-medium">Symbol</th>
                  <th className="py-2 font-medium">Score</th>
                  <th className="py-2 font-medium">Outcome</th>
                  <th className="py-2 font-medium">Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {historyDecisions.map((d: any) => {
                  let signals: any = {};
                  try {
                    signals = typeof d.signals_json === 'string' ? JSON.parse(d.signals_json) : d.signals_json || {};
                  } catch { signals = {}; }

                  return (
                    <tr key={d.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="py-2 text-slate-400 text-xs">
                        {new Date(d.created_at).toLocaleString()}
                      </td>
                      <td className="py-2 font-medium text-white">{d.symbol}</td>
                      <td className="py-2">
                        <span className="text-red-400 font-mono">
                          {(signals.short_score ?? 0).toFixed(2)}
                        </span>
                      </td>
                      <td className="py-2"><OutcomeBadge outcome={d.outcome} /></td>
                      <td className="py-2 text-slate-400 text-xs max-w-xs truncate">
                        {d.reasoning}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

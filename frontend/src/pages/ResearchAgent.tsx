import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import Card from '../components/Card';
import StatusBadge from '../components/StatusBadge';

export default function ResearchAgent() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'reports' | 'allocation' | 'discoveries' | 'memos'>('reports');

  const { data: status } = useQuery({ queryKey: ['research-status'], queryFn: api.getResearchStatus });
  const { data: reportsData } = useQuery({ queryKey: ['research-reports'], queryFn: () => api.getResearchReports() });
  const { data: allocData } = useQuery({ queryKey: ['research-allocation'], queryFn: api.getCurrentAllocation });
  const { data: discoveriesData } = useQuery({ queryKey: ['research-discoveries'], queryFn: api.getDiscoveries });
  const { data: memosData } = useQuery({ queryKey: ['research-memos'], queryFn: api.getStrategyMemos });

  const runPipeline = useMutation({
    mutationFn: api.triggerResearchRun,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['research-reports'] });
      queryClient.invalidateQueries({ queryKey: ['research-allocation'] });
      queryClient.invalidateQueries({ queryKey: ['research-discoveries'] });
    },
  });

  const runDiscovery = useMutation({
    mutationFn: api.triggerDiscovery,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research-discoveries'] }),
  });

  const reports = reportsData?.reports || [];
  const allocation = allocData?.allocation;
  const discoveries = discoveriesData?.discoveries || [];
  const memos = memosData?.memos || [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Research Agent</h1>
          <p className="text-slate-400 text-sm mt-1">Autonomous stock discovery and portfolio management</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => runDiscovery.mutate()}
            disabled={runDiscovery.isPending}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded disabled:opacity-50"
          >
            {runDiscovery.isPending ? 'Discovering...' : 'Discover Only'}
          </button>
          <button
            onClick={() => runPipeline.mutate()}
            disabled={runPipeline.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded disabled:opacity-50"
          >
            {runPipeline.isPending ? 'Running Pipeline...' : 'Run Full Pipeline'}
          </button>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-4 gap-4">
        <Card title="Status">
          <StatusBadge status={status?.active_monitors?.length > 0 ? 'running' : 'stopped'} />
        </Card>
        <Card title="Scan Interval">
          <p className="text-2xl font-bold text-white">{status?.scan_interval_minutes || 240}m</p>
        </Card>
        <Card title="Reports">
          <p className="text-2xl font-bold text-white">{reports.length}</p>
        </Card>
        <Card title="Positions">
          <p className="text-2xl font-bold text-white">
            {allocation?.entries?.filter((e: any) => e.target_weight > 0).length || 0}
            <span className="text-sm text-slate-400">/{status?.max_positions || 10}</span>
          </p>
        </Card>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 border-b border-slate-800">
        {(['reports', 'allocation', 'discoveries', 'memos'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize ${
              activeTab === tab
                ? 'text-white border-b-2 border-blue-500'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {tab === 'memos' ? 'Strategy Memos' : tab}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'reports' && (
        <Card title={`Research Reports (${reports.length})`}>
          {reports.length === 0 ? (
            <p className="text-slate-400">No reports yet. Run the pipeline to generate research.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-800">
                  <th className="text-left py-2">Symbol</th>
                  <th className="text-left py-2">Company</th>
                  <th className="text-left py-2">Sector</th>
                  <th className="text-right py-2">Score</th>
                  <th className="text-left py-2">Rec</th>
                  <th className="text-right py-2">Weight</th>
                  <th className="text-left py-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {reports.slice(0, 20).map((r: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/50">
                    <td className="py-2 text-cyan-400 font-mono">{r.symbol}</td>
                    <td className="py-2 text-white">{r.company_name || '-'}</td>
                    <td className="py-2 text-slate-400">{r.sector || '-'}</td>
                    <td className={`py-2 text-right font-bold ${
                      r.composite_score >= 7 ? 'text-green-400' : r.composite_score >= 5 ? 'text-yellow-400' : 'text-red-400'
                    }`}>
                      {r.composite_score?.toFixed(1)}
                    </td>
                    <td className="py-2">
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        r.recommendation?.includes('buy') ? 'bg-green-900 text-green-300' :
                        r.recommendation?.includes('sell') ? 'bg-red-900 text-red-300' :
                        'bg-slate-700 text-slate-300'
                      }`}>
                        {r.recommendation}
                      </span>
                    </td>
                    <td className="py-2 text-right text-white">{(r.target_weight * 100).toFixed(1)}%</td>
                    <td className="py-2 text-slate-500 text-xs">{r.created_at?.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      {activeTab === 'allocation' && (
        <Card title="Current Target Allocation">
          {!allocation ? (
            <p className="text-slate-400">No allocation yet. Run the pipeline to generate one.</p>
          ) : (
            <>
              <div className="flex gap-4 mb-4 text-sm">
                <span className="text-slate-400">Cash Reserve: <span className="text-white">{(allocation.cash_reserve * 100).toFixed(1)}%</span></span>
                <span className="text-slate-400">Rebalance: <StatusBadge status={allocation.rebalance_needed ? 'running' : 'stopped'} /></span>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-800">
                    <th className="text-left py-2">Symbol</th>
                    <th className="text-right py-2">Target %</th>
                    <th className="text-right py-2">Current %</th>
                    <th className="text-right py-2">Score</th>
                    <th className="text-left py-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(allocation.entries || []).map((e: any, i: number) => (
                    <tr key={i} className="border-b border-slate-800/50">
                      <td className="py-2 text-cyan-400 font-mono">{e.symbol}</td>
                      <td className="py-2 text-right text-white">{(e.target_weight * 100).toFixed(1)}%</td>
                      <td className="py-2 text-right text-slate-400">{(e.current_weight * 100).toFixed(1)}%</td>
                      <td className="py-2 text-right text-white">{e.research_score?.toFixed(1)}</td>
                      <td className="py-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${
                          e.action === 'buy' || e.action === 'add' ? 'bg-green-900 text-green-300' :
                          e.action === 'sell' || e.action === 'trim' ? 'bg-red-900 text-red-300' :
                          'bg-slate-700 text-slate-300'
                        }`}>
                          {e.action?.toUpperCase()}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {allocation.reasoning && (
                <p className="mt-3 text-xs text-slate-400">{allocation.reasoning}</p>
              )}
            </>
          )}
        </Card>
      )}

      {activeTab === 'discoveries' && (
        <Card title={`Discovery Runs (${discoveries.length})`}>
          {discoveries.length === 0 ? (
            <p className="text-slate-400">No discovery runs yet.</p>
          ) : (
            <div className="space-y-4">
              {discoveries.slice(0, 10).map((d: any, i: number) => (
                <div key={i} className="border border-slate-800 rounded p-3">
                  <div className="flex justify-between text-xs text-slate-400 mb-2">
                    <span>{d.num_candidates} candidates found</span>
                    <span>{d.created_at?.slice(0, 16)}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(d.candidates || []).map((c: any, j: number) => (
                      <span key={j} className="px-2 py-1 bg-slate-800 rounded text-xs text-cyan-400" title={c.reason}>
                        {c.symbol}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {activeTab === 'memos' && (
        <Card title={`Strategy Memos (${memos.length})`}>
          {memos.length === 0 ? (
            <p className="text-slate-400">No strategy reviews yet. The strategist runs weekly.</p>
          ) : (
            <div className="space-y-4">
              {memos.map((m: any, i: number) => (
                <div key={i} className="border border-slate-800 rounded p-4">
                  <div className="flex justify-between mb-2">
                    <span className="text-white font-medium">
                      {m.period_start?.slice(0, 10)} to {m.period_end?.slice(0, 10)}
                    </span>
                    <span className={`text-sm font-bold ${m.total_return_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {m.total_return_pct >= 0 ? '+' : ''}{m.total_return_pct?.toFixed(1)}%
                    </span>
                  </div>
                  <div className="text-sm text-slate-400 mb-2">
                    Win rate: {(m.win_rate * 100).toFixed(0)}%
                  </div>
                  {m.lessons?.length > 0 && (
                    <div className="mt-2">
                      <span className="text-xs text-slate-500">Lessons:</span>
                      <ul className="list-disc list-inside text-xs text-slate-400 mt-1">
                        {m.lessons.map((l: string, j: number) => <li key={j}>{l}</li>)}
                      </ul>
                    </div>
                  )}
                  {Object.keys(m.parameter_changes || {}).length > 0 && (
                    <div className="mt-2 text-xs text-yellow-400">
                      Parameter changes: {JSON.stringify(m.parameter_changes)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

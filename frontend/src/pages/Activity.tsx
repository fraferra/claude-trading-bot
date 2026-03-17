import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import Card from '../components/Card';
import StatusBadge from '../components/StatusBadge';

function ReasoningTooltip({ text }: { text: string | null | undefined }) {
  const [open, setOpen] = useState(false);

  if (!text) return <span className="text-slate-600">—</span>;

  return (
    <span className="relative inline-block">
      <button
        className="text-left text-slate-400 text-xs hover:text-blue-400 cursor-pointer transition-colors max-w-[200px] truncate block"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen(!open)}
      >
        {text.slice(0, 60)}...
      </button>
      {open && (
        <div className="absolute z-50 bottom-full left-0 mb-2 w-80 max-h-60 overflow-y-auto p-3 rounded-lg bg-slate-800 border border-slate-700 shadow-xl text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
          <div className="text-xs text-slate-500 mb-1 font-medium">Reasoning</div>
          {text}
          <div className="absolute bottom-0 left-4 translate-y-full w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-slate-700" />
        </div>
      )}
    </span>
  );
}

export default function Activity() {
  const { data: trades } = useQuery({ queryKey: ['trades'], queryFn: () => api.getTrades(50) });
  const { data: decisions } = useQuery({ queryKey: ['decisions'], queryFn: () => api.getDecisions(50) });

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Activity</h2>

      <Card title={`Trade History (${(trades || []).length})`}>
        {(trades || []).length === 0 ? (
          <p className="text-sm text-slate-500">No trades yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-500 text-left">
                  <th className="pb-2">Time</th>
                  <th className="pb-2">Symbol</th>
                  <th className="pb-2">Side</th>
                  <th className="pb-2 text-right">Qty</th>
                  <th className="pb-2 text-right">Price</th>
                  <th className="pb-2">Platform</th>
                  <th className="pb-2">Source</th>
                  <th className="pb-2">Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {(trades || []).map((t: any) => (
                  <tr key={t.id} className="border-t border-slate-800">
                    <td className="py-2 text-slate-400 text-xs">{t.created_at?.slice(5, 16)}</td>
                    <td className="py-2 text-white">{t.symbol?.slice(0, 20)}</td>
                    <td className="py-2"><StatusBadge status={t.side} /></td>
                    <td className="py-2 text-right">{t.quantity?.toFixed(2)}</td>
                    <td className="py-2 text-right">
                      {t.filled_price != null
                        ? `$${t.filled_price.toFixed(2)}`
                        : <span className="text-yellow-400">Pending</span>}
                    </td>
                    <td className="py-2 text-slate-400">{t.platform}</td>
                    <td className="py-2 text-slate-400">{t.source}</td>
                    <td className="py-2">
                      <ReasoningTooltip text={t.reasoning} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title={`Decision Log (${(decisions || []).length})`}>
        {(decisions || []).length === 0 ? (
          <p className="text-sm text-slate-500">No decisions yet</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pb-2">Time</th>
                <th className="pb-2">Symbol</th>
                <th className="pb-2">Action</th>
                <th className="pb-2 text-right">Confidence</th>
                <th className="pb-2">Executed</th>
                <th className="pb-2">Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {(decisions || []).map((d: any) => (
                <tr key={d.id} className="border-t border-slate-800">
                  <td className="py-2 text-slate-400 text-xs">{d.created_at?.slice(5, 16)}</td>
                  <td className="py-2 text-white">{d.symbol}</td>
                  <td className="py-2"><StatusBadge status={d.action} /></td>
                  <td className="py-2 text-right">{(d.confidence * 100).toFixed(0)}%</td>
                  <td className="py-2">{d.was_executed ? 'Yes' : 'No'}</td>
                  <td className="py-2">
                    <ReasoningTooltip text={d.reasoning} />
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

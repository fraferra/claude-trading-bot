import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import Card from '../components/Card';
import StatusBadge from '../components/StatusBadge';

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
                </tr>
              ))}
            </tbody>
          </table>
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
                  <td className="py-2 text-slate-400 text-xs max-w-xs truncate">{d.reasoning?.slice(0, 60)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

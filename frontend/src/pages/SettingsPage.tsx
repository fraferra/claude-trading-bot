import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: config } = useQuery({ queryKey: ['config'], queryFn: api.getConfig });
  const [saved, setSaved] = useState(false);

  const updateConfig = useMutation({
    mutationFn: api.updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const [watchlist, setWatchlist] = useState('');
  const [maxTradesPerDay, setMaxTradesPerDay] = useState('');
  const [minConfidence, setMinConfidence] = useState('');
  const [maxPositionPct, setMaxPositionPct] = useState('');

  // Initialize from config
  if (config && !watchlist) {
    setWatchlist(config.stocks?.watchlist?.join(', ') || '');
    setMaxTradesPerDay(String(config.risk?.max_trades_per_day || 10));
    setMinConfidence(String(config.risk?.min_confidence || 0.6));
    setMaxPositionPct(String(config.risk?.max_position_pct || 0.1));
  }

  const handleSave = () => {
    updateConfig.mutate({
      risk: {
        max_trades_per_day: Number(maxTradesPerDay),
        min_confidence: Number(minConfidence),
        max_position_pct: Number(maxPositionPct),
      },
      stocks: {
        watchlist: watchlist.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
      },
    });
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-white">Settings</h2>

      <Card title="Risk Management">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1">Max Trades/Day</label>
            <input
              value={maxTradesPerDay}
              onChange={(e) => setMaxTradesPerDay(e.target.value)}
              type="number"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Min Confidence</label>
            <input
              value={minConfidence}
              onChange={(e) => setMinConfidence(e.target.value)}
              type="number"
              step="0.05"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Max Position %</label>
            <input
              value={maxPositionPct}
              onChange={(e) => setMaxPositionPct(e.target.value)}
              type="number"
              step="0.01"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            />
          </div>
        </div>
      </Card>

      <Card title="Stock Watchlist">
        <div>
          <label className="block text-sm text-slate-400 mb-1">Symbols (comma-separated)</label>
          <input
            value={watchlist}
            onChange={(e) => setWatchlist(e.target.value)}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
            placeholder="AAPL, MSFT, GOOGL, ..."
          />
        </div>
      </Card>

      <button
        onClick={handleSave}
        disabled={updateConfig.isPending}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium text-white disabled:opacity-50"
      >
        <Save size={16} />
        {saved ? 'Saved!' : 'Save Settings'}
      </button>

      {config && (
        <Card title="Full Configuration (Read-only)">
          <pre className="text-xs text-slate-400 overflow-auto max-h-64 whitespace-pre-wrap">
            {JSON.stringify(config, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}

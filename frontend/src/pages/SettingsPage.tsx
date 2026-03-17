import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, Download, RotateCw } from 'lucide-react';
import { api } from '../api/client';
import Card from '../components/Card';

/* ─── tiny helpers ─────────────────────────────────────────────── */
function InputField({ label, value, onChange, type = 'text', step, placeholder, help }: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; step?: string; placeholder?: string; help?: string;
}) {
  return (
    <div>
      <label className="block text-sm text-slate-400 mb-1">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        step={step}
        placeholder={placeholder}
        className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-sm text-white"
      />
      {help && <p className="text-xs text-slate-600 mt-0.5">{help}</p>}
    </div>
  );
}

function Toggle({ label, checked, onChange, help }: {
  label: string; checked: boolean; onChange: (v: boolean) => void; help?: string;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <div
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full relative transition-colors ${checked ? 'bg-blue-600' : 'bg-slate-700'}`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${checked ? 'left-[18px]' : 'left-0.5'}`} />
      </div>
      <span className="text-sm text-slate-300">{label}</span>
      {help && <span className="text-xs text-slate-600">({help})</span>}
    </label>
  );
}

/* ─── main component ───────────────────────────────────────────── */
export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery({ queryKey: ['config'], queryFn: api.getConfig });
  const [saved, setSaved] = useState(false);
  const [initialized, setInitialized] = useState(false);

  /* ── Risk ── */
  const [maxTradesPerDay, setMaxTradesPerDay] = useState('10');
  const [minConfidence, setMinConfidence] = useState('0.6');
  const [maxPositionPct, setMaxPositionPct] = useState('0.1');
  const [maxPortfolioRisk, setMaxPortfolioRisk] = useState('0.25');

  /* ── Stocks ── */
  const [watchlist, setWatchlist] = useState('');
  const [tradeAmountUsd, setTradeAmountUsd] = useState('500');

  /* ── Position Guard ── */
  const [pgEnabled, setPgEnabled] = useState(true);
  const [pgScanInterval, setPgScanInterval] = useState('5');
  const [pgStopLoss, setPgStopLoss] = useState('8');
  const [pgTrailingStop, setPgTrailingStop] = useState('12');
  const [pgTakeProfit, setPgTakeProfit] = useState('25');
  const [pgPartialTP, setPgPartialTP] = useState(true);
  const [pgPartialFrac, setPgPartialFrac] = useState('0.5');
  const [pgExclude, setPgExclude] = useState('');
  const [pgShorts, setPgShorts] = useState(true);

  /* ── Telegram ── */
  const [tgEnabled, setTgEnabled] = useState(false);
  const [tgToken, setTgToken] = useState('');
  const [tgChatId, setTgChatId] = useState('');
  const [tgTrades, setTgTrades] = useState(true);
  const [tgErrors, setTgErrors] = useState(true);
  const [tgStopLoss, setTgStopLoss] = useState(true);
  const [tgDailySummary, setTgDailySummary] = useState(true);
  const [tgSummaryHour, setTgSummaryHour] = useState('17');

  /* ── Kalshi ── */
  const [kalshiEnabled, setKalshiEnabled] = useState(false);
  const [kalshiDefaultSize, setKalshiDefaultSize] = useState('25');
  const [kalshiMaxOpen, setKalshiMaxOpen] = useState('200');
  const [kalshiMinEdge, setKalshiMinEdge] = useState('0.08');

  /* ── Crypto ── */
  const [cryptoEnabled, setCryptoEnabled] = useState(false);
  const [cryptoSymbols, setCryptoSymbols] = useState('');
  const [cryptoTradeSize, setCryptoTradeSize] = useState('100');

  /* ── Shorts ── */
  const [shortsEnabled, setShortsEnabled] = useState(false);
  const [shortsMaxPositions, setShortsMaxPositions] = useState('3');
  const [shortsMaxPct, setShortsMaxPct] = useState('0.15');

  /* ── Drawdown Accumulation ── */
  const [daEnabled, setDaEnabled] = useState(false);
  const [daBaseBuy, setDaBaseBuy] = useState('100');
  const [daMaxDrawdownMultiplier, setDaMaxDrawdownMultiplier] = useState('5');

  /* ── Research Agent ── */
  const [raEnabled, setRaEnabled] = useState(true);
  const [raMaxPositions, setRaMaxPositions] = useState('12');
  const [raMaxPositionPct, setRaMaxPositionPct] = useState('0.12');

  const updateConfig = useMutation({
    mutationFn: api.updateConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  /* Init from loaded config */
  useEffect(() => {
    if (!config || initialized) return;
    setInitialized(true);

    // Risk
    setMaxTradesPerDay(String(config.risk?.max_trades_per_day ?? 10));
    setMinConfidence(String(config.risk?.min_confidence ?? 0.6));
    setMaxPositionPct(String(config.risk?.max_position_pct ?? 0.1));
    setMaxPortfolioRisk(String(config.risk?.max_portfolio_risk_pct ?? 0.25));

    // Stocks
    setWatchlist(config.stocks?.watchlist?.join(', ') ?? '');
    setTradeAmountUsd(String(config.stocks?.trade_amount_usd ?? 500));

    // Position Guard
    const pg = config.position_guard ?? {};
    setPgEnabled(pg.enabled ?? true);
    setPgScanInterval(String(pg.scan_interval_minutes ?? 5));
    setPgStopLoss(String(pg.stop_loss_pct ?? 8));
    setPgTrailingStop(String(pg.trailing_stop_pct ?? 12));
    setPgTakeProfit(String(pg.take_profit_pct ?? 25));
    setPgPartialTP(pg.partial_take_profit ?? true);
    setPgPartialFrac(String(pg.partial_take_fraction ?? 0.5));
    setPgExclude((pg.exclude_symbols ?? []).join(', '));
    setPgShorts(pg.enable_for_shorts ?? true);

    // Telegram
    const tg = config.telegram ?? {};
    setTgEnabled(tg.enabled ?? false);
    setTgToken(tg.bot_token ?? '');
    setTgChatId(tg.chat_id ?? '');
    setTgTrades(tg.notify_trades ?? true);
    setTgErrors(tg.notify_errors ?? true);
    setTgStopLoss(tg.notify_stop_loss ?? true);
    setTgDailySummary(tg.daily_summary ?? true);
    setTgSummaryHour(String(tg.daily_summary_hour ?? 17));

    // Kalshi
    const k = config.kalshi ?? {};
    setKalshiEnabled(k.enabled ?? false);
    setKalshiDefaultSize(String(k.default_size_usd ?? 25));
    setKalshiMaxOpen(String(k.max_open_exposure_usd ?? 200));
    setKalshiMinEdge(String(k.min_edge ?? 0.08));

    // Crypto
    const cr = config.crypto ?? {};
    setCryptoEnabled(cr.enabled ?? false);
    setCryptoSymbols((cr.symbols ?? []).join(', '));
    setCryptoTradeSize(String(cr.trade_size_usd ?? 100));

    // Shorts
    const sh = config.shorts ?? {};
    setShortsEnabled(sh.enabled ?? false);
    setShortsMaxPositions(String(sh.max_positions ?? 3));
    setShortsMaxPct(String(sh.max_portfolio_pct ?? 0.15));

    // Drawdown Accumulation
    const da = config.drawdown_accumulation ?? {};
    setDaEnabled(da.enabled ?? false);
    setDaBaseBuy(String(da.base_buy_usd ?? 100));
    setDaMaxDrawdownMultiplier(String(da.max_drawdown_multiplier ?? 5));

    // Research Agent
    const ra = config.research_agent ?? {};
    setRaEnabled(ra.enabled ?? true);
    setRaMaxPositions(String(ra.max_positions ?? 12));
    setRaMaxPositionPct(String(ra.max_position_pct ?? 0.12));
  }, [config, initialized]);

  const handleSave = () => {
    updateConfig.mutate({
      risk: {
        max_trades_per_day: Number(maxTradesPerDay),
        min_confidence: Number(minConfidence),
        max_position_pct: Number(maxPositionPct),
        max_portfolio_risk_pct: Number(maxPortfolioRisk),
      },
      stocks: {
        watchlist: watchlist.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        trade_amount_usd: Number(tradeAmountUsd),
      },
      position_guard: {
        enabled: pgEnabled,
        scan_interval_minutes: Number(pgScanInterval),
        stop_loss_pct: Number(pgStopLoss),
        trailing_stop_pct: Number(pgTrailingStop),
        take_profit_pct: Number(pgTakeProfit),
        partial_take_profit: pgPartialTP,
        partial_take_fraction: Number(pgPartialFrac),
        exclude_symbols: pgExclude.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        enable_for_shorts: pgShorts,
      },
      telegram: {
        enabled: tgEnabled,
        bot_token: tgToken,
        chat_id: tgChatId,
        notify_trades: tgTrades,
        notify_errors: tgErrors,
        notify_stop_loss: tgStopLoss,
        daily_summary: tgDailySummary,
        daily_summary_hour: Number(tgSummaryHour),
      },
      kalshi: {
        enabled: kalshiEnabled,
        default_size_usd: Number(kalshiDefaultSize),
        max_open_exposure_usd: Number(kalshiMaxOpen),
        min_edge: Number(kalshiMinEdge),
      },
      crypto: {
        enabled: cryptoEnabled,
        symbols: cryptoSymbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        trade_size_usd: Number(cryptoTradeSize),
      },
      shorts: {
        enabled: shortsEnabled,
        max_positions: Number(shortsMaxPositions),
        max_portfolio_pct: Number(shortsMaxPct),
      },
      drawdown_accumulation: {
        enabled: daEnabled,
        base_buy_usd: Number(daBaseBuy),
        max_drawdown_multiplier: Number(daMaxDrawdownMultiplier),
      },
      research_agent: {
        enabled: raEnabled,
        max_positions: Number(raMaxPositions),
        max_position_pct: Number(raMaxPositionPct),
      },
    });
  };

  if (isLoading) {
    return <div className="text-slate-400 text-sm">Loading configuration...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-white">Settings</h2>
        <div className="flex gap-2">
          <a
            href="/api/analytics/export-csv"
            download
            className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded text-xs text-slate-300"
          >
            <Download size={14} /> Export Trades CSV
          </a>
          <button
            onClick={() => { setInitialized(false); queryClient.invalidateQueries({ queryKey: ['config'] }); }}
            className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded text-xs text-slate-300"
          >
            <RotateCw size={14} /> Reload
          </button>
        </div>
      </div>

      {/* Risk Management */}
      <Card title="Risk Management">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <InputField label="Max Trades/Day" value={maxTradesPerDay} onChange={setMaxTradesPerDay} type="number" />
          <InputField label="Min Confidence" value={minConfidence} onChange={setMinConfidence} type="number" step="0.05" help="0-1 scale" />
          <InputField label="Max Position %" value={maxPositionPct} onChange={setMaxPositionPct} type="number" step="0.01" help="Fraction of equity" />
          <InputField label="Max Portfolio Risk %" value={maxPortfolioRisk} onChange={setMaxPortfolioRisk} type="number" step="0.01" />
        </div>
      </Card>

      {/* Stock Watchlist */}
      <Card title="Stocks">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <InputField label="Watchlist (comma-separated)" value={watchlist} onChange={setWatchlist} placeholder="AAPL, MSFT, GOOGL, ..." />
          <InputField label="Trade Amount (USD)" value={tradeAmountUsd} onChange={setTradeAmountUsd} type="number" />
        </div>
      </Card>

      {/* Position Guard */}
      <Card title="Position Guard (Stop-Loss / Trailing / Take-Profit)">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={pgEnabled} onChange={setPgEnabled} />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <InputField label="Scan Interval (min)" value={pgScanInterval} onChange={setPgScanInterval} type="number" />
            <InputField label="Stop-Loss %" value={pgStopLoss} onChange={setPgStopLoss} type="number" step="0.5" help="Hard stop from entry" />
            <InputField label="Trailing Stop %" value={pgTrailingStop} onChange={setPgTrailingStop} type="number" step="0.5" help="From peak price" />
            <InputField label="Take-Profit %" value={pgTakeProfit} onChange={setPgTakeProfit} type="number" step="1" />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Toggle label="Partial Take-Profit" checked={pgPartialTP} onChange={setPgPartialTP} />
            <InputField label="Partial Fraction" value={pgPartialFrac} onChange={setPgPartialFrac} type="number" step="0.1" help="Sell this fraction at TP" />
            <Toggle label="Enable for Shorts" checked={pgShorts} onChange={setPgShorts} />
          </div>
          <InputField label="Exclude Symbols" value={pgExclude} onChange={setPgExclude} placeholder="TQQQ, SOXL, ..." help="Comma-separated, won't be stopped out" />
        </div>
      </Card>

      {/* Telegram Notifications */}
      <Card title="Telegram Notifications">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={tgEnabled} onChange={setTgEnabled} />
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Bot Token" value={tgToken} onChange={setTgToken} placeholder="123456:ABC..." />
            <InputField label="Chat ID" value={tgChatId} onChange={setTgChatId} placeholder="-100..." />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <Toggle label="Trade Notifications" checked={tgTrades} onChange={setTgTrades} />
            <Toggle label="Error Notifications" checked={tgErrors} onChange={setTgErrors} />
            <Toggle label="Stop-Loss Alerts" checked={tgStopLoss} onChange={setTgStopLoss} />
            <Toggle label="Daily Summary" checked={tgDailySummary} onChange={setTgDailySummary} />
          </div>
          {tgDailySummary && (
            <InputField label="Summary Hour (24h)" value={tgSummaryHour} onChange={setTgSummaryHour} type="number" help="0-23, server timezone" />
          )}
        </div>
      </Card>

      {/* Kalshi */}
      <Card title="Kalshi Prediction Markets">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={kalshiEnabled} onChange={setKalshiEnabled} />
          <div className="grid grid-cols-3 gap-4">
            <InputField label="Default Size (USD)" value={kalshiDefaultSize} onChange={setKalshiDefaultSize} type="number" />
            <InputField label="Max Open Exposure (USD)" value={kalshiMaxOpen} onChange={setKalshiMaxOpen} type="number" />
            <InputField label="Min Edge" value={kalshiMinEdge} onChange={setKalshiMinEdge} type="number" step="0.01" help="Min probability edge" />
          </div>
        </div>
      </Card>

      {/* Crypto */}
      <Card title="Crypto Momentum">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={cryptoEnabled} onChange={setCryptoEnabled} />
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Symbols" value={cryptoSymbols} onChange={setCryptoSymbols} placeholder="BTC/USD, ETH/USD, ..." />
            <InputField label="Trade Size (USD)" value={cryptoTradeSize} onChange={setCryptoTradeSize} type="number" />
          </div>
        </div>
      </Card>

      {/* Shorts */}
      <Card title="Short Selling">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={shortsEnabled} onChange={setShortsEnabled} />
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Max Positions" value={shortsMaxPositions} onChange={setShortsMaxPositions} type="number" />
            <InputField label="Max Portfolio %" value={shortsMaxPct} onChange={setShortsMaxPct} type="number" step="0.01" help="Max % of equity in shorts" />
          </div>
        </div>
      </Card>

      {/* Drawdown Accumulation */}
      <Card title="Drawdown Accumulation (Leveraged ETF DCA)">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={daEnabled} onChange={setDaEnabled} />
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Base Buy (USD)" value={daBaseBuy} onChange={setDaBaseBuy} type="number" />
            <InputField label="Max Drawdown Multiplier" value={daMaxDrawdownMultiplier} onChange={setDaMaxDrawdownMultiplier} type="number" step="0.5" help="Buy more as drawdown deepens" />
          </div>
        </div>
      </Card>

      {/* Research Agent */}
      <Card title="Research Agent">
        <div className="space-y-4">
          <Toggle label="Enabled" checked={raEnabled} onChange={setRaEnabled} />
          <div className="grid grid-cols-2 gap-4">
            <InputField label="Max Positions" value={raMaxPositions} onChange={setRaMaxPositions} type="number" />
            <InputField label="Max Position %" value={raMaxPositionPct} onChange={setRaMaxPositionPct} type="number" step="0.01" help="Fraction of equity per position" />
          </div>
        </div>
      </Card>

      {/* Save button */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={updateConfig.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 rounded text-sm font-medium text-white disabled:opacity-50 transition-colors"
        >
          <Save size={16} />
          {updateConfig.isPending ? 'Saving...' : saved ? 'Saved!' : 'Save All Settings'}
        </button>
        {updateConfig.isError && (
          <span className="text-sm text-red-400">Error: {(updateConfig.error as Error).message}</span>
        )}
      </div>

      {/* Raw config (collapsed) */}
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

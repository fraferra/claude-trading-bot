import { useState } from 'react';
import {
  BookOpen, LayoutDashboard, Brain, LineChart, ArrowRightLeft, Globe,
  TrendingUp, Target, Bitcoin, TrendingDown, BarChart3, Shield,
  FlaskConical, Radio, History, Settings, ChevronDown, ChevronRight,
  Zap, AlertTriangle, CheckCircle, Info,
} from 'lucide-react';

interface Section {
  id: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  title: string;
  color: string;
  content: React.ReactNode;
}

function Callout({ type, children }: { type: 'tip' | 'warning' | 'info'; children: React.ReactNode }) {
  const styles = {
    tip: { bg: 'bg-green-950/40 border-green-700/50', icon: CheckCircle, text: 'text-green-400', label: 'Tip' },
    warning: { bg: 'bg-yellow-950/40 border-yellow-700/50', icon: AlertTriangle, text: 'text-yellow-400', label: 'Warning' },
    info: { bg: 'bg-blue-950/40 border-blue-700/50', icon: Info, text: 'text-blue-400', label: 'Note' },
  }[type];
  const Icon = styles.icon;
  return (
    <div className={`flex gap-3 p-3 rounded-lg border ${styles.bg} my-3`}>
      <Icon size={16} className={`${styles.text} mt-0.5 shrink-0`} />
      <div className="text-sm text-slate-300">{children}</div>
    </div>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto my-3">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700">
            {headers.map(h => (
              <th key={h} className="text-left py-2 px-3 text-slate-400 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
              {row.map((cell, j) => (
                <td key={j} className="py-2 px-3 text-slate-300">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Badge({ color, children }: { color: string; children: React.ReactNode }) {
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${color}`}>{children}</span>;
}

const SECTIONS: Section[] = [
  {
    id: 'overview',
    icon: BookOpen,
    title: 'Overview',
    color: 'text-slate-300',
    content: (
      <div className="space-y-4 text-slate-300 text-sm leading-relaxed">
        <p>
          This trading bot is a multi-platform autonomous trading system that operates across US equities,
          Kalshi prediction markets, Polymarket, and crypto. It combines AI-driven analysis, quantitative signals,
          and automated execution — all configurable through this web interface.
        </p>
        <Table
          headers={['Platform', 'Asset Type', 'Strategy']}
          rows={[
            ['Alpaca / Stocks', 'US Equities', 'AI fundamentals + technicals, short selling, research agent'],
            ['Kalshi', 'Prediction Markets', 'AI probability edge, direct arb'],
            ['Polymarket', 'Prediction Markets', 'Multi-outcome arb, cross-platform arb, temporal momentum'],
            ['Crypto (CCXT)', 'Spot Crypto', 'Momentum + mean reversion'],
          ]}
        />
        <Callout type="info">
          All trading is <strong>paper mode by default</strong>. Real execution requires configuring live broker credentials in Settings and disabling paper mode in the config file.
        </Callout>
        <h3 className="text-white font-semibold mt-4">Key concepts</h3>
        <ul className="space-y-1.5 list-disc list-inside text-slate-300">
          <li><strong className="text-white">Monitors</strong> — long-running background loops that scan, signal, and execute automatically</li>
          <li><strong className="text-white">Strategies</strong> — on-demand scans you trigger manually from the UI</li>
          <li><strong className="text-white">Risk Manager</strong> — enforces daily loss limits, max trades/day, and position size caps across all strategies</li>
          <li><strong className="text-white">Agent Decisions</strong> — every trade decision (human or AI) is logged with full reasoning for review</li>
        </ul>
      </div>
    ),
  },
  {
    id: 'dashboard',
    icon: LayoutDashboard,
    title: 'Dashboard',
    color: 'text-blue-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>The dashboard is a read-only overview of your portfolio's current state and recent activity.</p>
        <Table
          headers={['Card', 'Description']}
          rows={[
            ['Total Equity', 'Sum of cash + all open position market values'],
            ['Cash Available', 'Uninvested cash balance'],
            ["Today's P&L", 'Realized + unrealized gains/losses since midnight'],
            ['Unrealized P&L', 'Mark-to-market gain/loss on open positions'],
            ['Open Positions', 'Count of current open positions'],
          ]}
        />
        <h3 className="text-white font-semibold">Charts</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><strong className="text-white">Equity Over Time</strong> — 30-day portfolio equity curve</li>
          <li><strong className="text-white">P&L by Platform</strong> — separate Stocks, Kalshi, and Crypto performance lines</li>
          <li><strong className="text-white">Positions table</strong> — live mark-to-market for every open position</li>
          <li><strong className="text-white">Recent Trades</strong> — last 10 executed trades across all platforms</li>
        </ul>
        <Callout type="tip">
          The dashboard refreshes automatically. No actions needed — it's purely informational.
        </Callout>
      </div>
    ),
  },
  {
    id: 'research',
    icon: Brain,
    title: 'Research Agent',
    color: 'text-purple-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>
          An autonomous AI agent that discovers, scores, and manages a portfolio of US equities. It runs on a schedule
          and uses fundamental data, news, and technical signals to build a target allocation.
        </p>
        <h3 className="text-white font-semibold">Actions</h3>
        <Table
          headers={['Button', 'What it does']}
          rows={[
            ['Run Full Pipeline', 'Runs discovery + scoring + allocation rebalancing end-to-end'],
            ['Discover Only', 'Scans for new candidate symbols without updating allocations'],
          ]}
        />
        <h3 className="text-white font-semibold">Tabs</h3>
        <ul className="space-y-1.5 list-disc list-inside">
          <li><strong className="text-white">Reports</strong> — per-symbol research with composite score, recommendation (buy/hold/sell), and target weight</li>
          <li><strong className="text-white">Allocation</strong> — current target portfolio with cash reserve %, and per-symbol action (buy/add/trim/sell)</li>
          <li><strong className="text-white">Discoveries</strong> — latest scan results: new candidate symbols with reasons they were surfaced</li>
          <li><strong className="text-white">Strategy Memos</strong> — weekly retrospective memos with return %, win rate, lessons learned, and parameter adjustments</li>
        </ul>
        <Callout type="info">
          The Research Agent monitor must be running (start it from the <strong>Monitors</strong> page) for automatic scheduled runs. Manual triggers via buttons work regardless.
        </Callout>
      </div>
    ),
  },
  {
    id: 'strategies',
    icon: LineChart,
    title: 'Strategies',
    color: 'text-cyan-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>On-demand strategy tools — run a single scan and see results immediately. No monitor needed.</p>
        <Table
          headers={['Strategy', 'Input', 'What it returns']}
          rows={[
            ['Stock Scorer', 'Ticker symbol (e.g. AAPL)', 'Multi-signal composite score: technicals, fundamentals, AI sentiment; recommendation'],
            ['Watchlist Ranker', 'None (uses configured watchlist)', 'All watchlist stocks ranked by composite score'],
            ['Arbitrage Scanner', 'Optional min edge %', 'Polymarket multi-outcome markets where all outcomes sum < $1 (risk-free arb)'],
            ['Probability Edge', 'Optional search query', 'Markets where AI probability estimate diverges significantly from market price'],
          ]}
        />
        <Callout type="tip">
          Results are displayed as raw JSON. Use these tools for quick one-off analysis before committing to a trade or configuring a monitor.
        </Callout>
      </div>
    ),
  },
  {
    id: 'trade',
    icon: ArrowRightLeft,
    title: 'Trade',
    color: 'text-green-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Manual trade execution interface for stocks and Polymarket.</p>
        <h3 className="text-white font-semibold">Stock tab</h3>
        <Table
          headers={['Button', 'What it does']}
          rows={[
            ['Analyze Only', 'Runs AI analysis and returns recommendation — no order placed'],
            ['Analyze & Trade', 'Runs analysis, then places a trade if confidence exceeds threshold'],
          ]}
        />
        <h3 className="text-white font-semibold">Polymarket tab</h3>
        <p>Enter a <strong className="text-white">Condition ID</strong> (from the Markets search or Polymarket URL), choose BUY or SELL, set a USD size, and click <strong className="text-white">Execute Trade</strong>.</p>
        <Callout type="warning">
          In paper mode all trades are simulated. Switch to live mode in Settings + config to execute real orders.
        </Callout>
      </div>
    ),
  },
  {
    id: 'markets',
    icon: Globe,
    title: 'Markets',
    color: 'text-teal-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Market data lookup tool — not a trading screen, just data retrieval.</p>
        <Table
          headers={['Section', 'What you can look up']}
          rows={[
            ['Stock Lookup', 'Enter any US ticker: price, volume, RSI(14), MACD, P/E, beta, sector, market cap'],
            ['Polymarket Search', 'Search Polymarket by keyword: returns matching market questions, volumes, end dates, and condition IDs'],
          ]}
        />
        <Callout type="tip">
          Copy condition IDs from Polymarket search results directly into the Trade tab to place orders.
        </Callout>
      </div>
    ),
  },
  {
    id: 'kalshi',
    icon: TrendingUp,
    title: 'Kalshi',
    color: 'text-orange-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Full Kalshi prediction market dashboard: portfolio, orders, trades, AI estimates, and decisions.</p>
        <h3 className="text-white font-semibold">Summary cards</h3>
        <Table
          headers={['Card', 'Description']}
          rows={[
            ['Balance', 'Current Kalshi account cash balance'],
            ['Total Equity', 'Cash + open position market value'],
            ['Open Positions', 'Count of active Kalshi positions'],
            ['Settled P&L', 'Cumulative realized P&L with win/loss record'],
          ]}
        />
        <h3 className="text-white font-semibold">Sections</h3>
        <ul className="space-y-1.5 list-disc list-inside">
          <li><strong className="text-white">Open / Filled Orders</strong> — live order book state from Kalshi API</li>
          <li><strong className="text-white">AI Probability Estimates</strong> — markets where the AI estimate diverges from the current price; shows edge % and suggested side</li>
          <li><strong className="text-white">Decision Log</strong> — every trade decision with full AI reasoning; click a row to expand signals breakdown</li>
          <li><strong className="text-white">Settled Bets</strong> — resolved positions with final P&L per contract</li>
        </ul>
        <h3 className="text-white font-semibold">Actions</h3>
        <p><Badge color="bg-blue-700/50 text-blue-300">Scan Markets</Badge> — fetches current Kalshi markets and runs AI probability estimation on all of them.</p>
      </div>
    ),
  },
  {
    id: 'polymarket',
    icon: Target,
    title: 'Polymarket',
    color: 'text-pink-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Polymarket dashboard with three distinct trading strategies.</p>
        <h3 className="text-white font-semibold">Strategies</h3>
        <Table
          headers={['Button', 'Strategy', 'How it works']}
          rows={[
            ['Arb Scan', 'Multi-outcome arbitrage', 'Finds markets where YES + NO + other outcomes sum < $1.00 — buying all is risk-free profit'],
            ['Cross-Platform Scan', 'Kalshi ↔ Polymarket arbitrage', 'Matches similar questions across both platforms, buys the cheaper side'],
            ['Momentum Scan', 'Temporal momentum arb', 'Detects strong BTC/ETH/SOL momentum on Binance and enters Polymarket binary markets before they reprice'],
          ]}
        />
        <h3 className="text-white font-semibold">Temporal Momentum section</h3>
        <p>Shows live signals for BTC, ETH, and SOL:</p>
        <ul className="space-y-1 list-disc list-inside">
          <li><strong className="text-white">Direction badge</strong> — UP / DOWN / FLAT based on 1-minute and 3-minute price changes agreeing</li>
          <li><strong className="text-white">Strength bar</strong> — 0–100% composite score (weighted sigmoid of 1m, 3m, 5m changes)</li>
          <li><strong className="text-white">Opportunities table</strong> — live arb candidates with edge %, estimated true probability, suggested side, and time to expiry</li>
        </ul>
        <Callout type="info">
          The temporal momentum strategy requires the <strong>Temporal Momentum monitor</strong> to be running for real-time Binance WebSocket data. Manual scans work as one-shots.
        </Callout>
        <h3 className="text-white font-semibold">Decision Log</h3>
        <p>Expandable rows show full reasoning, momentum signal values, edge calculation, and outcome (won/lost/pending) for every executed trade.</p>
      </div>
    ),
  },
  {
    id: 'crypto',
    icon: Bitcoin,
    title: 'Crypto',
    color: 'text-yellow-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Cryptocurrency momentum and mean-reversion strategy dashboard.</p>
        <h3 className="text-white font-semibold">Signals displayed per pair</h3>
        <Table
          headers={['Signal', 'Meaning']}
          rows={[
            ['RSI(14)', 'Relative strength — below 30 oversold, above 70 overbought'],
            ['MACD', 'Trend momentum — positive = bullish crossover'],
            ['BB %B', 'Bollinger Band position — 0 = lower band, 1 = upper band'],
            ['Momentum', 'Raw price momentum score'],
            ['Mean Reversion', 'Distance from mean — high score = likely to revert'],
            ['Composite Signal', 'Weighted combination of all signals; determines buy/sell/hold'],
          ]}
        />
        <h3 className="text-white font-semibold">Actions</h3>
        <p><Badge color="bg-yellow-700/50 text-yellow-300">Scan Watchlist</Badge> — runs a full signal sweep across all configured crypto pairs.</p>
        <h3 className="text-white font-semibold">Decision Log</h3>
        <p>Expand any row to see: individual signal values at time of decision, price, quantity, fill amount, and the LLM reasoning that produced the action.</p>
        <Callout type="info">
          Crypto pairs are configured in Settings under <strong>Crypto Momentum → Symbols</strong>.
        </Callout>
      </div>
    ),
  },
  {
    id: 'shorts',
    icon: TrendingDown,
    title: 'Shorts',
    color: 'text-red-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>
          Short-selling proposal system. The bot scans S&P 500 and NASDAQ-100 for overbought conditions,
          generates proposals, and waits for <strong className="text-white">manual approval</strong> before placing any short.
        </p>
        <h3 className="text-white font-semibold">Scoring signals</h3>
        <Table
          headers={['Signal', 'High score means...']}
          rows={[
            ['RSI(2)', 'Extremely overbought on a 2-day basis'],
            ['RSI(14)', 'Overbought on a standard 14-day basis'],
            ['BB %B', 'Price near/above upper Bollinger Band'],
            ['Volume Ratio', 'Unusually high volume (potential exhaustion)'],
            ['MACD Histogram', 'Momentum diverging negative'],
            ['P/E Ratio', 'Significantly overvalued vs sector'],
            ['ATR', 'High volatility (better short risk/reward)'],
            ['vs SMA200', 'Price extended far above 200-day average'],
          ]}
        />
        <h3 className="text-white font-semibold">Workflow</h3>
        <ol className="space-y-1 list-decimal list-inside">
          <li>Click <Badge color="bg-red-700/50 text-red-300">Scan Market</Badge> to generate proposals</li>
          <li>Review each proposal card — examine the signal breakdown</li>
          <li>Click <Badge color="bg-red-600/80 text-white">Approve Short</Badge> to execute, or <Badge color="bg-slate-700 text-slate-300">Reject</Badge> to dismiss</li>
        </ol>
        <Callout type="warning">
          Short selling requires live broker credentials with margin enabled. Paper mode shorts are simulated but carry no real risk.
        </Callout>
      </div>
    ),
  },
  {
    id: 'analytics',
    icon: BarChart3,
    title: 'Analytics',
    color: 'text-indigo-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Aggregated performance analytics across all platforms and strategies.</p>
        <h3 className="text-white font-semibold">Key metrics</h3>
        <Table
          headers={['Metric', 'Definition']}
          rows={[
            ['Realized P&L', 'Total closed profit/loss across all platforms'],
            ['Win Rate', 'Percentage of trades that were profitable'],
            ['Sharpe Ratio', 'Risk-adjusted return (annualised return / volatility); >1.0 is good'],
            ['Sortino Ratio', 'Like Sharpe but only penalises downside volatility; >2.0 is strong'],
            ['Max Drawdown', 'Largest peak-to-trough equity decline; lower is better'],
            ['Profit Factor', 'Total wins ÷ total losses; >1.5 is solid'],
          ]}
        />
        <h3 className="text-white font-semibold">Charts</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><strong className="text-white">Daily Returns bar chart</strong> — green/red bars per calendar day</li>
          <li><strong className="text-white">P&L Calendar heatmap</strong> — 90-day intensity-coded calendar</li>
          <li><strong className="text-white">P&L by Symbol</strong> — attribution breakdown per traded symbol</li>
        </ul>
        <p><Badge color="bg-slate-700 text-slate-300">Export CSV</Badge> — downloads all analytics data for external analysis.</p>
      </div>
    ),
  },
  {
    id: 'risk',
    icon: Shield,
    title: 'Risk Dashboard',
    color: 'text-emerald-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Real-time portfolio risk exposure and concentration analysis.</p>
        <Table
          headers={['Metric', 'Description']}
          rows={[
            ['Long Exposure', 'Total USD value of long positions'],
            ['Short Exposure', 'Total USD value of short positions (absolute)'],
            ['Net Exposure', 'Long − Short — positive = net long'],
            ['Largest Position %', 'Biggest single position as % of total equity'],
          ]}
        />
        <h3 className="text-white font-semibold">Charts</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><strong className="text-white">Sector Exposure pie</strong> — portfolio breakdown by GICS sector</li>
          <li><strong className="text-white">Concentration bars</strong> — top 10 positions by % of portfolio</li>
          <li><strong className="text-white">Correlation matrix</strong> — pairwise correlations; yellow cells indicate high correlation (&gt;0.5) — concentrated risk</li>
        </ul>
        <Callout type="warning">
          High concentration in correlated positions amplifies drawdown risk. Aim for no single position above 10% and low cross-correlations.
        </Callout>
      </div>
    ),
  },
  {
    id: 'backtest',
    icon: FlaskConical,
    title: 'Backtest',
    color: 'text-violet-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Historical simulation of the stock strategy against any date range and parameter set.</p>
        <h3 className="text-white font-semibold">Parameters</h3>
        <Table
          headers={['Parameter', 'Description']}
          rows={[
            ['Symbols', 'Comma-separated tickers (e.g. AAPL,MSFT,NVDA)'],
            ['Start / End Date', 'Backtest window'],
            ['Initial Capital', 'Starting portfolio cash in USD'],
            ['Trade Amount', 'USD per trade'],
            ['Stop-Loss %', 'Automatic exit on drawdown from entry'],
            ['Take-Profit %', 'Automatic exit on gain from entry'],
            ['Technical Weight', 'Relative weight for RSI/MACD/BB signals (0–1)'],
            ['Fundamental Weight', 'Relative weight for P/E, earnings, beta signals (0–1)'],
            ['Momentum Weight', 'Relative weight for price momentum signals (0–1)'],
            ['Buy Threshold', 'Minimum composite score to trigger a buy (0–1)'],
          ]}
        />
        <h3 className="text-white font-semibold">Results</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li>Equity curve chart vs buy-and-hold benchmark</li>
          <li>Return %, Sharpe, Max Drawdown, Win Rate, Profit Factor</li>
          <li>Full trade log with entry price, exit price, and P&L per trade</li>
        </ul>
        <Callout type="tip">
          Use backtest to tune <strong>Buy Threshold</strong> and signal weights before deploying a monitor with real capital.
        </Callout>
      </div>
    ),
  },
  {
    id: 'monitors',
    icon: Radio,
    title: 'Monitors',
    color: 'text-blue-300',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Monitors are persistent background loops. Start one and it runs autonomously until you stop it.</p>
        <Table
          headers={['Monitor', 'What it does', 'Interval']}
          rows={[
            ['Research Agent', 'Discovers and scores stocks, updates target allocation', 'Daily'],
            ['Strategy Review', 'Reviews recent performance, adapts signal weights', 'Weekly'],
            ['Stock Watchlist', 'Scans watchlist stocks and trades on AI signals', '15 min'],
            ['Polymarket Arb', 'Scans all Polymarket markets for multi-outcome arb', '5 min'],
            ['Probability Edge', 'Compares AI probability vs market price on Kalshi/Polymarket', '10 min'],
            ['Cross-Market', 'Finds correlated markets with diverging prices', '15 min'],
            ['Cross-Platform Arb', 'Kalshi ↔ Polymarket price spread detection', '5 min'],
            ['Weather Arbitrage', 'NOAA forecast vs Polymarket weather market prices (1–7 day)', '30 min'],
            ['Kalshi Prediction', 'AI probability estimation on Kalshi markets', '10 min'],
            ['Kalshi Arb', 'Direct arbitrage within Kalshi multi-outcome events', '5 min'],
            ['Crypto Momentum', 'Momentum + mean-reversion on configured crypto pairs', '15 min'],
            ['Regime Classifier', 'Detects market regime (bull/bear/sideways), adjusts risk', '1 hour'],
            ['Short Candidate', 'Scans S&P 500 + NASDAQ-100 for short opportunities', '1 hour'],
            ['Temporal Momentum', 'Binance spot → Polymarket binary crypto lag arb', '2 sec'],
          ]}
        />
        <h3 className="text-white font-semibold">Controls</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><Badge color="bg-yellow-700/50 text-yellow-300">Pause</Badge> — suspends execution, keeps state; resume later</li>
          <li><Badge color="bg-green-700/50 text-green-300">Resume</Badge> — restarts a paused monitor</li>
          <li><Badge color="bg-red-700/50 text-red-300">Stop</Badge> — terminates and removes the monitor</li>
        </ul>
        <Callout type="info">
          Multiple monitors of the same type can run simultaneously (e.g. two Polymarket Arb monitors with different config). Each gets a unique ID.
        </Callout>
      </div>
    ),
  },
  {
    id: 'activity',
    icon: History,
    title: 'Activity',
    color: 'text-slate-400',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Full audit log of all trade executions and AI decisions across every platform.</p>
        <h3 className="text-white font-semibold">Trade History columns</h3>
        <Table
          headers={['Column', 'Description']}
          rows={[
            ['Time', 'Execution timestamp'],
            ['Symbol', 'Ticker, token ID, or market condition ID'],
            ['Side', 'BUY (green) or SELL (red)'],
            ['Qty', 'Number of shares/contracts/tokens'],
            ['Price', 'Execution price (or "Pending" if order not yet filled)'],
            ['Platform', 'alpaca / kalshi / polymarket / crypto'],
            ['Source', 'Which monitor or strategy originated the trade'],
            ['Reasoning', 'Hover to read the full AI reasoning text'],
          ]}
        />
        <h3 className="text-white font-semibold">Decision Log columns</h3>
        <Table
          headers={['Column', 'Description']}
          rows={[
            ['Time', 'Decision timestamp'],
            ['Symbol', 'Target asset'],
            ['Action', 'BUY / SELL / HOLD / SKIP'],
            ['Confidence', 'AI confidence score 0–100%'],
            ['Executed', 'Whether an order was actually placed'],
            ['Reasoning', 'Hover to read full reasoning'],
          ]}
        />
        <Callout type="tip">
          Hover over any <strong>Reasoning</strong> cell to read the full LLM explanation in a tooltip.
        </Callout>
      </div>
    ),
  },
  {
    id: 'settings',
    icon: Settings,
    title: 'Settings',
    color: 'text-slate-300',
    content: (
      <div className="space-y-3 text-slate-300 text-sm leading-relaxed">
        <p>Configure all system parameters. Changes take effect immediately after clicking <Badge color="bg-blue-700/50 text-blue-300">Save All Settings</Badge>.</p>
        <h3 className="text-white font-semibold">Risk Management</h3>
        <Table
          headers={['Setting', 'Description']}
          rows={[
            ['Max Trades/Day', 'Hard cap on total trade executions across all strategies per day'],
            ['Min Confidence', 'AI confidence threshold (0–1) below which trades are skipped'],
            ['Max Position %', 'Maximum single position as % of portfolio equity'],
            ['Max Portfolio Risk %', 'Maximum total portfolio drawdown allowed before trading halts'],
          ]}
        />
        <h3 className="text-white font-semibold">Position Guard (Stop-Loss)</h3>
        <Table
          headers={['Setting', 'Description']}
          rows={[
            ['Stop-Loss %', 'Hard stop — exit if position falls this % below entry'],
            ['Trailing Stop %', 'Dynamic stop that follows the price up, locks in gains'],
            ['Take-Profit %', 'Auto-exit when position reaches this % gain'],
            ['Partial Take-Profit', 'Sell a fraction (configurable) at take-profit, hold the rest'],
            ['Enable for Shorts', 'Apply stop-loss/take-profit logic to short positions too'],
            ['Exclude Symbols', 'Symbols exempt from automatic stop-loss management'],
          ]}
        />
        <h3 className="text-white font-semibold">Telegram Notifications</h3>
        <p>Enter your Telegram Bot Token and Chat ID to receive alerts for: trade executions, errors, stop-loss triggers, and a configurable daily summary.</p>
        <h3 className="text-white font-semibold">Other strategy toggles</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><strong className="text-white">Kalshi</strong> — default order size, max open exposure, min edge threshold</li>
          <li><strong className="text-white">Crypto Momentum</strong> — enabled pairs, trade size per signal</li>
          <li><strong className="text-white">Short Selling</strong> — max concurrent shorts, max portfolio % in shorts</li>
          <li><strong className="text-white">Drawdown Accumulation</strong> — base buy size and multiplier for dollar-cost-averaging into drawdowns</li>
          <li><strong className="text-white">Research Agent</strong> — max portfolio positions, max % per position</li>
        </ul>
        <h3 className="text-white font-semibold">Other actions</h3>
        <ul className="space-y-1 list-disc list-inside">
          <li><Badge color="bg-slate-700 text-slate-300">Export Trades CSV</Badge> — downloads full trade history</li>
          <li><Badge color="bg-slate-700 text-slate-300">Reload</Badge> — re-fetches current config from server without saving</li>
        </ul>
      </div>
    ),
  },
  {
    id: 'quickstart',
    icon: Zap,
    title: 'Quick Start',
    color: 'text-amber-400',
    content: (
      <div className="space-y-4 text-slate-300 text-sm leading-relaxed">
        <h3 className="text-white font-semibold">Get trading in 5 steps</h3>
        <ol className="space-y-3 list-decimal list-inside">
          <li>
            <strong className="text-white">Configure settings</strong> — Go to Settings, set your watchlist symbols, trade amount, and risk limits. Click Save.
          </li>
          <li>
            <strong className="text-white">Run a backtest</strong> — Use Backtest to validate the stock strategy on your watchlist over the last 6–12 months. Tune the Buy Threshold until results look good.
          </li>
          <li>
            <strong className="text-white">Start monitors</strong> — Go to Monitors. Start with <strong>Stock Watchlist</strong> for equities, <strong>Polymarket Arb</strong> for risk-free prediction market arb, and <strong>Crypto Momentum</strong> for crypto.
          </li>
          <li>
            <strong className="text-white">Monitor decisions</strong> — Check Activity and the platform-specific pages (Kalshi, Polymarket, Crypto) to review what the bot is doing and why.
          </li>
          <li>
            <strong className="text-white">Go live</strong> — Once comfortable, update <code className="bg-slate-800 px-1 rounded">config.yaml</code> to disable paper mode and provide live broker credentials.
          </li>
        </ol>
        <Callout type="tip">
          Start with the <strong>Polymarket Arb</strong> monitor — it trades risk-free combined-price arbitrage where buying all outcomes costs less than $1, locking in guaranteed profit regardless of market outcome.
        </Callout>
        <Callout type="warning">
          The <strong>Temporal Momentum</strong> monitor runs on a 2-second inner loop against live Binance WebSocket data. It requires a reliable connection and works best during high-volatility periods (major macro events, earnings, Fed announcements).
        </Callout>
        <h3 className="text-white font-semibold mt-2">Recommended monitor stack for beginners</h3>
        <Table
          headers={['Monitor', 'Risk level', 'Expected frequency']}
          rows={[
            ['Polymarket Arb', 'Very low (hedged)', '2–10 trades/day during active markets'],
            ['Stock Watchlist', 'Medium', '1–3 trades/day depending on signals'],
            ['Crypto Momentum', 'Medium-high', '2–5 trades/day'],
            ['Research Agent', 'Low (long-term)', '1 rebalance/week'],
          ]}
        />
      </div>
    ),
  },
];

export default function Guide() {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(['overview', 'quickstart']));

  function toggle(id: string) {
    setOpenSections(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function expandAll() {
    setOpenSections(new Set(SECTIONS.map(s => s.id)));
  }

  function collapseAll() {
    setOpenSections(new Set());
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BookOpen size={24} className="text-slate-400" />
            User Guide
          </h1>
          <p className="text-slate-400 text-sm mt-1">Complete reference for all bot features and pages</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={expandAll}
            className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition-colors"
          >
            Expand all
          </button>
          <button
            onClick={collapseAll}
            className="px-3 py-1.5 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded transition-colors"
          >
            Collapse all
          </button>
        </div>
      </div>

      {/* Table of contents */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
        <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">Sections</p>
        <div className="flex flex-wrap gap-2">
          {SECTIONS.map(({ id, icon: Icon, title, color }) => (
            <button
              key={id}
              onClick={() => {
                setOpenSections(prev => new Set([...prev, id]));
                setTimeout(() => {
                  document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 50);
              }}
              className="flex items-center gap-1.5 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 rounded text-xs transition-colors"
            >
              <Icon size={12} className={color} />
              <span className="text-slate-300">{title}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Sections */}
      {SECTIONS.map(({ id, icon: Icon, title, color, content }) => {
        const isOpen = openSections.has(id);
        return (
          <div
            key={id}
            id={`section-${id}`}
            className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden"
          >
            <button
              onClick={() => toggle(id)}
              className="w-full flex items-center justify-between px-5 py-4 hover:bg-slate-800/50 transition-colors"
            >
              <div className="flex items-center gap-3">
                <Icon size={18} className={color} />
                <span className="text-white font-semibold">{title}</span>
              </div>
              {isOpen
                ? <ChevronDown size={16} className="text-slate-500" />
                : <ChevronRight size={16} className="text-slate-500" />}
            </button>
            {isOpen && (
              <div className="px-5 pb-5 border-t border-slate-800">
                <div className="pt-4">{content}</div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

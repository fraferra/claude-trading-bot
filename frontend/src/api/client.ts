const BASE = '/api';

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...opts?.headers },
    ...opts,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  return resp.json();
}

export const api = {
  // Portfolio
  getPortfolio: () => request<Record<string, any>>('/portfolio'),
  getPositions: () => request<any[]>('/positions'),
  getSnapshots: (platform?: string) =>
    request<any[]>(`/snapshots${platform ? `?platform=${platform}` : ''}`),

  // Analysis
  analyzeStock: (symbol: string) =>
    request<any>('/analyze/stock', { method: 'POST', body: JSON.stringify({ symbol }) }),
  analyzeMarket: (conditionId: string) =>
    request<any>('/analyze/market', { method: 'POST', body: JSON.stringify({ condition_id: conditionId }) }),
  analyzeProbability: (conditionId: string) =>
    request<any>('/analyze/probability', { method: 'POST', body: JSON.stringify({ condition_id: conditionId }) }),

  // Trade
  tradeStock: (symbol: string, quantity?: number) =>
    request<any>('/trade/stock', { method: 'POST', body: JSON.stringify({ symbol, quantity }) }),
  tradeMarket: (conditionId: string, sizeUsd: number, side: string) =>
    request<any>('/trade/market', { method: 'POST', body: JSON.stringify({ condition_id: conditionId, size_usd: sizeUsd, side }) }),
  tradePreview: (symbol: string, side: string, platform: string, quantity?: number) =>
    request<any>('/trade/preview', { method: 'POST', body: JSON.stringify({ symbol, side, platform, quantity }) }),

  // Strategies
  scoreStock: (symbol: string) =>
    request<any>('/scan/stock-score', { method: 'POST', body: JSON.stringify({ symbol }) }),
  rankStocks: (symbols?: string[]) =>
    request<any>('/scan/stock-rank', { method: 'POST', body: JSON.stringify({ symbols }) }),
  scanArbitrage: (minEdge?: number) =>
    request<any>('/scan/arbitrage', { method: 'POST', body: JSON.stringify({ min_edge: minEdge }) }),
  scanCrossMarket: (queries?: string[]) =>
    request<any>('/scan/cross-market', { method: 'POST', body: JSON.stringify({ queries }) }),
  scanProbability: (conditionIds?: string[], query?: string) =>
    request<any>('/scan/probability', { method: 'POST', body: JSON.stringify({ condition_ids: conditionIds, search_query: query }) }),

  // Monitors
  getMonitors: () => request<any>('/monitors'),
  startMonitor: (type: string) => request<any>(`/monitors/${type}/start`, { method: 'POST' }),
  stopMonitor: (id: string) => request<any>(`/monitors/${id}/stop`, { method: 'POST' }),
  pauseMonitor: (id: string) => request<any>(`/monitors/${id}/pause`, { method: 'POST' }),
  resumeMonitor: (id: string) => request<any>(`/monitors/${id}/resume`, { method: 'POST' }),
  getMonitorDetail: (id: string) => request<any>(`/monitors/${id}`),

  // Market Data
  getStockData: (symbol: string) => request<any>(`/stocks/${symbol}`),
  searchMarkets: (q: string) => request<any[]>(`/markets/search?q=${encodeURIComponent(q)}`),
  getMarketData: (id: string) => request<any>(`/markets/${id}`),

  // History
  getTrades: (limit = 100) => request<any[]>(`/history/trades?limit=${limit}`),
  getDecisions: (limit = 100) => request<any[]>(`/history/decisions?limit=${limit}`),
  getStrategyResults: () => request<any[]>('/history/strategy-results'),
  getStockScores: (symbol?: string) =>
    request<any[]>(`/history/stock-scores${symbol ? `?symbol=${symbol}` : ''}`),
  getCumulativePnl: () => request<Record<string, any[]>>('/history/cumulative-pnl'),

  // Analytics
  getPerformance: (platform?: string) =>
    request<any>(`/analytics/performance${platform ? `?platform=${platform}` : ''}`),
  getRiskMetrics: () => request<any>('/analytics/risk'),
  getCalendarReturns: () => request<any[]>('/analytics/calendar'),
  getCorrelation: () => request<any>('/analytics/correlation'),
  checkEarnings: (symbols: string) =>
    request<any>(`/analytics/earnings-check?symbols=${encodeURIComponent(symbols)}`),

  // Config
  getConfig: () => request<any>('/config'),
  updateConfig: (data: any) =>
    request<any>('/config', { method: 'PUT', body: JSON.stringify(data) }),

  // Research Agent
  getResearchStatus: () => request<any>('/research/status'),
  getResearchReports: (symbol?: string) =>
    request<any>(`/research/reports${symbol ? `?symbol=${symbol}` : ''}`),
  getResearchReportsForSymbol: (symbol: string) =>
    request<any>(`/research/reports/${symbol}`),
  getCurrentAllocation: () => request<any>('/research/allocation'),
  getStrategyMemos: () => request<any>('/research/memos'),
  getDiscoveries: () => request<any>('/research/discoveries'),
  triggerResearchRun: () =>
    request<any>('/research/run', { method: 'POST' }),
  triggerDiscovery: () =>
    request<any>('/research/discover', { method: 'POST' }),

  // Kalshi
  getKalshiEvents: () => request<any>('/kalshi/events'),
  getKalshiMarket: (ticker: string) => request<any>(`/kalshi/markets/${ticker}`),
  getKalshiPortfolio: () => request<any>('/kalshi/portfolio'),
  getKalshiOrders: (status?: string) => request<any>(`/kalshi/orders${status ? `?status=${status}` : ''}`),
  getKalshiTrades: (limit = 50) => request<any[]>(`/kalshi/trades?limit=${limit}`),
  getKalshiEstimates: (limit = 50) => request<any[]>(`/kalshi/estimates?limit=${limit}`),
  getKalshiDecisions: (limit = 50) => request<any[]>(`/kalshi/decisions?limit=${limit}`),
  getKalshiSettlements: (limit = 50) => request<any[]>(`/kalshi/settlements?limit=${limit}`),
  scanKalshi: () => request<any>('/kalshi/scan', { method: 'POST' }),

  // Polymarket
  getPolymarketPortfolio: () => request<any>('/polymarket/portfolio'),
  getPolymarketPositions: () => request<any>('/polymarket/positions'),
  getPolymarketTrades: (limit = 50) => request<any[]>(`/polymarket/trades?limit=${limit}`),
  getPolymarketSettlements: (limit = 50) => request<any[]>(`/polymarket/settlements?limit=${limit}`),
  getPolymarketArbOpportunities: (limit = 20) => request<any>(`/polymarket/arb-opportunities?limit=${limit}`),
  getPolymarketCrossPlatformPairs: (status?: string) =>
    request<any>(`/polymarket/cross-platform-pairs${status ? `?status=${status}` : ''}`),
  getPolymarketPnlHistory: () => request<any>('/polymarket/pnl-history'),
  getPolymarketMonitorStats: () => request<any>('/polymarket/monitor-stats'),
  getPolymarketDecisions: (limit = 50, agentType?: string) =>
    request<any>(`/polymarket/decisions?limit=${limit}${agentType ? `&agent_type=${agentType}` : ''}`),
  scanPolymarketArb: () => request<any>('/polymarket/arb-scan', { method: 'POST' }),
  scanPolymarketCrossPlatform: () => request<any>('/polymarket/cross-platform-scan', { method: 'POST' }),
  getTemporalMomentumSignals: () => request<any>('/polymarket/temporal-momentum/signals'),
  getTemporalMomentumDecisions: (limit = 50) =>
    request<any>(`/polymarket/temporal-momentum/decisions?limit=${limit}`),
  scanTemporalMomentum: () => request<any>('/polymarket/temporal-momentum/scan', { method: 'POST' }),

  // Crypto
  getCryptoSignals: (symbol?: string) =>
    request<any[]>(`/crypto/signals${symbol ? `/${symbol}` : ''}`),
  getCryptoBars: (symbol: string) => request<any>(`/crypto/bars/${symbol}`),
  getCryptoDecisions: (limit = 50) => request<any[]>(`/crypto/decisions?limit=${limit}`),
  scanCrypto: () => request<any>('/crypto/scan', { method: 'POST' }),
  getCryptoPortfolio: () => request<any>('/crypto/portfolio'),

  // Shorts
  getShortProposals: (status = 'pending_approval') =>
    request<any[]>(`/shorts/proposals?status=${status}`),
  getShortDecisions: (limit = 50) => request<any[]>(`/shorts/decisions?limit=${limit}`),
  approveShort: (id: number) =>
    request<any>(`/shorts/${id}/approve`, { method: 'POST' }),
  rejectShort: (id: number) =>
    request<any>(`/shorts/${id}/reject`, { method: 'POST' }),
  scanShorts: () => request<any>('/shorts/scan', { method: 'POST' }),

  // Backtest
  runBacktest: (params: Record<string, any>) =>
    request<any>('/backtest/run', { method: 'POST', body: JSON.stringify(params) }),
};

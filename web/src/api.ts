export type Direction = 'LONG' | 'SHORT'

export interface Account {
  balance: number
  nav: number
  currency: string
  unrealized_pnl: number
  margin_used: number
}

export interface Position {
  id: string
  instrument: string
  units: number
  entry_price: number
  stop_loss: number | null
  take_profit: number | null
  unrealized_pnl: number
  open_time: string | null
  direction: Direction
}

export interface Stats {
  trades: number
  wins: number
  losses: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  profit_factor: number | null
  expectancy: number
  max_drawdown: number
  max_drawdown_pct: number | null
}

export interface Analysis {
  time?: string
  candle_time?: string
  close?: number
  ema_fast?: number | null
  ema_mid?: number | null
  ema_slow?: number | null
  rsi?: number | null
  atr?: number | null
  signal?: Direction | null
  reason?: string
  action?: string
  error?: string
}

export interface Overview {
  account: Account | null
  positions: Position[]
  broker_error: string | null
  stats: Stats
  bot: {
    heartbeat: string | null
    status: string | null
    last_error: { time: string; message: string } | null
    analyses: Record<string, Analysis>
  }
  market_open: boolean
}

export interface Trade {
  id: number
  instrument: string
  direction: Direction
  units: number
  entry_time: string
  entry_price: number
  stop_loss: number | null
  take_profit: number | null
  risk_amount: number | null
  signal_reason: string | null
  status: 'OPEN' | 'CLOSED'
  exit_time: string | null
  exit_price: number | null
  pnl: number | null
  close_reason: string | null
}

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  ema_fast: number | null
  ema_mid: number | null
  ema_slow: number | null
  rsi: number | null
  atr: number | null
}

export interface TradeMarker {
  direction: Direction
  entry_time: string
  entry_price: number
  exit_time: string | null
  exit_price: number | null
  close_reason: string | null
  pnl: number | null
}

export interface StrategyParams {
  ema_fast: number
  ema_mid: number
  ema_slow: number
  rsi_period: number
  atr_period: number
  volume_period: number
  rsi_long_max: number
  rsi_short_min: number
  use_volume_filter: boolean
  atr_stop_mult: number
  reward_risk: number
}

export interface Config {
  broker: 'oanda' | 'mt5'
  instruments: string[]
  granularity: string
  risk_per_trade: number
  max_leverage: number
  max_open_trades: number
  daily_loss_limit: number
  max_spread_atr: number
  trading_hours_utc: string | null
  friday_cutoff_utc: number
  dry_run: boolean
  oanda_env: 'practice' | 'live' | null
  strategy: StrategyParams
}

export interface EquityPoint {
  time: string
  balance: number
  nav?: number
}

export interface BacktestTrade {
  instrument: string
  direction: Direction
  units: number
  entry_time: string
  entry_price: number
  stop_loss: number
  take_profit: number
  exit_time: string
  exit_price: number
  close_reason: string
  pnl: number
  signal_reason: string
}

export interface BacktestResult {
  initial_balance: number
  final_balance: number
  total_return_pct: number
  stats: Stats
  per_instrument: Record<string, Stats>
  period: { start?: string; end?: string; bars?: number; granularity?: string }
  trades: BacktestTrade[]
  equity: EquityPoint[]
}

export interface BacktestRequest {
  instruments: string[]
  granularity: string
  count: number
  initial_balance: number
  risk_per_trade: number
  strategy: Partial<StrategyParams>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* réponse non JSON */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  config: () => request<Config>('/api/config'),
  overview: () => request<Overview>('/api/overview'),
  trades: (limit = 200) => request<Trade[]>(`/api/trades?limit=${limit}`),
  equity: () => request<EquityPoint[]>('/api/equity'),
  candles: (instrument: string, count = 300) =>
    request<{ instrument: string; candles: Candle[]; trades: TradeMarker[] }>(
      `/api/candles/${instrument}?count=${count}`,
    ),
  backtest: (body: BacktestRequest) =>
    request<BacktestResult>('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}

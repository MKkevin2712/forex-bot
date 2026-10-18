import { useEffect, useState } from 'react'
import { api, type Config } from './api'
import { Banner } from './components/ui'
import { usePolling } from './hooks'
import { ago } from './format'
import { Backtest } from './pages/Backtest'
import { Dashboard } from './pages/Dashboard'

type Tab = 'dashboard' | 'backtest'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('dashboard')
  const overview = usePolling(() => api.overview(), 30_000)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    api.config().then(setConfig, (e: Error) => setConfigError(e.message))
    const id = window.setInterval(() => setNow(Date.now()), 15_000)
    return () => window.clearInterval(id)
  }, [])

  const bot = overview.data?.bot
  const heartbeatAge = bot?.heartbeat ? (now - new Date(bot.heartbeat).getTime()) / 1000 : Infinity
  const alive = heartbeatAge < 5 * 60
  const brokerLabel = config
    ? config.broker === 'oanda'
      ? `OANDA ${config.oanda_env === 'live' ? 'réel' : 'démo'}`
      : 'MetaTrader 5'
    : ''

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 17l5-6 4 4 8-10" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Forex Bot</span>
        </div>
        <nav className="tabs" aria-label="Sections">
          <button aria-current={tab === 'dashboard' ? 'page' : undefined} onClick={() => setTab('dashboard')}>
            Tableau de bord
          </button>
          <button aria-current={tab === 'backtest' ? 'page' : undefined} onClick={() => setTab('backtest')}>
            Backtest
          </button>
        </nav>
        <div className="status">
          {config && <span className="pill">{brokerLabel}</span>}
          {config?.dry_run && <span className="pill warn">Simulation</span>}
          {overview.data && (
            <span className={`pill ${overview.data.market_open ? '' : 'muted'}`}>
              Marché {overview.data.market_open ? 'ouvert' : 'fermé'}
            </span>
          )}
          <span className={`pill ${alive ? 'ok' : 'down'}`} title={bot?.status ?? undefined}>
            <span className="dot" />
            {alive ? `Bot actif · ${ago(bot?.heartbeat, now)}` : bot?.heartbeat ? `Bot muet · ${ago(bot.heartbeat, now)}` : 'Bot jamais lancé'}
          </span>
        </div>
      </header>

      <main>
        {configError && <Banner tone="error">API injoignable : {configError}. Lancez « forex-bot api ».</Banner>}
        {overview.error && !configError && <Banner tone="error">{overview.error}</Banner>}
        {config && tab === 'dashboard' && <Dashboard config={config} overview={overview.data} />}
        {config && tab === 'backtest' && <Backtest config={config} />}
      </main>
    </div>
  )
}

import type { ReactNode } from 'react'
import type { Direction, Stats } from '../api'
import { money, num, pct, toneOf } from '../format'

export function Card({ title, actions, children, className = '' }: {
  title?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label, value, hint, tone = '' }: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: string
}) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className={`kpi-value ${tone}`}>{value}</span>
      {hint != null && <span className="kpi-hint">{hint}</span>}
    </div>
  )
}

export function StatsKpis({ stats, currency = 'USD' }: { stats: Stats; currency?: string }) {
  return (
    <>
      <Kpi
        label="P&L réalisé"
        value={money(stats.total_pnl, currency)}
        tone={toneOf(stats.total_pnl)}
        hint={`${stats.trades} trade${stats.trades > 1 ? 's' : ''} clôturé${stats.trades > 1 ? 's' : ''}`}
      />
      <Kpi label="Taux de réussite" value={pct(stats.win_rate)} hint={`${stats.wins} gagnants · ${stats.losses} perdants`} />
      <Kpi
        label="Profit factor"
        value={num(stats.profit_factor)}
        tone={stats.profit_factor == null ? '' : stats.profit_factor >= 1 ? 'up' : 'down'}
        hint={`Espérance ${money(stats.expectancy, currency)} / trade`}
      />
      <Kpi
        label="Drawdown max"
        value={money(-stats.max_drawdown, currency)}
        tone={stats.max_drawdown > 0 ? 'down' : ''}
        hint={stats.max_drawdown_pct != null ? pct(-stats.max_drawdown_pct) : 'depuis le premier trade'}
      />
    </>
  )
}

export function DirectionTag({ direction }: { direction: Direction | null | undefined }) {
  if (!direction) return <span className="tag">—</span>
  return <span className={`tag ${direction === 'LONG' ? 'up' : 'down'}`}>{direction === 'LONG' ? 'Achat' : 'Vente'}</span>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}

export function Banner({ tone = 'warn', children }: { tone?: 'warn' | 'error' | 'info'; children: ReactNode }) {
  return (
    <div className={`banner ${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

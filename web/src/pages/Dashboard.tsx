import { useState } from 'react'
import { api, type Analysis, type Config, type Overview } from '../api'
import { EquityChart, PriceChart } from '../components/charts'
import { Banner, Card, DirectionTag, Empty, Kpi, StatsKpis } from '../components/ui'
import { usePolling } from '../hooks'
import { dateTime, money, num, pair, pips, price, signedMoney, toneOf } from '../format'

function trendOf(a: Analysis) {
  if (a.ema_fast == null || a.ema_mid == null || a.ema_slow == null) return '—'
  if (a.ema_fast > a.ema_mid && a.ema_mid > a.ema_slow) return 'Haussière'
  if (a.ema_fast < a.ema_mid && a.ema_mid < a.ema_slow) return 'Baissière'
  return 'Indécise'
}

export function Dashboard({ config, overview }: { config: Config; overview: Overview | null }) {
  const [instrument, setInstrument] = useState(config.instruments[0])
  const chart = usePolling(() => api.candles(instrument, 300), 120_000, [instrument])
  const trades = usePolling(() => api.trades(100), 60_000)
  const equity = usePolling(() => api.equity(), 300_000)

  const currency = overview?.account?.currency ?? 'USD'
  const account = overview?.account
  const { ema_fast, ema_mid, ema_slow } = config.strategy

  return (
    <div className="stack">
      {overview?.broker_error && <Banner tone="error">{overview.broker_error}</Banner>}
      {overview?.bot.last_error && (
        <Banner>
          Dernière erreur du bot ({dateTime(overview.bot.last_error.time)}) : {overview.bot.last_error.message}
        </Banner>
      )}

      <div className="kpis">
        <Kpi
          label="Solde"
          value={money(account?.balance, currency)}
          hint={account ? `Marge utilisée ${money(account.margin_used, currency)}` : 'courtier non connecté'}
        />
        <Kpi
          label="Valeur liquidative"
          value={money(account?.nav, currency)}
          tone={toneOf(account?.unrealized_pnl)}
          hint={account ? `Latent ${signedMoney(account.unrealized_pnl, currency)}` : undefined}
        />
        {overview && <StatsKpis stats={overview.stats} currency={currency} />}
      </div>

      <Card
        title={`${pair(instrument)} · ${config.granularity}`}
        actions={
          <div className="segmented" role="tablist" aria-label="Paire affichée">
            {config.instruments.map((i) => (
              <button key={i} role="tab" aria-selected={i === instrument} onClick={() => setInstrument(i)}>
                {pair(i)}
              </button>
            ))}
          </div>
        }
      >
        <div className="legend">
          <span className="swatch ema-fast" /> EMA {ema_fast}
          <span className="swatch ema-mid" /> EMA {ema_mid}
          <span className="swatch ema-slow" /> EMA {ema_slow}
          <span className="swatch rsi" /> RSI (seuils {config.strategy.rsi_short_min} / {config.strategy.rsi_long_max})
        </div>
        {chart.error ? (
          <Empty>Graphique indisponible : {chart.error}</Empty>
        ) : chart.data ? (
          <PriceChart instrument={instrument} candles={chart.data.candles} trades={chart.data.trades} params={config.strategy} />
        ) : (
          <div className="chart chart-price skeleton" />
        )}
      </Card>

      <Card title="Dernière analyse du bot">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Paire</th>
                <th>Bougie</th>
                <th className="num">Clôture</th>
                <th>Tendance</th>
                <th className="num">RSI</th>
                <th className="num">ATR</th>
                <th>Signal</th>
                <th>Décision</th>
              </tr>
            </thead>
            <tbody>
              {config.instruments.map((i) => {
                const a = overview?.bot.analyses[i]
                if (!a) {
                  return (
                    <tr key={i}>
                      <td>{pair(i)}</td>
                      <td colSpan={7} className="muted">Pas encore analysée</td>
                    </tr>
                  )
                }
                return (
                  <tr key={i}>
                    <td>{pair(i)}</td>
                    <td className="muted">{dateTime(a.candle_time)}</td>
                    <td className="num">{price(a.close, i)}</td>
                    <td>{trendOf(a)}</td>
                    <td className="num">{num(a.rsi, 1)}</td>
                    <td className="num">{pips(a.atr, i)}</td>
                    <td><DirectionTag direction={a.signal} /></td>
                    <td className="wrap">
                      {a.error ? <span className="down">{a.error}</span> : a.action === 'aucune' ? a.reason : a.action}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid-2">
        <Card title="Positions ouvertes">
          {overview && overview.positions.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Paire</th>
                    <th>Sens</th>
                    <th className="num">Unités</th>
                    <th className="num">Entrée</th>
                    <th className="num">SL</th>
                    <th className="num">TP</th>
                    <th className="num">Latent</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.positions.map((p) => (
                    <tr key={p.id}>
                      <td>{pair(p.instrument)}</td>
                      <td><DirectionTag direction={p.direction} /></td>
                      <td className="num">{num(Math.abs(p.units), 0)}</td>
                      <td className="num">{price(p.entry_price, p.instrument)}</td>
                      <td className="num">{price(p.stop_loss, p.instrument)}</td>
                      <td className="num">{price(p.take_profit, p.instrument)}</td>
                      <td className={`num ${toneOf(p.unrealized_pnl)}`}>{signedMoney(p.unrealized_pnl, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>Aucune position ouverte.</Empty>
          )}
        </Card>

        <Card title="Évolution du capital">
          {equity.data && equity.data.length > 1 ? (
            <EquityChart points={equity.data} />
          ) : (
            <Empty>La courbe apparaîtra après quelques heures de fonctionnement du bot.</Empty>
          )}
        </Card>
      </div>

      <Card title="Journal de trading">
        {trades.data && trades.data.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ouverture</th>
                  <th>Paire</th>
                  <th>Sens</th>
                  <th className="num">Unités</th>
                  <th className="num">Entrée</th>
                  <th className="num">SL</th>
                  <th className="num">TP</th>
                  <th className="num">Sortie</th>
                  <th>Motif</th>
                  <th className="num">P&L</th>
                </tr>
              </thead>
              <tbody>
                {trades.data.map((t) => (
                  <tr key={t.id}>
                    <td className="muted">{dateTime(t.entry_time)}</td>
                    <td>{pair(t.instrument)}</td>
                    <td><DirectionTag direction={t.direction} /></td>
                    <td className="num">{num(t.units, 0)}</td>
                    <td className="num">{price(t.entry_price, t.instrument)}</td>
                    <td className="num">{price(t.stop_loss, t.instrument)}</td>
                    <td className="num">{price(t.take_profit, t.instrument)}</td>
                    <td className="num">{price(t.exit_price, t.instrument)}</td>
                    <td>{t.status === 'OPEN' ? <span className="tag">En cours</span> : <span className="tag">{t.close_reason}</span>}</td>
                    <td className={`num ${toneOf(t.pnl)}`}>{signedMoney(t.pnl, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>Le bot n'a encore ouvert aucune position.</Empty>
        )}
      </Card>
    </div>
  )
}

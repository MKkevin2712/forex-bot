import { useState, type FormEvent } from 'react'
import { api, type BacktestResult, type Config } from '../api'
import { EquityChart } from '../components/charts'
import { Banner, Card, DirectionTag, Empty, Kpi, StatsKpis } from '../components/ui'
import { dateTime, money, num, pair, pct, price, signedMoney, toneOf } from '../format'

const GRANULARITIES = ['M15', 'M30', 'H1', 'H4', 'D']

export function Backtest({ config }: { config: Config }) {
  const s = config.strategy
  const [form, setForm] = useState({
    instruments: config.instruments,
    granularity: config.granularity,
    count: 5000,
    initial_balance: 10000,
    risk_pct: config.risk_per_trade * 100,
    atr_stop_mult: s.atr_stop_mult,
    reward_risk: s.reward_risk,
    rsi_long_max: s.rsi_long_max,
    rsi_short_min: s.rsi_short_min,
    use_volume_filter: s.use_volume_filter,
  })
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }))
  const toggle = (i: string) =>
    set('instruments', form.instruments.includes(i) ? form.instruments.filter((x) => x !== i) : [...form.instruments, i])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setRunning(true)
    setError(null)
    try {
      setResult(
        await api.backtest({
          instruments: form.instruments,
          granularity: form.granularity,
          count: form.count,
          initial_balance: form.initial_balance,
          risk_per_trade: form.risk_pct / 100,
          strategy: {
            atr_stop_mult: form.atr_stop_mult,
            reward_risk: form.reward_risk,
            rsi_long_max: form.rsi_long_max,
            rsi_short_min: form.rsi_short_min,
            use_volume_filter: form.use_volume_filter,
          },
        }),
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const numberField = (key: 'count' | 'initial_balance' | 'risk_pct' | 'atr_stop_mult' | 'reward_risk' | 'rsi_long_max' | 'rsi_short_min', label: string, step: number | 'any', min: number, max?: number) => (
    <label className="field">
      <span>{label}</span>
      <input type="number" step={step} min={min} max={max} value={form[key]} onChange={(e) => set(key, Number(e.target.value))} required />
    </label>
  )

  return (
    <div className="stack">
      <Card title="Paramètres du backtest">
        <form className="form" onSubmit={submit}>
          <fieldset className="field">
            <legend>Paires</legend>
            <div className="checks">
              {config.instruments.map((i) => (
                <label key={i} className="check">
                  <input type="checkbox" checked={form.instruments.includes(i)} onChange={() => toggle(i)} />
                  {pair(i)}
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field">
            <span>Unité de temps</span>
            <select value={form.granularity} onChange={(e) => set('granularity', e.target.value)}>
              {GRANULARITIES.map((g) => (
                <option key={g}>{g}</option>
              ))}
            </select>
          </label>
          {numberField('count', 'Nombre de bougies', 100, 300, 5000)}
          {numberField('initial_balance', 'Capital initial', 'any', 100)}
          {numberField('risk_pct', 'Risque par trade (%)', 'any', 0.1, 5)}
          {numberField('atr_stop_mult', 'Stop-loss (× ATR)', 'any', 0.3)}
          {numberField('reward_risk', 'Objectif (× risque)', 'any', 0.5)}
          {numberField('rsi_long_max', 'RSI max à l’achat', 1, 1, 100)}
          {numberField('rsi_short_min', 'RSI min à la vente', 1, 0, 99)}
          <label className="check field-inline">
            <input type="checkbox" checked={form.use_volume_filter} onChange={(e) => set('use_volume_filter', e.target.checked)} />
            Filtre de volume
          </label>
          <div className="form-actions">
            <button className="primary" type="submit" disabled={running || form.instruments.length === 0}>
              {running ? 'Calcul en cours…' : 'Lancer le backtest'}
            </button>
          </div>
        </form>
        <p className="note">
          Entrée à l'ouverture de la bougie suivant le signal, spread inclus, stop-loss considéré comme touché en premier
          quand le SL et le TP le sont dans la même bougie. Swaps non simulés. Un bon backtest ne garantit pas les
          résultats futurs.
        </p>
      </Card>

      {error && <Banner tone="error">{error}</Banner>}

      {result && (
        <>
          <div className="kpis">
            <Kpi
              label="Rendement"
              value={pct(result.total_return_pct, 2)}
              tone={toneOf(result.total_return_pct)}
              hint={`${money(result.initial_balance)} → ${money(result.final_balance)}`}
            />
            <Kpi
              label="Trades"
              value={result.stats.trades}
              hint={`sur ${num(result.period.bars ?? 0, 0)} bougies ${result.period.granularity ?? ''}`}
            />
            <StatsKpis stats={result.stats} />
          </div>
          <Card title="Courbe du capital" actions={<span className="muted small">{dateTime(result.period.start)} → {dateTime(result.period.end)}</span>}>
            {result.equity.length > 1 ? <EquityChart points={result.equity} height={280} /> : <Empty>Pas assez de trades pour tracer une courbe.</Empty>}
          </Card>
          <Card title="Par paire">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Paire</th>
                    <th className="num">Trades</th>
                    <th className="num">Réussite</th>
                    <th className="num">Profit factor</th>
                    <th className="num">P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.per_instrument).map(([i, st]) => (
                    <tr key={i}>
                      <td>{pair(i)}</td>
                      <td className="num">{st.trades}</td>
                      <td className="num">{pct(st.win_rate)}</td>
                      <td className="num">{num(st.profit_factor)}</td>
                      <td className={`num ${toneOf(st.total_pnl)}`}>{signedMoney(st.total_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title={`Trades (${result.trades.length})`}>
            {result.trades.length === 0 ? (
              <Empty>Aucun trade : les conditions de la stratégie n'ont jamais été réunies.</Empty>
            ) : (
              <div className="table-wrap tall">
                <table>
                  <thead>
                    <tr>
                      <th>Entrée</th>
                      <th>Paire</th>
                      <th>Sens</th>
                      <th className="num">Prix</th>
                      <th>Sortie</th>
                      <th className="num">Prix</th>
                      <th>Motif</th>
                      <th className="num">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...result.trades].reverse().map((t, k) => (
                      <tr key={k}>
                        <td className="muted">{dateTime(t.entry_time)}</td>
                        <td>{pair(t.instrument)}</td>
                        <td><DirectionTag direction={t.direction} /></td>
                        <td className="num">{price(t.entry_price, t.instrument)}</td>
                        <td className="muted">{dateTime(t.exit_time)}</td>
                        <td className="num">{price(t.exit_price, t.instrument)}</td>
                        <td><span className="tag">{t.close_reason}</span></td>
                        <td className={`num ${toneOf(t.pnl)}`}>{signedMoney(t.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}

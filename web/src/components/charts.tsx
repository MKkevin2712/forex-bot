import { useEffect, useRef } from 'react'
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { Candle, EquityPoint, StrategyParams, TradeMarker } from '../api'
import { useColorScheme } from '../hooks'
import { priceDigits } from '../format'

const ts = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function baseOptions() {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: cssVar('--text-muted'),
      fontFamily: 'inherit',
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: cssVar('--grid') },
      horzLines: { color: cssVar('--grid') },
    },
    rightPriceScale: { borderColor: cssVar('--border') },
    timeScale: {
      borderColor: cssVar('--border'),
      timeVisible: true,
      secondsVisible: false,
      // garde toute la période visible quand le conteneur prend sa vraie largeur
      lockVisibleTimeRangeOnResize: true,
    },
    crosshair: { mode: 1 },
    // la molette fait défiler la page ; zoom au glisser ou au pincement
    handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
  }
}

/** Ramène un horodatage sur l'ouverture de la bougie qui le contient (les marqueurs doivent tomber sur une bougie). */
function snap(times: number[], t: number): number | null {
  let lo = 0
  let hi = times.length - 1
  let found: number | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (times[mid] <= t) {
      found = times[mid]
      lo = mid + 1
    } else hi = mid - 1
  }
  return found
}

interface PriceChartProps {
  instrument: string
  candles: Candle[]
  trades: TradeMarker[]
  params: StrategyParams
}

export function PriceChart({ instrument, candles, trades, params }: PriceChartProps) {
  const ref = useRef<HTMLDivElement>(null)
  const scheme = useColorScheme()

  useEffect(() => {
    if (!ref.current || candles.length === 0) return
    const digits = priceDigits(instrument)
    const up = cssVar('--up')
    const down = cssVar('--down')
    const chart: IChartApi = createChart(ref.current, baseOptions())

    const priceFormat = { type: 'price' as const, precision: digits, minMove: 10 ** -digits }
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: up,
      downColor: down,
      borderVisible: false,
      wickUpColor: up,
      wickDownColor: down,
      priceFormat,
    })
    candleSeries.setData(
      candles.map((c) => ({ time: ts(c.time), open: c.open, high: c.high, low: c.low, close: c.close })),
    )

    const lines: [keyof Candle, string, number][] = [
      ['ema_fast', cssVar('--ema-fast'), 1],
      ['ema_mid', cssVar('--ema-mid'), 1],
      ['ema_slow', cssVar('--ema-slow'), 2],
    ]
    for (const [key, color, width] of lines) {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: width as 1 | 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat,
      })
      series.setData(
        candles.filter((c) => c[key] != null).map((c) => ({ time: ts(c.time), value: c[key] as number })),
      )
    }

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    volume.setData(
      candles.map((c) => ({
        time: ts(c.time),
        value: c.volume,
        color: c.close >= c.open ? cssVar('--up-soft') : cssVar('--down-soft'),
      })),
    )

    // RSI dans un second panneau, avec les seuils de la stratégie
    const rsi = chart.addSeries(
      LineSeries,
      { color: cssVar('--accent'), lineWidth: 1, priceLineVisible: false, lastValueVisible: true },
      1,
    )
    rsi.setData(candles.filter((c) => c.rsi != null).map((c) => ({ time: ts(c.time), value: c.rsi as number })))
    for (const level of [params.rsi_long_max, params.rsi_short_min]) {
      rsi.createPriceLine({
        price: level,
        color: cssVar('--text-faint'),
        lineStyle: LineStyle.Dashed,
        lineWidth: 1,
        axisLabelVisible: true,
        title: '',
      })
    }
    chart.panes()[1]?.setHeight(110)

    // Entrées et sorties du bot
    const times = candles.map((c) => ts(c.time) as number)
    const markers: SeriesMarker<Time>[] = []
    for (const t of trades) {
      const entry = snap(times, ts(t.entry_time))
      if (entry != null) {
        const long = t.direction === 'LONG'
        markers.push({
          time: entry as UTCTimestamp,
          position: long ? 'belowBar' : 'aboveBar',
          shape: long ? 'arrowUp' : 'arrowDown',
          color: long ? up : down,
          text: long ? 'Achat' : 'Vente',
        })
      }
      const exit = t.exit_time ? snap(times, ts(t.exit_time)) : null
      if (exit != null) {
        markers.push({
          time: exit as UTCTimestamp,
          position: 'aboveBar',
          shape: 'circle',
          color: (t.pnl ?? 0) >= 0 ? up : down,
          text: t.close_reason ?? '',
        })
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    createSeriesMarkers(candleSeries, markers)

    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [instrument, candles, trades, params, scheme])

  return <div ref={ref} className="chart chart-price" role="img" aria-label={`Graphique ${instrument}`} />
}

export function EquityChart({ points, height = 240 }: { points: EquityPoint[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const scheme = useColorScheme()

  useEffect(() => {
    if (!ref.current || points.length === 0) return
    const chart = createChart(ref.current, baseOptions())
    const accent = cssVar('--accent')
    const series = chart.addSeries(AreaSeries, {
      lineColor: accent,
      topColor: cssVar('--accent-soft'),
      bottomColor: 'transparent',
      lineWidth: 2,
      priceLineVisible: false,
    })
    // un seul point par horodatage (plusieurs trades peuvent se fermer sur la même bougie)
    const byTime = new Map<number, number>()
    for (const p of points) byTime.set(ts(p.time), p.balance)
    series.setData(
      [...byTime.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time: time as UTCTimestamp, value })),
    )
    chart.timeScale().fitContent()
    return () => chart.remove()
  }, [points, scheme])

  return <div ref={ref} className="chart" style={{ height }} role="img" aria-label="Courbe du capital" />
}

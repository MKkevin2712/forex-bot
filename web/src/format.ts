const numberFormats = new Map<number, Intl.NumberFormat>()

function nf(digits: number) {
  if (!numberFormats.has(digits)) {
    numberFormats.set(
      digits,
      new Intl.NumberFormat('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits }),
    )
  }
  return numberFormats.get(digits)!
}

export const isJpy = (instrument: string) => instrument.endsWith('JPY')
export const pipSize = (instrument: string) => (isJpy(instrument) ? 0.01 : 0.0001)
export const priceDigits = (instrument: string) => (isJpy(instrument) ? 3 : 5)
export const pair = (instrument: string) => instrument.replace('_', '/')

export function num(value: number | null | undefined, digits = 2) {
  return value == null || Number.isNaN(value) ? '—' : nf(digits).format(value)
}

export function money(value: number | null | undefined, currency = 'USD') {
  if (value == null) return '—'
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency }).format(value)
}

export function signedMoney(value: number | null | undefined, currency = 'USD') {
  if (value == null) return '—'
  return (value > 0 ? '+' : '') + money(value, currency)
}

export function price(value: number | null | undefined, instrument: string) {
  return num(value, priceDigits(instrument))
}

export function pips(distance: number | null | undefined, instrument: string) {
  return distance == null ? '—' : `${num(distance / pipSize(instrument), 1)} pips`
}

export function pct(value: number | null | undefined, digits = 1) {
  return value == null ? '—' : `${num(value, digits)} %`
}

const dateFormat = new Intl.DateTimeFormat('fr-FR', {
  day: '2-digit',
  month: '2-digit',
  year: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
})

export function dateTime(iso: string | null | undefined) {
  return iso ? `${dateFormat.format(new Date(iso))} UTC` : '—'
}

export function ago(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return 'jamais'
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `il y a ${seconds} s`
  if (seconds < 3600) return `il y a ${Math.round(seconds / 60)} min`
  if (seconds < 86400) return `il y a ${Math.round(seconds / 3600)} h`
  return `il y a ${Math.round(seconds / 86400)} j`
}

export const toneOf = (value: number | null | undefined) =>
  value == null || value === 0 ? '' : value > 0 ? 'up' : 'down'

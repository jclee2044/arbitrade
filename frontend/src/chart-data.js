import { TickMarkType } from 'lightweight-charts'

const eastern = options => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', ...options })
const dateFields = { year: 'numeric', month: '2-digit', day: '2-digit' }
const timeFields = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
const dateOnly = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/New_York', ...dateFields })
const minute = eastern({ ...dateFields, ...timeFields })
const second = eastern({ ...dateFields, ...timeFields, second: '2-digit', timeZoneName: 'longOffset' })
const parts = (formatter, time) => Object.fromEntries(formatter.formatToParts(time).map(({ type, value }) => [type, value]))
const dateString = ({ year, month, day }) => `${year}-${month}-${day}`
const clockString = ({ hour, minute }) => `${hour}:${minute}`

export const easternDate = time => dateOnly.format(time * 1000)

export function formatEastern(time) {
  if (!Number.isFinite(time)) return '—'
  const local = parts(minute, time * 1000)
  return `${dateString(local)} ${clockString(local)} ET`
}

export function easternTimestamp(iso) {
  const time = Date.parse(iso)
  if (!Number.isFinite(time)) return ''
  const local = parts(second, time)
  // Preserve receipt precision beyond the milliseconds supported by Date.
  const fraction = iso.match(/:\d{2}(\.\d+)/)?.[1] || ''
  return `${dateString(local)}T${clockString(local)}:${local.second}${fraction}${local.timeZoneName.slice(3)}`
}

export function formatEasternTimestamp(iso) {
  const local = easternTimestamp(iso)
  return local ? local.slice(0, -6).replace('T', ' ') + ' ET' : '—'
}

const tickFormats = {
  [TickMarkType.Year]: eastern({ year: 'numeric' }),
  [TickMarkType.Month]: eastern({ month: 'short' }),
  [TickMarkType.DayOfMonth]: eastern({ day: 'numeric' }),
  [TickMarkType.Time]: eastern(timeFields),
  [TickMarkType.TimeWithSeconds]: eastern({ ...timeFields, second: '2-digit' }),
}

export const easternTick = (time, type) => tickFormats[type].format(time * 1000)

export function adaptCandles(rows, volumeColors = { up: '#15847b', down: '#c9435b' }) {
  if (!Array.isArray(rows)) throw new Error('Expected a candle array')
  const candles = rows.map((row) => {
    const time = Date.parse(row.timestamp) / 1000
    if (!Number.isInteger(time) || time % 60 !== 0) {
      throw new Error('Expected minute-start timestamps')
    }
    for (const field of ['open', 'high', 'low', 'close', 'volume']) {
      if (field === 'volume' && row[field] === null) continue
      if (typeof row[field] !== 'number' || !Number.isFinite(row[field])) {
        throw new Error(`Invalid ${field}`)
      }
    }
    return { ...row, time }
  }).sort((a, b) => a.time - b.time)
  if (candles.some((c, i) => i > 0 && c.time === candles[i - 1].time)) {
    throw new Error('Duplicate candle timestamp')
  }
  return {
    candles,
    prices: candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })),
    volumes: candles.map(({ time, open, close, volume }) => ({
      time, ...(volume === null ? {} : { value: volume }), color: close >= open ? volumeColors.up : volumeColors.down,
    })),
  }
}

const dollars = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4,
})

export const price = value => value == null ? '—' : dollars.format(value)
export const average = value => value == null ? 'Unavailable' : value.toLocaleString('en-US', { maximumFractionDigits: 6 })

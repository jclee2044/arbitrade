export function formatUtc(time) {
  return new Date(time * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

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

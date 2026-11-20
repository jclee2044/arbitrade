export const entryFilters = {
  baseline: 'Nothing else — buy on the crossover',
  sma200: 'Close above the 200-day simple average',
  ema200: 'Close above the 200-day exponential average',
}

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
export const usd = value => dollars.format(value)
export const pct = value => Number(value).toFixed(2) + '%'

// Match fills in the selected long-only simulation. A skipped signal has no trade.
export function tradeAtSignal(run, index) {
  const f = run.facts[index]
  const order = run.orders.find(o => o.signal_at === f.cutoff)
  const filled = run.orders.filter(o => o.status === 'filled')
  const entry = order?.side === 'buy' ? (order.status === 'filled' ? order : null)
    : f.shares ? filled.findLast(o => o.side === 'buy' && o.fill_at <= f.cutoff) : null
  const exit = entry && filled.find(o => o.side === 'sell' && o.fill_at > entry.fill_at)
  return { order, entry, exit }
}

export function explainSignal(f) {
  const direction = f.crossover === 'up' ? 'above' : 'below'
  const trigger = f.crossover
    ? `The 20-day average (${usd(f.sma20)}) crossed ${direction} the 50-day average (${usd(f.sma50)}).`
    : 'The 20-day and 50-day averages did not cross at this close.'
  let reason
  if (f.crossover === 'down') reason = f.shares
    ? 'The strategy held one share and signaled an exit. Entry filters apply only to buys.'
    : 'The account was already flat, so there was no share to sell.'
  else if (f.reason === 'entry_filter_failed' || f.verdict === 'buy') {
    if (f.variant === 'baseline') reason = 'The account held no shares and the crossover was the only entry condition.'
    else {
      const average = f[f.variant]
      const relation = f.close > average ? 'above' : f.close === average ? 'equal to' : 'below'
      const name = f.variant === 'sma200' ? 'simple' : 'exponential'
      reason = `${f.ticker} closed at ${usd(f.close)}, ${relation} the 200-day ${name} average of ${usd(average)}. This filter allows a buy only above that average.`
    }
  } else reason = f.shares ? 'The account already held one share and had no exit signal.' : 'The account was flat and had no new buy signal.'
  return { trigger, reason }
}

// Compare one filled buy with leaving its purchase cash untouched. Stop marking
// that share when its actual exit fills; later trades belong to other signals.
export function forwardReview(run, index, baselineOrders) {
  const signal = run.facts[index]
  const skipped = signal.reason === 'entry_filter_failed'
  const orders = skipped ? baselineOrders : run.orders
  const buy = orders.find(o => o.signal_at === signal.cutoff && o.side === 'buy' && o.status === 'filled')
  const exit = buy && orders.find(o => o.side === 'sell' && o.status === 'filled' && o.fill_at > buy.fill_at)
  const rows = [1, 5, 20].map(days => {
    const bar = run.bars[index + days]
    if (!bar) return { days }
    const mark = exit && exit.fill_at <= bar.cutoff ? exit.fill_price : bar.close
    return { days, bar, movePct: (bar.close / signal.close - 1) * 100,
      accountChange: Number(run.facts[index + days].equity) - Number(signal.equity),
      tradePnl: buy ? mark - buy.fill_price : null }
  })
  return { rows, buy, exit, skipped }
}

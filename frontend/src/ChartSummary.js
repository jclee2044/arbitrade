import { h } from 'vue'
import { formatUtc, price } from './chart-data.js'

function candleReading(bar, signal, market, ended) {
  if (signal) {
    const side = signal === 'up' ? 'above' : 'below'
    return `SMA ${market.appliedShort} crossed ${side} SMA ${market.appliedLong} at the ${price(bar.close)} close.`
  }
  const change = bar.close - bar.open
  if (!change) return 'Price matched the candle open.'
  const verb = ended ? 'Closed' : 'Trading'
  return `${verb} ${price(Math.abs(change))} ${change > 0 ? 'above' : 'below'} the ${price(bar.open)} open.`
}

export default {
  props: { market: Object, decision: Object, busy: Boolean, message: String, proposalOpen: Boolean },
  emits: ['analyze', 'review'],
  setup(props, { emit, slots }) {
    return () => {
      const m = props.market
      const bar = m.selected
      const ended = m.selectedCoverage?.ended
      const result = props.decision
      const signal = m.tab === 'signals' && m.selectedAverage?.signal
      const candleLabel = m.pinned ? 'Pinned candle' : 'Latest candle'
      return h('section', { class: 'summary-card', 'aria-labelledby': 'summary-title' }, [
        h('h2', { id: 'summary-title' }, 'AI summary'),
        result ? h('div', { class: 'model-summary', 'aria-live': 'polite' }, [
          h('p', { class: 'summary-meta' }, [result.model_call_kind, result.provider, result.model].filter(Boolean).join(' · ')),
          h('h3', result.proposal ? 'Model proposal · ' + result.proposal : 'Analysis unavailable'),
          result.image_analysis?.answers?.crossover ? h('p', 'Chart reading · ' + result.image_analysis.answers.crossover.choice) : null,
          result.review?.reviewer?.verdict ? h('p', 'Reviewer · ' + result.review.reviewer.verdict.replaceAll('_',' ')) : null,
          h('p', result.error_code ? 'Result · ' + result.error_code.replaceAll('_',' ') : 'Validation · ' + result.validation_status),
        ]) : bar && !ended ? h('p', { class: 'summary-meta' }, 'Decision API can interpret the visible chart, including a forming candle.') : null,
        h('div', { class: 'observed-candle' }, [
          h('p', { class: 'summary-meta' }, bar ? candleLabel + ' · ' + formatUtc(bar.time) : 'Candle evidence'),
          h('h3', !bar ? 'Awaiting a candle' : signal ? (signal === 'up' ? 'Upward' : 'Downward') + ' SMA crossover' : (ended ? 'Close ' : 'Latest price ') + price(bar.close)),
          bar ? h('p', { class: 'candle-reading' }, candleReading(bar, signal, m, ended)) : null,
          bar ? h('p', { class: 'bar-state' }, (ended ? 'Ended' : 'Forming') + ' · ' + (m.selectedCoverage.coverage_complete ? 'Complete coverage' : 'Partial coverage')) : null,
          bar && m.chartStudies.length ? h('dl', { class: 'study-readings' }, m.chartStudies.map(item => h('div', [
            h('dt', { class: ['study-key', item.type === 'ema' && 'dashed'], style: { '--line': item.color } }, item.name),
            h('dd', item.value == null ? '—' : price(item.value)),
          ]))) : null,
        ]),
        props.message ? h('p', { class: 'summary-note', role: 'status' }, props.message) : null,
        m.lastEnded && !ended ? h('button', { class: 'text-button inspect-last', onClick: () => m.pin(m.lastEnded.time) }, 'Inspect last close') : null,
        h('div', { class: 'summary-actions' }, [
          h('button', { class: 'primary', disabled: props.busy || !m.candles.length, onClick: () => emit('analyze') },
            props.busy ? 'Analyzing…' : 'Decision API'),
          h('button', { class: 'review-link', 'aria-expanded': props.proposalOpen, 'aria-controls': 'proposal-view',
            onClick: () => emit('review') }, props.proposalOpen ? 'Close paper proposal' : 'Review paper proposal'),
        ]),
        slots.default?.(),
      ])
    }
  },
}

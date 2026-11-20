import DrawingLayer from './DrawingLayer.js'
import { h } from 'vue'
import { formatEastern, formatEasternTimestamp, price } from './chart-data.js'
import { timeframes } from './chart-studies.js'

function replayControls(m) {
  return h('section', { class: 'replay-controls', 'aria-label': 'Recorded observations' }, [
    h('div', { class: 'replay-fields' }, [
      h('label', { for: 'replay-symbol' }, ['Saved symbol', h('select', { id: 'replay-symbol', value: m.replaySymbol,
        onChange: e => m.chooseSymbol(e.target.value) }, m.saved.map(item => h('option', { value: item.symbol }, item.symbol)))]),
      ...[['start', 'From'], ['end', 'Through']].map(([key, label]) => h('label', { for: 'replay-' + key }, [
        label + ' · receipt time (ET)', h('input', { id: 'replay-' + key, value: m[key],
          placeholder: 'YYYY-MM-DDTHH:mm:ss±HH:mm', 'aria-describedby': 'replay-offset',
          onInput: e => { m[key] = e.target.value } }),
      ])),
    ]),
    h('p', { id: 'replay-offset', class: 'fine-print' }, 'Use -04:00 for daylight time or -05:00 for standard time.'),
    h('div', { class: 'actions' }, [
      h('button', { onClick: m.connect }, 'Load / restart replay'),
      h('button', { disabled: m.waiting || !m.replay || m.replay.done, onClick: m.next }, 'Next observation'),
      h('button', { class: 'primary', disabled: !m.replay || m.replay.done, onClick: m.togglePlayback }, m.playing ? 'Pause replay' : 'Play replay'),
    ]),
    m.replay ? h('p', { id: 'replay-status' }, m.replay.message || `${m.replay.position} / ${m.replay.total} receipts${m.replay.done ? ' · Finished' : ''}`) : null,
    m.replay?.current ? h('p', { id: 'replay-time', class: 'fine-print' },
      `Replaying observation: ${m.replay.current.source_time_utc ? formatEasternTimestamp(m.replay.current.source_time_utc) : 'Unknown source time'} · Received: ${formatEasternTimestamp(m.replay.current.received_at_utc)}`) : null,
  ])
}

function hoverCard(m) {
  const bar = m.hoveredCandle
  if (!bar) return null
  const rows = [['Open', price(bar.open)], ['High', price(bar.high)], ['Low', price(bar.low)], ['Close', price(bar.close)],
    ...(bar.volume == null ? [] : [[m.coverage[bar.time]?.volume_provenance === 'yahoo_quote_counter'
      ? 'Observed volume' : 'Volume', bar.volume.toLocaleString('en-US')]])]
  return h('div', { class: 'hover-card', 'aria-hidden': 'true',
    style: { left: `clamp(4px, ${m.hover.x + 14}px, calc(100% - 178px))`,
      top: `clamp(4px, ${m.hover.y + 14}px, calc(100% - 166px))` } }, [
    h('strong', formatEastern(bar.time)),
    h('dl', { class: 'facts' }, rows.flatMap(([key, value]) => [h('dt', key), h('dd', value)])),
  ])
}

export default {
  props: { market: Object, chartHost: Function, drawingOpen: Boolean },
  setup(props) {
    return () => {
      const m = props.market
      const last = m.latest
      return h('section', { class: 'market-column', 'aria-labelledby': 'chart-title' }, [
        h('h2', { id: 'chart-title', class: 'sr-only' }, `${m.mode === 'replay' ? 'Replay · ' : ''}${m.symbol} · ${m.timeframe} candles`),
        h('div', { id: 'timeframe', role: 'group', 'aria-label': 'Candle timeframe' }, [
          h('span', 'Timeframe'), ...Object.entries(timeframes).map(([value, label]) => h('button', {
            'data-frame': value, 'aria-pressed': m.timeframe === value,
            onClick: () => { if (m.timeframe !== value) { m.timeframe = value; m.connect() } },
          }, label)),
        ]),
        m.mode === 'replay' ? replayControls(m) : null,
        h('div', { class: 'overlay-legend', 'aria-label': 'Plotted indicators' }, m.chartStudies.map(item =>
          h('span', { class: ['study-key', item.type === 'ema' && 'dashed'], style: { '--line': item.color } }, item.name))),
        h('div', { class: 'plot-wrap' }, [
          h('div', { ref: props.chartHost, class: 'chart', role: 'img', 'aria-label': `${m.symbol} candlesticks with aligned volume below. Hover for values or click a candle to pin it.` }),
          h(DrawingLayer, { market: m, active: props.drawingOpen }),
          m.failure ? h('p', { class: 'chart-empty chart-error', role: 'alert' }, m.failure)
            : !last ? h('p', { class: 'chart-empty' }, m.mode === 'replay' ? 'No regular-session candles at this replay step.' : 'Waiting for stored or live observations in a regular exchange session.') : null,
          hoverCard(m),
        ]),
      ])
    }
  },
}

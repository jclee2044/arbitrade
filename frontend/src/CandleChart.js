import { h, ref } from 'vue'
import { formatUtc, price } from './chart-data.js'
import { timeframes } from './chart-studies.js'

function replayControls(m) {
  return h('section', { class: 'replay-controls', 'aria-label': 'Recorded observations' }, [
    h('div', { class: 'replay-fields' }, [
      h('label', { for: 'replay-symbol' }, ['Saved symbol', h('select', { id: 'replay-symbol', value: m.replaySymbol,
        onChange: e => m.chooseSymbol(e.target.value) }, m.saved.map(item => h('option', { value: item.symbol }, item.symbol)))]),
      ...[['start', 'From'], ['end', 'Through']].map(([key, label]) => h('label', { for: 'replay-' + key }, [
        label + ' · receipt time', h('input', { id: 'replay-' + key, value: m[key],
          placeholder: 'YYYY-MM-DDTHH:mm:ssZ', onInput: e => { m[key] = e.target.value } }),
      ])),
    ]),
    h('div', { class: 'actions' }, [
      h('button', { onClick: m.connect }, 'Load / restart replay'),
      h('button', { disabled: m.waiting || !m.replay || m.replay.done, onClick: m.next }, 'Next observation'),
      h('button', { class: 'primary', disabled: !m.replay || m.replay.done, onClick: m.togglePlayback }, m.playing ? 'Pause replay' : 'Play replay'),
    ]),
    m.replay ? h('p', { id: 'replay-status' }, m.replay.message || `${m.replay.position} / ${m.replay.total} receipts${m.replay.done ? ' · Finished' : ''}`) : null,
    m.replay?.current ? h('p', { id: 'replay-time', class: 'fine-print' },
      `Replaying observation: ${m.replay.current.source_time_utc || 'Unknown source time'} · Received: ${m.replay.current.received_at_utc}`) : null,
  ])
}

function inspector(m) {
  const bar = m.selected
  if (!bar) return null
  const facts = [
    ['Date and time', formatUtc(bar.time)], ['Open', bar.open], ['High', bar.high], ['Low', bar.low], ['Close', bar.close],
    ['Volume', bar.volume == null ? 'Unknown' : bar.volume.toLocaleString('en-US') + ' shares'],
    ['Interval', m.selectedCoverage?.ended ? 'Ended' : 'Still forming'],
    ['Coverage', m.selectedCoverage?.coverage_complete ? 'Complete' : 'Partial'],
  ]
  return h('div', { class: 'candle-inspector' }, [
    h('div', { class: 'candle-strip' }, [
      h('div', { class: 'strip-date' }, [h('span', m.pinned ? 'Pinned candle' : 'Latest candle'), h('strong', formatUtc(bar.time))]),
      h('dl', ['open','high','low','close'].map(key => h('div', [h('dt', key[0].toUpperCase() + key.slice(1)), h('dd', price(bar[key]))]))),
    ]),
    h('div', { class: 'inspect-controls' }, [
      h('label', { for: 'candle-time' }, 'Inspect candle'),
      h('select', { id: 'candle-time', value: m.selectedTime, onChange: e => m.pin(Number(e.target.value)) },
        m.candles.map(c => h('option', { value: c.time }, formatUtc(c.time)))),
      m.pinned ? h('button', { class: 'text-button', onClick: m.followLatest }, 'Follow latest') : null,
    ]),
    h('details', { class: 'facts-disclosure' }, [
      h('summary', 'Candle details'),
      h('dl', { class: 'candle-values facts' }, facts.flatMap(([key, value]) => [h('dt', key), h('dd', String(value))])),
    ]),
  ])
}

function hoverCard(m) {
  const bar = m.hoveredCandle
  if (!bar) return null
  const rows = [['Open', price(bar.open)], ['High', price(bar.high)], ['Low', price(bar.low)], ['Close', price(bar.close)],
    ['Volume', bar.volume == null ? 'Unknown' : bar.volume.toLocaleString('en-US')]]
  return h('div', { class: 'hover-card', 'aria-hidden': 'true',
    style: { left: `clamp(4px, ${m.hover.x + 14}px, calc(100% - 178px))`,
      top: `clamp(4px, ${m.hover.y + 14}px, calc(100% - 166px))` } }, [
    h('strong', formatUtc(bar.time)),
    h('dl', { class: 'facts' }, rows.flatMap(([key, value]) => [h('dt', key), h('dd', value)])),
  ])
}

function feedAge(seconds) {
  if (seconds < 60) return seconds + 's'
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm'
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h'
  return Math.floor(seconds / 86400) + 'd'
}

export default {
  props: { market: Object, chartHost: Function },
  setup(props) {
    const result = ref('')
    const checking = ref(false)
    async function checkConnection() {
      checking.value = true
      try {
        const response = await fetch('/api/health')
        if (!response.ok) throw Error('HTTP ' + response.status)
        const data = await response.json()
        if (data.status !== 'ok') throw Error('Unexpected health response')
        result.value = 'Backend connected: ' + JSON.stringify(data)
      } catch (error) {
        result.value = 'Backend unavailable: ' + error.message
      } finally { checking.value = false }
    }

    return () => {
      const m = props.market
      const last = m.latest
      const previous = m.candles.at(-2)
      const delta = last && previous ? last.close - previous.close : null
      const sourceName = /construct|test_data=true/i.test(m.source) ? 'Constructed data' :
        m.mode === 'replay' ? 'Recorded observations' : 'Yahoo Finance'
      const linkDown = /disconnected|error/i.test(m.transport)
      const status = linkDown ? 'Connection lost' : m.mode === 'replay' ? 'Replay' : (m.feed.status || 'Waiting')
      const isCurrent = !linkDown && (m.mode === 'replay' || m.feed.status === 'live')
      const lastAge = m.mode === 'live' && m.feed.source_time_utc ? feedAge(parseInt(m.age, 10)) : null
      return h('section', { class: 'market-column', 'aria-labelledby': 'chart-title' }, [
        h('div', { class: 'quote-toolbar' }, [
          h('h2', { id: 'chart-title', class: 'sr-only' }, `${m.mode === 'replay' ? 'Replay · ' : ''}${m.symbol} · ${m.timeframe} candles`),
          h('div', { class: 'quote-group' }, [
            h('span', { class: 'last-price' }, price(last?.close)),
            h('span', { class: 'quote-label' }, m.mode === 'replay' ? 'Replay price' : 'Last price'),
            delta != null ? h('span', { class: ['price-move', delta < 0 && 'negative'],
              title: 'Change from the preceding candle close' }, (delta >= 0 ? '+' : '−') + price(Math.abs(delta))) : null,
          ]),
        ]),
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
          h('div', { ref: props.chartHost, class: 'chart', role: 'img', 'aria-label': `${m.symbol} candlesticks with aligned volume below. Use Inspect candle for values.` }),
          !last ? h('p', { class: 'chart-empty' }, m.mode === 'replay' ? 'No regular-session candles at this replay step.' : 'Waiting for stored or live observations in a regular exchange session.') : null,
          hoverCard(m),
        ]),
        h('div', { class: 'plot-key' }, [
          h('span', last && last.volume == null ? 'Latest volume unavailable' : 'Volume · shares'),
          h('span', 'UTC'),
        ]),
        h('div', { class: 'feed-strip' }, [
          h('span', { id: 'market-status', class: ['feed-state', !isCurrent && 'feed-muted'] }, status),
          h('span', { id: 'market-source' }, sourceName),
          h('span', { id: 'market-age' }, lastAge ? 'Source updated ' + lastAge + ' ago' : m.mode === 'live' ? 'Awaiting source time' : 'Recorded timeline'),
        ]),
        m.failure ? h('p', { role: 'alert' }, m.failure) : null,
        inspector(m),
        h('details', { class: 'feed-details' }, [
          h('summary', 'Feed details'),
          h('p', `Source: ${m.source} · UTC · Regular exchange sessions · Volume in shares`),
          h('p', { id: 'transport-status' }, `Chart: ${m.transport} · Feed: ${m.feed.status}${m.mode === 'live' ? ' · Source age: ' + m.age : ''}`),
          m.feed.source_time_utc ? h('p', 'Latest source observation: ' + m.feed.source_time_utc) : null,
          h('button', { disabled: checking.value, onClick: checkConnection }, checking.value ? 'Checking…' : 'Check connection'),
          result.value ? h('p', { role: 'status' }, result.value) : null,
          h('p', { class: 'attribution' }, ['TradingView Lightweight Charts™ · © 2026 ', h('a', { href: 'https://www.tradingview.com/', target: '_blank', rel: 'noopener noreferrer' }, 'TradingView, Inc.')]),
        ]),
      ])
    }
  },
}

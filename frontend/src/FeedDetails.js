import { h, ref } from 'vue'
import { formatEasternTimestamp } from './chart-data.js'

export default {
  props: { market: Object },
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
      } finally {
        checking.value = false
      }
    }

    return () => {
      const m = props.market
      const historyStatus = m.mode === 'live' ? m.feed.historical?.status : null
      return h('details', { class: 'rail-details feed-details' }, [
        h('summary', 'Feed details'),
        h('p', `Source: ${m.source} · ET · Regular exchange sessions · Volume in shares`),
        h('p', 'Observed volume is the cumulative change from saved Yahoo updates.'),
        h('p', { id: 'transport-status' }, `Chart: ${m.transport} · Feed: ${m.feed.status}${m.mode === 'live' ? ' · Source age: ' + m.age : ''}`),
        m.feed.source_time_utc ? h('p', 'Latest source observation: ' + formatEasternTimestamp(m.feed.source_time_utc)) : null,
        historyStatus === 'unavailable' ? h('p', { role: 'status' }, 'Historical download unavailable. Showing recorded candles; retrying automatically.')
          : historyStatus === 'cached' ? h('p', { role: 'status' }, 'Cached history; download retry pending.') : null,
        h('button', { disabled: checking.value, onClick: checkConnection }, checking.value ? 'Checking…' : 'Check connection'),
        result.value ? h('p', { role: 'status' }, result.value) : null,
        h('p', { class: 'attribution' }, ['TradingView Lightweight Charts™ · © 2026 ',
          h('a', { href: 'https://www.tradingview.com/', target: '_blank', rel: 'noopener noreferrer' }, 'TradingView, Inc.')]),
      ])
    }
  },
}

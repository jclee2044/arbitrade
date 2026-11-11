import { createApp, h, ref } from 'vue'
import CandleChart from './CandleChart.js'
import VoicePanel from './VoicePanel.js'
import './style.css'

createApp({
  setup() {
    const result = ref('Ready to check the connection.')
    const checking = ref(false)

    async function checkConnection() {
      checking.value = true
      result.value = 'Checking…'
      try {
        const response = await fetch('/api/health')
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data = await response.json()
        if (data.status !== 'ok') throw new Error('Unexpected health response')
        result.value = `Backend connected: ${JSON.stringify(data)}`
      } catch (error) {
        result.value = `Backend unavailable: ${error.message}`
      } finally {
        checking.value = false
      }
    }

    return () => h('main', [
      h('h1', 'Arbitrade'),
      h('p', 'Check the local backend connection.'),
      h('button', {
        disabled: checking.value,
        onClick: checkConnection,
      }, checking.value ? 'Checking…' : 'Check connection'),
      h('p', { role: 'status', 'aria-live': 'polite' }, result.value),
      h(CandleChart),
      h(VoicePanel),
    ])
  },
}).mount('#app')

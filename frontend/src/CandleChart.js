import { h, ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import PaperTrading from './PaperTrading.js'
import DecisionPanel from './DecisionPanel.js'
import AutomationPanel from './AutomationPanel.js'
import { adaptCandles, formatUtc } from './chart-data.js'

export default {
  setup() {
    const availableTypes = ref([])
    const indicatorType = ref('')
    const indicatorName = ref('')
    const indicatorSettings = ref({})
    const indicatorError = ref('')
    const indicatorSaving = ref(false)
    const configured = ref([])
    const editedWindows = ref({})
    async function saveWindow(item) {
      indicatorError.value = ''
      const window = Number(editedWindows.value[item.id] ?? item.settings.window)
      try {
        const response = await fetch('/api/indicators/' + item.id, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ settings: { ...item.settings, window } }),
        })
        const result = await response.json()
        if (!response.ok) throw Error(result.detail || 'Could not save window')
        if (mode.value === 'replay' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ action: 'refresh' }))
      } catch (error) { indicatorError.value = error.message }
    }
    const selectedType = computed(() => availableTypes.value.find((item) => item.type === indicatorType.value))
    const configuredSeries = new Map()
    const palette = ['#7c3aed', '#0e7490', '#b91c1c', '#4d7c0f']
    function chooseType(value) {
      indicatorType.value = value
      const definition = availableTypes.value.find((item) => item.type === value)
      indicatorSettings.value = Object.fromEntries(Object.entries(definition?.settings || {}).map(([key, spec]) => [key, String(spec.default)]))
    }
    async function addIndicator() {
      indicatorError.value = ''
      const settings = {}
      for (const [key, spec] of Object.entries(selectedType.value?.settings || {})) {
        const raw = indicatorSettings.value[key]
        const value = Number(raw)
        if (!/^[1-9]\d*$/.test(raw) || !Number.isSafeInteger(value) || value < spec.minimum) {
          indicatorError.value = `${spec.label} must be a positive whole number.`
          return
        }
        settings[key] = value
      }
      if (!indicatorName.value.trim()) {
        indicatorError.value = 'Enter an indicator name.'
        return
      }
      const selection = { symbol: symbol.value, timeframe: timeframe.value }
      indicatorSaving.value = true
      try {
        const response = await fetch('/api/indicators', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...selection, type: indicatorType.value, name: indicatorName.value, settings }),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save indicator.')
        indicatorName.value = ''
        if (selection.symbol === symbol.value && selection.timeframe === timeframe.value) {
          // Request a fresh server snapshot without advancing or restarting replay.
          if (mode.value === 'replay' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ action: 'refresh' }))
          // Live status includes configuration changes on its next periodic update.
        }
      } catch (error) {
        indicatorError.value = error.message
      } finally {
        indicatorSaving.value = false
      }
    }
    const shortWindow = ref('20')
    const longWindow = ref('50')
    const settingsError = ref('')
    const averages = ref(null)
    const averageRows = computed(() => averages.value?.rows || [])
    const signals = computed(() => averageRows.value.filter((row) => row.signal))
    const selectedAverage = computed(() => averageRows.value.find((row) => Date.parse(row.timestamp) / 1000 === selectedTime.value))
    const displayAverage = (value) => value == null ? 'Unavailable' : value.toLocaleString('en-US', { maximumFractionDigits: 6 })
    const paperAccount = ref('live')
    const mode = ref('live')
    const saved = ref([])
    const symbol = ref('AAPL')
    const start = ref('')
    const end = ref('')
    const replay = ref(null)
    const playing = ref(false)
    const waiting = ref(false)
    let playback
    function chooseSymbol(value) {
      symbol.value = value
      const selection = saved.value.find((item) => item.symbol === value)
      start.value = selection?.start || ''
      end.value = selection?.end || ''
    }
    function next() {
      if (socket?.readyState === WebSocket.OPEN && !waiting.value && !replay.value?.done) {
        waiting.value = true
        socket.send(JSON.stringify({ action: 'next' }))
      }
    }
    const container = ref(null)
    const candles = ref([])
    const coverage = ref({})
    const selectedTime = ref(null)
    const timeframe = ref('1m')
    const transport = ref('Connecting')
    const feed = ref({ status: 'connecting' })
    const source = ref('Yahoo Finance · stored observations')
    const failure = ref('')
    const clock = ref(Date.now())
    const selected = computed(() => candles.value.find((c) => c.time === selectedTime.value))
    const age = computed(() => feed.value.source_time_utc
      ? `${Math.max(0, (clock.value - Date.parse(feed.value.source_time_utc)) / 1000).toFixed(0)} seconds`
      : 'No source observation received in this session')
    let chart, prices, volume, shortLine, longLine, markers, socket, retry, timer
    let generation = 0
    let disposed = false

    function renderRows(rows, statuses, reset = false) {
      const data = adaptCandles(rows)
      const wasEmpty = candles.value.length === 0
      const previousLatest = candles.value.at(-1)?.time
      const following = !selectedTime.value || selectedTime.value === candles.value.at(-1)?.time
      candles.value = data.candles
      coverage.value = Object.fromEntries(statuses.map((s) => [Date.parse(s.timestamp) / 1000, s]))
      prices.setData(data.prices)
      volume.setData(data.volumes)
      if (following || !data.candles.some((c) => c.time === selectedTime.value)) selectedTime.value = data.candles.at(-1)?.time
      if ((reset || wasEmpty) && data.candles.length) chart.timeScale().fitContent()
      else if (following && data.candles.at(-1)?.time > previousLatest) chart.timeScale().scrollToRealTime()
    }

    function renderAverages(value) {
      averages.value = value
      for (const [series, field] of [[shortLine, 'short'], [longLine, 'long']]) {
        series.setData((value?.rows || []).map((row) => ({
          time: Date.parse(row.timestamp) / 1000,
          ...(row[field] === null ? {} : { value: row[field] }),
        })))
      }
      shortLine.applyOptions({ title: `Short SMA (${value?.short_window || shortWindow.value})` })
      longLine.applyOptions({ title: `Long SMA (${value?.long_window || longWindow.value})` })
      markers.setMarkers((value?.rows || []).filter((row) => row.signal).map((row) => ({
        time: Date.parse(row.timestamp) / 1000,
        position: row.signal === 'up' ? 'belowBar' : 'aboveBar',
        shape: row.signal === 'up' ? 'arrowUp' : 'arrowDown',
        color: row.signal === 'up' ? '#087f5b' : '#b42340',
        text: row.signal === 'up' ? 'SMA up' : 'SMA down',
      })))
    }

    function renderConfigured(instances) {
      configured.value = instances
      const ids = new Set(instances.map((item) => item.id))
      for (const [id, series] of configuredSeries) {
        if (!ids.has(id)) { chart.removeSeries(series); configuredSeries.delete(id) }
      }
      for (const item of instances) {
        let series = configuredSeries.get(item.id)
        if (!series) {
          series = chart.addSeries(LineSeries, {
            color: palette[item.id % palette.length], lineWidth: 2, title: item.name,
            priceLineVisible: false,
          }, item.pane === 'price' ? 0 : 2)
          configuredSeries.set(item.id, series)
        }
        series.setData(item.rows.map((row) => ({ time: Date.parse(row.timestamp) / 1000,
          ...(row.value === null ? {} : { value: row.value }) })))
      }
    }

    function connect() {
      const short = Number(shortWindow.value), long = Number(longWindow.value)
      if (![shortWindow.value, longWindow.value].every((value) => /^[1-9]\d*$/.test(value)) ||
          !Number.isSafeInteger(short) || !Number.isSafeInteger(long) || short >= long) {
        settingsError.value = 'SMA windows must be positive whole numbers with short smaller than long.'
        return
      }
      settingsError.value = ''
      paperAccount.value = mode.value === 'live' ? 'live' : null
      clearTimeout(playback)
      playing.value = false
      waiting.value = false
      replay.value = null
      const token = ++generation
      clearTimeout(retry)
      socket?.close()
      candles.value = []
      coverage.value = {}
      selectedTime.value = null
      prices.setData([])
      volume.setData([])
      renderAverages(null)
      renderConfigured([])
      failure.value = ''
      transport.value = 'Connecting'
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const params = new URLSearchParams({ symbol: symbol.value, timeframe: timeframe.value,
        short_window: String(short), long_window: String(long) })
      if (mode.value === 'replay') {
        params.set('start', start.value)
        params.set('end', end.value)
      }
      socket = new WebSocket(`${protocol}//${location.host}/api/${mode.value}?${params}`)
      socket.onopen = () => { if (token === generation) transport.value = 'Connected to FastAPI' }
      socket.onmessage = ({ data }) => {
        if (token !== generation || disposed) return
        try {
          const message = JSON.parse(data)
          if (message.type === 'error') throw new Error(message.error)
          if (message.symbol !== symbol.value || message.interval !== timeframe.value) return
          waiting.value = false
          if (mode.value === 'replay') {
            clearTimeout(playback)
            replay.value = message.replay
            if (message.replay.done) playing.value = false
            if (playing.value) playback = setTimeout(next, 500)
          }
          feed.value = message.feed
          source.value = message.source
          if (message.type === 'snapshot') renderRows(message.candles, message.coverage, true)
          if (message.type === 'candle') {
            const rows = candles.value.filter((c) => c.timestamp !== message.candle.timestamp)
            rows.push(message.candle)
            const statuses = Object.values(coverage.value).filter((s) => s.timestamp !== message.candle.timestamp)
            statuses.push(message.completion)
            // Replaces matching timestamps, including late revisions, and appends
            // new intervals. Both chart panes use the same backend candle rows.
            renderRows(rows, statuses)
          }
          if (message.moving_averages) renderAverages(message.moving_averages)
          if (message.indicators) renderConfigured(message.indicators)
          if (message.paper_account_id) paperAccount.value = message.paper_account_id
        } catch (error) {
          failure.value = `Could not update chart: ${error.message}`
        }
      }
      socket.onclose = () => {
        if (token !== generation || disposed) return
        transport.value = 'Disconnected from FastAPI · retrying'
        playing.value = false
        clearTimeout(playback)
        if (mode.value === 'live') retry = setTimeout(connect, 3000)
        else transport.value = 'Disconnected from FastAPI'
      }
      socket.onerror = () => { if (token === generation) transport.value = 'FastAPI connection error' }
    }

    function inspect(event) {
      if (candles.value.some((c) => c.time === event.time)) selectedTime.value = event.time
    }

    onMounted(() => {
      chart = createChart(container.value, {
        autoSize: true,
        layout: { attributionLogo: true, textColor: '#263648', background: { type: 'solid', color: '#ffffff' } },
        localization: { timeFormatter: formatUtc },
        timeScale: { timeVisible: true, secondsVisible: false },
      })
      prices = chart.addSeries(CandlestickSeries, {
        upColor: '#15847b', downColor: '#c9435b', borderVisible: false,
        wickUpColor: '#15847b', wickDownColor: '#c9435b',
      }, 0)
      volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, title: 'Volume (shares)' }, 1)
      shortLine = chart.addSeries(LineSeries, { color: '#2563eb', lineWidth: 2, priceLineVisible: false }, 0)
      longLine = chart.addSeries(LineSeries, { color: '#b45309', lineWidth: 2, priceLineVisible: false }, 0)
      markers = createSeriesMarkers(prices, [])
      chart.panes()[1].setHeight(130)
      chart.subscribeCrosshairMove(inspect)
      timer = setInterval(() => { clock.value = Date.now() }, 1000)
      connect()
      fetch('/api/indicators/types').then((response) => {
        if (!response.ok) throw new Error('Could not load indicator types.')
        return response.json()
      }).then((types) => { availableTypes.value = types; chooseType(types[0]?.type || '') })
        .catch((error) => { indicatorError.value = error.message })
      fetch('/api/replay/selections').then((response) => {
        if (!response.ok) throw new Error('Could not load saved selections')
        return response.json()
      }).then((items) => { saved.value = items; chooseSymbol(symbol.value) })
        .catch((error) => { failure.value = error.message })
    })

    onBeforeUnmount(() => {
      disposed = true
      generation++
      clearTimeout(retry)
      clearTimeout(playback)
      clearInterval(timer)
      socket?.close()
      chart?.unsubscribeCrosshairMove(inspect)
      markers?.detach()
      chart?.remove()
    })

    return () => h('section', { 'aria-labelledby': 'chart-title' }, [
      h('h2', { id: 'chart-title' }, `${mode.value === 'replay' ? 'Replay · ' : ''}${symbol.value} · ${timeframe.value} candles`),
      h('label', { for: 'mode' }, 'Mode '),
      h('select', { id: 'mode', value: mode.value, onChange: (event) => {
        mode.value = event.target.value
        if (mode.value === 'live') symbol.value = 'AAPL'
        connect()
      } }, [h('option', { value: 'live' }, 'Live'), h('option', { value: 'replay' }, 'Replay')]),
      mode.value === 'replay' ? h('div', { key: 'replay-controls', class: 'replay-controls' }, [
        h('label', { for: 'replay-symbol' }, 'Saved symbol '),
        h('select', { id: 'replay-symbol', value: symbol.value,
          onChange: (event) => chooseSymbol(event.target.value) },
        saved.value.map((item) => h('option', { value: item.symbol }, item.symbol))),
        ...[['start', start], ['end', end]].flatMap(([name, value]) => [
          h('label', { for: `replay-${name}` }, `${name} receipt time (ISO 8601 with timezone) `),
          h('input', { id: `replay-${name}`, value: value.value,
            onInput: (event) => { value.value = event.target.value } }),
        ]),
        h('button', { onClick: connect }, 'Load / restart replay'),
        h('button', { disabled: waiting.value || !replay.value || replay.value.done, onClick: next }, 'Next observation'),
        h('button', { disabled: !replay.value || replay.value.done, onClick: () => {
          playing.value = !playing.value
          clearTimeout(playback)
          if (playing.value) next()
        } }, playing.value ? 'Pause replay' : 'Play replay'),
        replay.value ? h('p', { id: 'replay-status' }, replay.value.message ||
          `${replay.value.position} / ${replay.value.total} receipts${replay.value.done ? ' · Finished' : ''}`) : null,
        replay.value?.current ? h('p', { id: 'replay-time' },
          `Replaying observation: ${replay.value.current.source_time_utc || 'Unknown source time'} · Received: ${replay.value.current.received_at_utc}`) : null,
      ]) : null,
      h('label', { for: 'timeframe' }, 'Timeframe '),
      h('select', {
        id: 'timeframe', value: timeframe.value,
        onChange: (event) => { timeframe.value = event.target.value; connect() },
      }, ['1m', '5m', '15m', '1h', '1d'].map((value) => h('option', { value }, value === '1d' ? '1d · Daily' : value))),
      h('form', { key: 'sma-controls', class: 'sma-controls', onSubmit: (event) => { event.preventDefault(); connect() } }, [
        ...[['short', shortWindow], ['long', longWindow]].flatMap(([name, value]) => [
          h('label', { for: `sma-${name}` }, `${name === 'short' ? 'Short' : 'Long'} SMA window `),
          h('input', { id: `sma-${name}`, type: 'number', min: 1, step: 1, required: true,
            value: value.value, onInput: (event) => { value.value = event.target.value } }),
        ]),
        h('button', { type: 'submit' }, 'Apply SMA windows'),
      ]),
      settingsError.value ? h('p', { role: 'alert' }, settingsError.value) : null,
      h('p', { class: 'sma-legend' }, [
        h('span', { class: 'sma-short' }, `Blue: short SMA (${averages.value?.short_window || shortWindow.value})`),
        ' · ', h('span', { class: 'sma-long' }, `Brown: long SMA (${averages.value?.long_window || longWindow.value})`),
        ' · Completed candles only. Warm-up and unfinished candles: Unavailable.',
      ]),
      h('div', { key: 'indicator-controls', class: 'indicator-controls' }, [
        h('h3', 'Chart indicators'),
        h('form', { novalidate: true, onSubmit: (event) => { event.preventDefault(); addIndicator() } }, [
          h('label', { for: 'indicator-type' }, 'Indicator type'),
          h('select', { id: 'indicator-type', value: indicatorType.value, onChange: (event) => chooseType(event.target.value) },
            availableTypes.value.map((item) => h('option', { value: item.type }, item.label))),
          h('label', { for: 'indicator-name' }, 'Indicator name'),
          h('input', { id: 'indicator-name', value: indicatorName.value, maxlength: 80,
            onInput: (event) => { indicatorName.value = event.target.value } }),
          ...Object.entries(selectedType.value?.settings || {}).flatMap(([key, spec]) => [
            h('label', { for: `indicator-${key}` }, spec.label),
            h('input', { id: `indicator-${key}`, type: 'number', min: spec.minimum, step: 1,
              value: indicatorSettings.value[key], onInput: (event) => { indicatorSettings.value[key] = event.target.value } }),
          ]),
          h('button', { type: 'submit', disabled: indicatorSaving.value || !selectedType.value }, indicatorSaving.value ? 'Saving indicator…' : 'Add indicator'),
        ]),
        selectedType.value ? h('p', `${selectedType.value.description} Units: ${selectedType.value.units}.`) : null,
        h('p', 'Named indicators are saved for this symbol and timeframe. Completed candles only; warm-up gaps stay unavailable.'),
        indicatorError.value ? h('p', { role: 'alert' }, indicatorError.value) : null,
      ]),
      h('p', `Source: ${source.value} · UTC · Regular exchange sessions · Volume in shares`),
      h('p', { role: 'status' }, `Chart: ${transport.value} · Feed: ${feed.value.status}${mode.value === 'live' ? ` · Source age: ${age.value}` : ''}`),
      feed.value.source_time_utc ? h('p', `Latest source observation: ${feed.value.source_time_utc}`) : null,
      failure.value ? h('p', { role: 'alert' }, failure.value) : null,
      !candles.value.length ? h('p', mode.value === 'replay' ? 'No regular-session candles at this replay step.' : 'Waiting for stored or live observations in a regular exchange session.') : null,
      h('div', { key: 'chart', ref: container, class: 'chart', 'aria-label': 'AAPL candlesticks with aligned volume below' }),
      candles.value.length ? h('div', { key: 'inspector', class: 'candle-inspector' }, [
        h('label', { for: 'candle-time' }, 'Inspect candle (UTC)'),
        h('select', {
          id: 'candle-time', value: selectedTime.value,
          onChange: (event) => { selectedTime.value = Number(event.target.value) },
        }, candles.value.map((c) => h('option', { value: c.time, key: c.time }, formatUtc(c.time)))),
        selected.value ? h('dl', { class: 'candle-values' }, [
          ['Date and time', formatUtc(selected.value.time)],
          ['Open', selected.value.open], ['High', selected.value.high],
          ['Low', selected.value.low], ['Close', selected.value.close],
          ['Volume', selected.value.volume === null ? 'Unknown' : `${selected.value.volume.toLocaleString('en-US')} shares`],
          ['Interval', coverage.value[selectedTime.value]?.ended ? 'Ended' : 'Still forming'],
          ['Coverage', coverage.value[selectedTime.value]?.coverage_complete ? 'Complete' : 'Partial'],
        ].flatMap(([name, value]) => [h('dt', name), h('dd', String(value))])) : null,
      ]) : null,
      selected.value ? h('dl', { key: 'sma-values', class: 'sma-values' }, [
        ['Short SMA', displayAverage(selectedAverage.value?.short)],
        ['Long SMA', displayAverage(selectedAverage.value?.long)],
        ['Confirmed crossover', selectedAverage.value?.signal || 'None'],
      ].flatMap(([name, value]) => [h('dt', name), h('dd', value)])) : null,
      h('div', { key: 'sma-crossovers', class: 'sma-crossovers', 'aria-label': 'Confirmed SMA crossovers' }, [
        h('h3', 'Confirmed SMA crossovers'),
        signals.value.length ? h('ul', signals.value.map((row) => h('li', { key: row.timestamp },
          `${formatUtc(Date.parse(row.timestamp) / 1000)} · ${row.signal === 'up' ? 'Upward' : 'Downward'} · Short ${displayAverage(row.short)} · Long ${displayAverage(row.long)}`)))
          : h('p', 'No confirmed crossovers.'),
      ]),
      h('div', { key: 'configured-indicators', class: 'configured-indicators' }, [
        h('h3', 'Saved indicator values'),
        configured.value.length ? h('ul', configured.value.map((item) => {
          const value = item.rows.find((row) => Date.parse(row.timestamp) / 1000 === selectedTime.value)?.value
          return h('li', { key: item.id, 'data-indicator-name': item.name }, [
            h('strong', item.name), ` · ${item.type} · ${Object.entries(item.settings).map(([key, setting]) => `${key}: ${setting}`).join(', ')} · `,
            h('span', { class: 'indicator-value' }, displayAverage(value)), ` (${item.units})`,
            h('label', { for: `saved-window-${item.id}` }, ' Window '),
            h('input', { id: `saved-window-${item.id}`, type: 'number', min: 1, step: 1,
              value: editedWindows.value[item.id] ?? item.settings.window,
              onInput: event => { editedWindows.value[item.id] = event.target.value } }),
            h('button', { onClick: () => saveWindow(item) }, 'Save window'),
          ])
        })) : h('p', 'No named indicators saved for this chart.'),
      ]),
      h(DecisionPanel, { key: 'decision-panel', chartRange: () => chart?.timeScale().getVisibleRange(), accountId: paperAccount.value, symbol: symbol.value, interval: timeframe.value,
        candleTimestamp: selected.value?.timestamp, completed: Boolean(coverage.value[selectedTime.value]?.ended),
        shortWindow: averages.value?.short_window || Number(shortWindow.value), longWindow: averages.value?.long_window || Number(longWindow.value) }),
      h(AutomationPanel,{accountId:paperAccount.value,symbol:symbol.value,interval:timeframe.value,shortWindow:averages.value?.short_window||Number(shortWindow.value),longWindow:averages.value?.long_window||Number(longWindow.value),completed:Object.values(coverage.value).filter(c=>c.ended)}),
      h(PaperTrading, { key: 'paper-trading', accountId: paperAccount.value, symbol: symbol.value }),
      h('p', { class: 'attribution' }, [
        'TradingView Lightweight Charts™ · Copyright (с) 2025 TradingView, Inc. ',
        h('a', { href: 'https://www.tradingview.com/', target: '_blank', rel: 'noopener noreferrer' }, 'TradingView'),
      ]),
    ])
  },
}

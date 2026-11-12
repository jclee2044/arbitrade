import { reactive, ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createSeriesMarkers } from 'lightweight-charts'
import { adaptCandles, formatUtc } from './chart-data.js'
import { periodColor, studyColor } from './chart-studies.js'

export function useMarketChart(container) {
  const availableTypes = ref([])
  const indicatorType = ref('')
  const indicatorName = ref('')
  const indicatorSettings = ref({})
  const indicatorError = ref('')
  const indicatorSaving = ref(false)
  const configured = ref([])
  const presets = ref([])
  const presetSaving = ref(false)
  const tab = ref('indicators')
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
  async function togglePreset(kind, period) {
    if (presetSaving.value) return
    const token = generation
    const enabled = !presets.value.some(item => item.type === kind && item.settings.window === period)
    presetSaving.value = true
    indicatorError.value = ''
    try {
      const response = await fetch('/api/indicator-presets/' + kind + '/' + period, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: symbol.value, timeframe: timeframe.value, enabled }),
      })
      const result = await response.json()
      if (!response.ok) throw Error(result.detail || 'Could not save this preset.')
      if (token !== generation) return
      const previous = new Map(presets.value.map(item => [item.id, item.rows]))
      presets.value = result.map(item => ({ ...item, rows: previous.get(item.id) || [] }))
      drawStudies()
      if (mode.value === 'replay' && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ action: 'refresh' }))
    } catch (error) {
      if (token === generation) indicatorError.value = error.message
    } finally {
      if (token === generation) presetSaving.value = false
    }
  }
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
  const appliedShort = ref(20)
  const appliedLong = ref(50)
  const settingsError = ref('')
  const averages = ref(null)
  const averageRows = computed(() => averages.value?.rows || [])
  const signals = computed(() => averageRows.value.filter((row) => row.signal).reverse())
  const selectedAverage = computed(() => averageRows.value.find((row) => Date.parse(row.timestamp) / 1000 === selectedTime.value))
  const paperAccount = ref('live')
  const mode = ref('live')
  const saved = ref([])
  const symbol = ref('AAPL')
  const replaySymbol = ref('AAPL')
  const start = ref('')
  const end = ref('')
  const replay = ref(null)
  const playing = ref(false)
  const waiting = ref(false)
  let playback
  function chooseSymbol(value) {
    replaySymbol.value = value
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
  const pinned = ref(false)
  const hover = ref(null)
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

  function renderRows(rows, statuses) {
    const data = adaptCandles(rows, { up: '#608b78', down: '#a36f7e' })
    const wasEmpty = candles.value.length === 0
    const previousLatest = candles.value.at(-1)?.time
    const following = !pinned.value
    const scale = chart.timeScale()
    const visible = scale.getVisibleLogicalRange()
    const showingTail = visible && visible.to >= candles.value.length - 1
    candles.value = data.candles
    coverage.value = Object.fromEntries(statuses.map((s) => [Date.parse(s.timestamp) / 1000, s]))
    prices.setData(data.prices)
    volume.setData(data.volumes)
    if (following || !data.candles.some((c) => c.time === selectedTime.value)) {
      pinned.value = false
      selectedTime.value = data.candles.at(-1)?.time
    }
    const count = data.candles.length
    const capacity = Math.max(25, Math.floor(container.value.clientWidth / 10))
    if (wasEmpty && count > capacity) {
      scale.setVisibleLogicalRange({ from: count - capacity, to: count + 1 })
    } else if (count && (wasEmpty || (following && showingTail && visible.from <= 0 && count <= capacity))) {
      scale.fitContent()
    } else if (following && showingTail && data.candles.at(-1)?.time > previousLatest) {
      scale.scrollToRealTime()
    }
  }

  function renderAverages(value) {
    averages.value = value
    for (const [series, field] of [[shortLine, 'short'], [longLine, 'long']]) {
      series.setData((value?.rows || []).map((row) => ({
        time: Date.parse(row.timestamp) / 1000,
        ...(row[field] === null ? {} : { value: row[field] }),
      })))
    }
    renderMarkers()
  }

  function renderMarkers() {
    const rows = tab.value === 'signals' ? signals.value.slice().reverse() : []
    const plotted = rows.map(row => {
      const time = Date.parse(row.timestamp) / 1000
      const selected = pinned.value && time === selectedTime.value
      const up = row.signal === 'up'
      return { time, position: up ? 'belowBar' : 'aboveBar', shape: up ? 'arrowUp' : 'arrowDown',
        color: selected ? '#225d76' : up ? '#087f5b' : '#b42340', size: selected ? 1.4 : 1,
        text: (up ? 'SMA up' : 'SMA down') + (selected ? ' · Pinned' : '') }
    })
    if (pinned.value && !plotted.some(mark => mark.time === selectedTime.value)) {
      plotted.push({ time: selectedTime.value, position: 'aboveBar', shape: 'circle', color: '#225d76', text: 'Pinned' })
      plotted.sort((a, b) => a.time - b.time)
    }
    markers.setMarkers(plotted)
  }

  const pair = computed(() => [
    { name: 'SMA ' + appliedShort.value, color: periodColor(appliedShort.value), type: 'sma', value: selectedAverage.value?.short },
    { name: 'SMA ' + appliedLong.value, color: periodColor(appliedLong.value, '#81394e'), type: 'sma', value: selectedAverage.value?.long },
  ])
  const chartStudies = computed(() => tab.value === 'signals' ? pair.value : [...presets.value, ...configured.value].map(item => ({
    name: item.name, type: item.type, color: studyColor(item),
    value: selectedTime.value == null ? null : item.rows.find(row => Date.parse(row.timestamp) === selectedTime.value * 1000)?.value,
  })))

  function drawStudies() {
    const showPair = tab.value === 'signals'
    shortLine.applyOptions({ visible: showPair, color: periodColor(appliedShort.value) })
    longLine.applyOptions({ visible: showPair, color: periodColor(appliedLong.value, '#81394e') })
    const instances = showPair ? [] : [...presets.value, ...configured.value]
    const ids = new Set(instances.map((item) => item.id))
    for (const [id, series] of configuredSeries) {
      if (!ids.has(id)) { chart.removeSeries(series); configuredSeries.delete(id) }
    }
    for (const item of instances) {
      let series = configuredSeries.get(item.id)
      if (!series) {
        series = chart.addSeries(LineSeries, {
          color: studyColor(item), lineWidth: 2, lineStyle: item.type === 'ema' ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false, lastValueVisible: false,
        }, item.pane === 'price' ? 0 : 2)
        if (item.pane !== 'price') chart.panes()[2].setStretchFactor(0.35)
        configuredSeries.set(item.id, series)
      }
      series.setData(item.rows.map((row) => ({ time: Date.parse(row.timestamp) / 1000,
        ...(row.value === null ? {} : { value: row.value }) })))
    }
  }

  function selectTab(value) {
    tab.value = value
    drawStudies()
    renderAverages(averages.value)
  }

  function applyWindows() {
    const short = Number(shortWindow.value), long = Number(longWindow.value)
    if (![shortWindow.value, longWindow.value].every((value) => /^[1-9]\d*$/.test(value)) ||
        !Number.isSafeInteger(short) || !Number.isSafeInteger(long) || short >= long) {
      settingsError.value = 'SMA windows must be positive whole numbers with short smaller than long.'
      return
    }
    settingsError.value = ''
    appliedShort.value = short
    appliedLong.value = long
    connect()
  }

  function connect() {
    symbol.value = mode.value === 'live' ? 'AAPL' : replaySymbol.value
    paperAccount.value = mode.value === 'live' ? 'live' : null
    clearTimeout(playback)
    playing.value = false
    waiting.value = false
    replay.value = null
    const token = ++generation
    presetSaving.value = false
    clearTimeout(retry)
    socket?.close()
    socket = null
    candles.value = []
    coverage.value = {}
    selectedTime.value = null
    pinned.value = false
    hover.value = null
    source.value = mode.value === 'replay' ? 'Recorded observations' : 'Yahoo Finance'
    feed.value = { status: 'connecting' }
    prices.setData([])
    volume.setData([])
    renderAverages(null)
    configured.value = []
    presets.value = []
    drawStudies()
    chart.timeScale().applyOptions({ timeVisible: !['1d', '1w', '1mo'].includes(timeframe.value) })
    failure.value = ''
    transport.value = 'Connecting'
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({ symbol: symbol.value, timeframe: timeframe.value,
      short_window: String(appliedShort.value), long_window: String(appliedLong.value) })
    if (mode.value === 'replay') {
      if (!start.value || !end.value) {
        transport.value = 'Waiting for replay range'
        replay.value = { done: true, message: saved.value.length ? 'Choose a recorded receipt-time range.' : 'No saved range selected.' }
        fetch('/api/indicator-presets?' + new URLSearchParams({symbol:symbol.value,timeframe:timeframe.value}))
          .then(response => { if (!response.ok) throw Error('Could not load presets.'); return response.json() })
          .then(items => { if (token === generation) { presets.value = items.map(item => ({ ...item, rows: [] })); drawStudies() } })
          .catch(error => { if (token === generation) indicatorError.value = error.message })
        return
      }
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
        if (message.type === 'snapshot') renderRows(message.candles, message.coverage)
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
        if (message.indicators || message.presets) {
          if (message.indicators) configured.value = message.indicators
          if (message.presets) presets.value = message.presets
          drawStudies()
        }
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

  function pin(time) {
    const index = candles.value.findIndex(c => c.time === time)
    if (index < 0) return
    selectedTime.value = time
    pinned.value = true
    renderMarkers()
    const scale = chart.timeScale()
    const range = scale.getVisibleLogicalRange()
    if (range && (index < range.from || index > range.to)) {
      const half = (range.to - range.from) / 2
      scale.setVisibleLogicalRange({ from: index - half, to: index + half })
    }
  }

  function followLatest() {
    pinned.value = false
    selectedTime.value = candles.value.at(-1)?.time
    renderMarkers()
    chart.timeScale().scrollToRealTime()
  }

  function inspect(event) {
    hover.value = event.point && event.seriesData.has(prices)
      ? { time: event.time, x: event.point.x, y: event.point.y } : null
  }

  function clickCandle(event) {
    if (event.seriesData.has(prices)) pin(event.time)
  }

  function changeMode(value) {
    mode.value = value
    connect()
  }

  function togglePlayback() {
    playing.value = !playing.value
    clearTimeout(playback)
    if (playing.value) next()
  }

  onMounted(() => {
    chart = createChart(container.value, {
      autoSize: true,
      layout: { attributionLogo: true, textColor: '#53655d', background: { type: 'solid', color: '#faf8f2' } },
      grid: { vertLines: { visible: false }, horzLines: { color: '#e3e2d8' } },
      rightPriceScale: { borderVisible: false },
      crosshair: { vertLine: { color: '#739db0' }, horzLine: { color: '#739db0' } },
      localization: { timeFormatter: formatUtc },
      timeScale: { timeVisible: true, secondsVisible: false, borderVisible: false },
    })
    prices = chart.addSeries(CandlestickSeries, {
      upColor: '#084c3d', downColor: '#682d40', borderVisible: false,
      wickUpColor: '#084c3d', wickDownColor: '#682d40',
    }, 0)
    volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, title: 'Volume (shares)' }, 1)
    shortLine = chart.addSeries(LineSeries, { color: '#427e9c', lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0)
    longLine = chart.addSeries(LineSeries, { color: '#956b36', lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0)
    markers = createSeriesMarkers(prices, [])
    chart.panes()[0].setStretchFactor(1)
    chart.panes()[1].setStretchFactor(0.25)
    chart.subscribeCrosshairMove(inspect)
    chart.subscribeClick(clickCandle)
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
    }).then((items) => {
      saved.value = items
      chooseSymbol(items.find(item => item.symbol === symbol.value)?.symbol ?? items[0]?.symbol ?? symbol.value)
      if (!disposed && mode.value === 'replay' && !socket && start.value && end.value) connect()
    })
      .catch((error) => { failure.value = error.message })
  })

  onBeforeUnmount(() => {
    disposed = true
    generation++
    clearTimeout(retry)
    clearTimeout(playback)
    clearInterval(timer)
    socket?.close()
    chart?.unsubscribeClick(clickCandle)
    chart?.unsubscribeCrosshairMove(inspect)
    markers?.detach()
    chart?.remove()
  })

  return reactive({
    mode, changeMode, symbol, timeframe, connect, source, feed, transport, failure, age,
    candles, coverage, selected, selectedTime, pinned, pin, followLatest, hover,
    selectedCoverage: computed(() => coverage.value[selectedTime.value]),
    latest: computed(() => candles.value.at(-1)),
    lastEnded: computed(() => candles.value.findLast(c => coverage.value[c.time]?.ended)),
    completed: computed(() => Object.values(coverage.value).filter(c => c.ended)),
    hoveredCandle: computed(() => hover.value && candles.value.find(c => c.time === hover.value.time)),
    visibleRange: () => chart?.timeScale().getVisibleRange(),
    saved, start, end, replaySymbol, chooseSymbol, replay, playing, waiting, next, togglePlayback, paperAccount,
    configured, presets, presetSaving, togglePreset, tab, selectTab, chartStudies, editedWindows, availableTypes, indicatorType, indicatorName, indicatorSettings,
    chooseType, selectedType, addIndicator, indicatorSaving, indicatorError, saveWindow,
    shortWindow, longWindow, appliedShort, appliedLong, applyWindows, settingsError, averages, signals, selectedAverage,
  })
}

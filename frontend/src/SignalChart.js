import { h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CandlestickSeries, createChart, createSeriesMarkers, LineSeries, LineStyle } from 'lightweight-charts'

import { easternDate, easternTick, formatEastern } from './chart-data.js'

export const studies = [
  ['sma20', '20-day SMA', '#19746b'], ['sma50', '50-day SMA', '#80465c'],
  ['sma200', '200-day SMA', '#8b641a'], ['ema200', '200-day EMA', '#4f60a1'],
]

const time = iso => Date.parse(iso) / 1000

export default {
  props: { bars: Array, facts: Array, cutoff: String, variant: String, trade: Object },
  emits: ['select'],
  setup(props, { emit, expose }) {
    const host = ref(null)
    const overlay = ref(null), first = ref(0)
    let chart, prices, markers, lines
    const visibleCount = () => Math.min(31, props.bars.length)
    const maxStart = () => props.bars.length - visibleCount()
    function pan(start) {
      const from = Math.max(0, Math.min(maxStart(), start))
      chart.timeScale().setVisibleLogicalRange({ from, to: from + visibleCount() - 1 })
    }
    function center() {
      pan(props.bars.findIndex(b => b.cutoff === props.cutoff) - Math.floor(visibleCount() / 2))
    }
    function updateOverlay() {
      if (!props.trade || !chart) return
      const scale = chart.timeScale(), range = scale.getVisibleLogicalRange()
      if (!range) return
      first.value = Math.max(0, Math.min(maxStart(), Math.round(range.from)))
      const { width, height } = chart.paneSize()
      const { entry, exit, order } = props.trade
      const events = [
        { kind: 'signal', label: 'Signal', stamp: props.cutoff },
        { kind: 'entry', label: 'Entry', stamp: entry?.fill_at },
        { kind: 'exit', label: 'Exit', stamp: exit?.fill_at },
      ]
      const coordinate = date => {
        const index = props.bars.findIndex(b => b.date >= date)
        return scale.logicalToCoordinate(index < 0 ? props.bars.length : index)
      }
      const pivot = order?.fill_at || props.cutoff
      const pivotDate = easternDate(time(pivot))
      const split = pivotDate < props.bars[0].date ? 0
        : pivotDate > props.bars.at(-1).date ? width : coordinate(pivotDate)
      overlay.value = { width, height, split: Math.max(0, Math.min(width, split)),
        events: events.filter(e => e.stamp).map(e => ({ ...e, date: easternDate(time(e.stamp)) }))
          .filter(e => props.bars.some(b => b.date === e.date))
          .map(e => ({ ...e, x: coordinate(e.date) })).filter(e => e.x >= 0 && e.x < width) }
    }
    function draw() {
      if (!chart) return
      prices.setData(props.bars.map(b => ({ time: time(b.cutoff), open: b.open, high: b.high, low: b.low, close: b.close })))
      for (const [key, line] of lines) {
        const active = ['sma20', 'sma50', props.variant].includes(key)
        line.setData(active ? props.facts.map(f => ({ time: time(f.cutoff), ...(f[key] == null ? {} : { value: f[key] }) })) : [])
      }
      markers.setMarkers(props.facts.filter(f => f.cutoff <= props.cutoff && f.reason !== 'warmup' &&
        (f.crossover || f.cutoff === props.cutoff)).map(f => ({
        time: time(f.cutoff), position: f.crossover === 'down' ? 'aboveBar' : 'belowBar',
        color: f.cutoff === props.cutoff ? '#084c3d' : '#756d61',
        shape: f.crossover === 'up' ? 'arrowUp' : f.crossover === 'down' ? 'arrowDown' : 'circle',
        text: f.cutoff === props.cutoff ? (f.reason === 'entry_filter_failed' ? 'Skipped entry' : f.verdict.toUpperCase()) : '',
      })))
      if (props.trade) { center(); updateOverlay() }
      else chart.timeScale().fitContent()
    }
    onMounted(() => {
      chart = createChart(host.value, { autoSize: true, handleScroll: props.trade ? {
        mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false } : false, handleScale: false,
        layout: { background: { type: 'solid', color: '#faf8f2' }, textColor: '#43534d', attributionLogo: false },
        localization: { timeFormatter: formatEastern },
        timeScale: { tickMarkFormatter: easternTick, ...(props.trade
          ? { fixLeftEdge: true, fixRightEdge: true, lockVisibleTimeRangeOnResize: true } : { rightOffset: 6 }) },
        grid: { vertLines: { visible: false }, horzLines: { color: '#e5e3d9' } } })
      prices = chart.addSeries(CandlestickSeries, { upColor: '#146455', downColor: '#80465c',
        borderVisible: false, wickUpColor: '#146455', wickDownColor: '#80465c',
        lastValueVisible: !props.trade, priceLineVisible: false })
      lines = studies.map(([key, , color]) => [key, chart.addSeries(LineSeries, { color,
        lineWidth: 2, lineStyle: key === 'ema200' ? LineStyle.Dashed : LineStyle.Solid,
        lastValueVisible: false, priceLineVisible: false })])
      markers = createSeriesMarkers(prices, [])
      if (props.trade) {
        chart.timeScale().subscribeVisibleLogicalRangeChange(updateOverlay)
        chart.timeScale().subscribeSizeChange(updateOverlay)
      }
      chart.subscribeClick(event => {
        const f = props.facts.find(row => time(row.cutoff) === event.time)
        if (f?.crossover && f.cutoff <= props.cutoff && f.reason !== 'warmup') emit('select', f.cutoff)
      })
      draw()
    })
    watch(() => [props.bars, props.facts, props.cutoff, props.variant], draw)
    expose({ screenshot: () => chart.takeScreenshot() })
    onBeforeUnmount(() => chart?.remove())
    return () => {
      const plot = h('div', { ref: host, class: 'backtest-chart', role: 'img',
        'aria-label': props.trade ? 'Trade review chart' : 'AAPL daily candles through ' + props.bars.at(-1)?.date })
      if (!props.trade) return plot
      const layer = overlay.value, start = Math.min(first.value, maxStart())
      const pivotName = props.trade.order?.fill_at ? (props.trade.order.side === 'buy' ? 'entry' : 'exit') : 'signal'
      return h('div', { class: 'trade-explorer' }, [
        h('div', { class: 'trade-plot' }, [plot, layer && h('div', { class: 'trade-overlay', 'aria-hidden': 'true',
          style: { width: layer.width + 'px', height: layer.height + 'px' } }, [
          h('div', { class: 'trade-before', style: { width: layer.split + 'px' } }),
          h('div', { class: 'trade-after', style: { left: layer.split + 'px' } }),
          ...layer.events.map(e => h('div', { class: 'trade-marker ' + e.kind, style: { left: e.x + 'px' } },
            [h('span', { style: e.x > layer.width - 46 ? { right: '2px' } : { left: '2px' } }, e.label)])),
        ])]),
        h('div', { class: 'trade-range-key' }, [h('span', 'Before ' + pivotName), h('span', 'From ' + pivotName),
          h('button', { class: 'text-button', onClick: center }, 'Center on signal')]),
        h('label', { class: 'trade-scroll' }, ['Scroll through trading sessions',
          h('input', { type: 'range', min: 0, max: maxStart(), step: 1, value: start, disabled: !maxStart(),
            onInput: e => pan(Number(e.target.value)) })]),
        h('p', { class: 'plot-period' }, 'Showing ' + props.bars[start].date + ' – ' +
          props.bars[Math.min(props.bars.length - 1, start + visibleCount() - 1)].date + ' · ' +
          props.bars.filter(b => b.cutoff < props.cutoff).length + ' sessions before and ' +
          props.bars.filter(b => b.cutoff > props.cutoff).length + ' after the signal available.'),
      ])
    }
  },
}

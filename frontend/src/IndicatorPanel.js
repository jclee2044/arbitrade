import { h, nextTick, ref, watch } from 'vue'
import { periods, movingAverageColors, timeframes } from './chart-studies.js'
import { average, formatEastern } from './chart-data.js'
import FeedDetails from './FeedDetails.js'

function strategy(m) {
  return [
    h('h3', 'SMA crossover strategy'),
    h('form', { class: 'sma-controls', onSubmit: e => { e.preventDefault(); m.applyWindows() } }, [
      ...['short', 'long'].map(key => h('label', { for: 'sma-' + key }, [
        (key === 'short' ? 'Short' : 'Long') + ' window',
        h('input', { id: 'sma-' + key, type: 'number', min: 1, step: 1, required: true,
          value: m[key + 'Window'], onInput: e => { m[key + 'Window'] = e.target.value } }),
      ])),
      h('button', { type: 'submit' }, 'Apply SMA windows'),
    ]),
    m.settingsError ? h('p', { role: 'alert' }, m.settingsError) : null,
  ]
}

function namedStudies(m) {
  return [
    h('h3', 'Add an indicator'),
    h('form', { class: 'indicator-form', novalidate: true, onSubmit: e => { e.preventDefault(); m.addIndicator() } }, [
      h('label', { for: 'indicator-type' }, ['Type', h('select', { id: 'indicator-type', value: m.indicatorType,
        onChange: e => m.chooseType(e.target.value) }, m.availableTypes.map(item => h('option', { value: item.type }, item.label)))]),
      h('label', { for: 'indicator-name' }, ['Name', h('input', { id: 'indicator-name', value: m.indicatorName, maxlength: 80,
        onInput: e => { m.indicatorName = e.target.value } })]),
      ...Object.entries(m.selectedType?.settings || {}).map(([key, spec]) => h('label', { for: 'indicator-' + key }, [
        spec.label, h('input', { id: 'indicator-' + key, type: 'number', min: spec.minimum, step: 1,
          value: m.indicatorSettings[key], onInput: e => { m.indicatorSettings[key] = e.target.value } }),
      ])),
      m.selectedType ? h('p', { class: 'fine-print' }, m.selectedType.description + ' Units: ' + m.selectedType.units + '.') : null,
      h('button', { class: 'primary', type: 'submit', disabled: m.indicatorSaving || !m.selectedType }, m.indicatorSaving ? 'Saving indicator…' : 'Add indicator'),
    ]),
    h('section', { class: 'configured-indicators' }, [
      h('h3', 'Saved indicators'),
      m.configured.length ? h('ul', m.configured.map(item => {
        const value = item.rows.find(row => Date.parse(row.timestamp) / 1000 === m.selectedTime)?.value
        return h('li', { key: item.id, 'data-indicator-name': item.name }, [
          h('strong', item.name), h('p', { class: 'fine-print' }, [item.type + ' · ', h('span', { class: 'indicator-value' }, average(value)), ' ' + item.units]),
          h('label', { for: 'saved-window-' + item.id }, ['Window', h('input', {
            id: 'saved-window-' + item.id, type: 'number', min: 1, step: 1, value: m.editedWindows[item.id] ?? item.settings.window,
            onInput: e => { m.editedWindows[item.id] = e.target.value },
          })]), h('button', { onClick: () => m.saveWindow(item) }, 'Save window'),
        ])
      })) : h('p', { class: 'fine-print' }, 'No indicators saved for this symbol and timeframe.'),
    ]),
  ]
}

const presetFrames = { '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1hr', '1d': '1D', '1w': '1W' }

function presets(m, kind) {
  const title = kind.toUpperCase()
  return h('section', { class: 'study-group' }, [
    h('h3', title),
    ...Object.entries(presetFrames).map(([frame, label]) =>
      h('div', { class: 'periods', role: 'group', 'aria-label': title + ' ' + label }, [
        h('span', label),
        ...periods.map(period => h('button', {
          type: 'button', 'aria-label': title + ' ' + period + ' · ' + label,
          'aria-pressed': m.presets.some(item => item.timeframe === frame && item.type === kind && item.settings.window === period),
          disabled: m.presetSaving, style: { '--line': movingAverageColors[kind] },
          onClick: () => m.togglePreset(kind, period, frame),
        }, String(period))),
      ])),
  ])
}

function crossoverHistory(m) {
  return [
    h('section', { class: 'sma-crossovers', 'aria-label': 'Confirmed SMA crossovers' }, [
      h('h3', 'Confirmed crossovers'),
      h('p', { class: 'pair-caption' }, 'SMA ' + m.appliedShort + ' and SMA ' + m.appliedLong + ' · ' + timeframes[m.timeframe]),
      m.signals.length ? h('ol', m.signals.map(row => {
        const time = Date.parse(row.timestamp) / 1000
        const upward = row.signal === 'up'
        return h('li', { key: row.timestamp }, h('button', { class: 'signal-link',
          'aria-pressed': m.pinned && m.selectedTime === time, onClick: () => m.pin(time) }, [
          h('span', { class: 'signal-heading' }, [h('strong', [h('i', { 'aria-hidden': true, class: upward ? 'up' : 'down' }, upward ? '↗' : '↘'), upward ? 'Upward' : 'Downward']),
            h('time', { datetime: row.timestamp, title: formatEastern(time) }, formatEastern(time))]),
          h('span', { class: 'signal-levels' }, ['Short ' + average(row.short), 'Long ' + average(row.long)].map(text => h('span', text))),
        ]))
      })) : h('p', { class: 'empty-signals' }, 'No confirmed crossovers in this history.'),
    ]),
    h('details', { class: 'rail-details' }, [h('summary', 'Crossover windows'), ...strategy(m)]),
    h('details', { class: 'rail-details' }, [h('summary', 'Selected candle values'),
      h('dl', { class: 'sma-values facts' }, [
        ['Short SMA', average(m.selectedAverage?.short)], ['Long SMA', average(m.selectedAverage?.long)],
        ['Confirmed crossover', m.selectedAverage?.signal || 'None'],
      ].flatMap(([label, value]) => [h('dt', label), h('dd', value)])),
    ]),
  ]
}

const drawingIcons = {
  line: 'M6 18L18 6 M2 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0 M18 4a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
  freehand: 'M2 17C5 17 7 4 11 4C16 4 5 20 11 20C15 20 16 10 19 11C21 12 19 16 22 15',
  eraser: 'M3 14l11-11a1 1 0 0 1 2 0l5 5a1 1 0 0 1 0 2L11 20H8l-5-5z M8 9l8 8 M11 20h10',
}

function drawingPanel(m) {
  function tool(name, value) {
    return h('button', {
      'aria-pressed': m.drawingTool === value, disabled: !m.latest,
      onClick: () => { m.drawingTool = m.drawingTool === value ? null : value },
    }, drawingIcons[value] ? [
      h('svg', { viewBox: '0 0 24 24', width: 21, height: 21, fill: 'none', stroke: 'currentColor',
        'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' },
      [h('path', { d: drawingIcons[value] })]), name,
    ] : name)
  }
  return [
    h('div', { class: 'drawing-buttons drawing-tool-list' }, [tool('Trend Line', 'line'), tool('Freehand', 'freehand'), tool('Eraser', 'eraser')]),
    h('h3', { class: 'risk-heading' }, 'Risk/Reward'),
    h('div', { class: 'drawing-buttons risk-presets' }, [2, 3, 4].map(r => tool('1:' + r, r))),
    !m.latest ? h('p', { class: 'pair-caption' }, 'Waiting for candles.') : null,
  ]
}

const labels = { indicators: 'Indicators', signals: 'Signals', drawing: 'Drawing Tools', ai: 'AI' }

function railIcon(tab) {
  if (tab === 'ai') return h('img', { src: '/brand/arbitrade-diamond.svg', alt: '', width: 25, height: 25 })
  const path = tab === 'drawing' ? 'M-9 9l1-6L5-10l5 5L-3 8z M2-7l5 5' : tab === 'indicators' ? 'M-10 -4H10 M-10 4H10 M-5 -8V0 M5 0V8' : 'M-10 7V-7 M-10 7H11 M-7 2L-2 -3L2 0L9 -6'
  return h('svg', { viewBox: '-13 -13 26 26', width: 25, height: 25, fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' }, [h('path', { d: path })])
}

export default {
  props: { market: Object, collapsed: Boolean, menu: String },
  emits: ['collapse', 'select'],
  setup(props, { emit, slots }) {
    const rail = ref(null)
    watch(() => props.menu, () => { rail.value.scrollTop = 0 })
    const tabs = Object.keys(labels)
    function select(tab) {
      if (tab === 'indicators' || tab === 'signals') props.market.selectTab(tab)
      emit('select', tab)
      emit('collapse', false)
    }
    function tabKey(event) {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return
      event.preventDefault()
      const direction = event.key === 'ArrowRight' ? 1 : -1
      const tab = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1) : tabs[(tabs.indexOf(props.menu) + direction + tabs.length) % tabs.length]
      select(tab)
      nextTick(() => document.getElementById('tab-' + tab).focus())
    }
    return () => {
      const m = props.market
      return h('aside', { ref: rail, class: 'study-rail', 'aria-label': 'Chart tools' }, [
        h('div', { class: 'rail-heading' }, [
          h('div', { class: 'rail-tabs', role: 'tablist', 'aria-label': 'Chart tools', onKeydown: tabKey }, tabs.map(tab =>
            h('button', { id: 'tab-' + tab, role: 'tab', 'aria-selected': props.menu === tab, tabindex: props.menu === tab ? 0 : -1,
              title: labels[tab], 'aria-label': labels[tab], 'aria-controls': 'rail-content', onClick: () => select(tab) }, railIcon(tab)))),
          h('button', { class: 'collapse-rail', title: props.collapsed ? 'Expand sidebar' : 'Collapse sidebar',
            'aria-label': props.collapsed ? 'Expand sidebar' : 'Collapse sidebar', 'aria-controls': 'rail-content',
            'aria-expanded': !props.collapsed, onClick: () => emit('collapse', !props.collapsed) }, props.collapsed ? '›' : '‹'),
        ]),
        h('div', { class: 'rail-reveal', inert: props.collapsed }, [
          h('div', { id: 'rail-content', role: 'tabpanel', 'aria-labelledby': 'tab-' + props.menu },
            h('div', { class: 'rail-track', style: { '--slide': (-100 * tabs.indexOf(props.menu)) + '%' } },
              tabs.map(tab => h('div', { key: tab, class: 'rail-pane', inert: tab !== props.menu }, tab === 'ai' ? slots.default?.() : [
                h('h2', labels[tab]),
                ...(tab === 'drawing' ? drawingPanel(m) : tab === 'signals' ? crossoverHistory(m) : [
                  h('details', { class: 'moving-averages rail-details', open: true }, [
                    h('summary', 'Moving Averages'), presets(m, 'sma'), presets(m, 'ema'),
                  ]),
                  h('details', { class: 'rail-details custom-studies' }, [h('summary', 'Rolling price range & custom indicators'), ...namedStudies(m)]),
                  m.indicatorError ? h('p', { role: 'alert' }, m.indicatorError) : null,
                  h(FeedDetails, { market: m }),
                ]),
              ])))),
        ]),
      ])
    }
  },
}

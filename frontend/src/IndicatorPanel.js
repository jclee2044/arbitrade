import { h, nextTick } from 'vue'
import { periods, periodColor, timeframes } from './chart-studies.js'
import { average, formatUtc } from './chart-data.js'

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

function presets(m, kind, description) {
  return h('section', { class: 'study-group' }, [
    h('h3', kind.toUpperCase()), h('p', description),
    h('div', { class: 'periods', role: 'group', 'aria-label': description }, periods.map(period =>
      h('button', { type: 'button', 'aria-label': kind.toUpperCase() + ' ' + period,
        'aria-pressed': m.presets.some(item => item.type === kind && item.settings.window === period),
        disabled: m.presetSaving, style: { '--line': periodColor(period) },
        onClick: () => m.togglePreset(kind, period) }, String(period)))),
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
            h('time', { datetime: row.timestamp, title: formatUtc(time) }, formatUtc(time).replace(' UTC', ''))]),
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

export default {
  props: { market: Object, collapsed: Boolean },
  emits: ['collapse'],
  setup(props, { emit }) {
    const tabs = ['indicators', 'signals']
    function select(tab) {
      props.market.selectTab(tab)
      emit('collapse', false)
    }
    function tabKey(event) {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return
      event.preventDefault()
      const tab = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs.find(t => t !== props.market.tab)
      select(tab)
      nextTick(() => document.getElementById('tab-' + tab).focus())
    }
    return () => {
      const m = props.market
      return h('aside', { class: 'study-rail', 'aria-label': 'Chart tools' }, [
        h('div', { class: 'rail-heading' }, [
          h('div', { class: 'rail-tabs', role: 'tablist', 'aria-label': 'Chart tools', onKeydown: tabKey }, tabs.map(tab =>
            h('button', { id: 'tab-' + tab, role: 'tab', 'aria-selected': m.tab === tab, tabindex: m.tab === tab ? 0 : -1,
              'aria-controls': 'rail-content', onClick: () => select(tab) }, tab === 'signals' ? 'Signals' : 'Indicators'))),
          h('button', { class: 'collapse-rail', title: props.collapsed ? 'Expand sidebar' : 'Collapse sidebar',
            'aria-label': props.collapsed ? 'Expand sidebar' : 'Collapse sidebar', 'aria-controls': 'rail-content',
            'aria-expanded': !props.collapsed, onClick: () => emit('collapse', !props.collapsed) }, props.collapsed ? '›' : '‹'),
        ]),
        h('div', { key: m.tab, id: 'rail-content', role: 'tabpanel', hidden: props.collapsed, 'aria-labelledby': 'tab-' + m.tab }, m.tab === 'signals'
          ? crossoverHistory(m)
          : [presets(m, 'sma', 'Simple moving average'), presets(m, 'ema', 'Exponential moving average'),
            h('details', { class: 'rail-details custom-studies' }, [h('summary', 'Rolling price range & custom indicators'), ...namedStudies(m)]),
            m.indicatorError ? h('p', { role: 'alert' }, m.indicatorError) : null]),
      ])
    }
  },
}

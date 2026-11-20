import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef } from 'vue'
import { boundChartPng } from './chart-capture.js'
import ClassroomDecision from './ClassroomDecision.js'
import DeskAgentChat from './DeskAgentChat.js'
import { formatEastern, easternDate } from './chart-data.js'
import { requestDeskAgent } from './desk-agent.js'
import SignalChart, { studies } from './SignalChart.js'
import { entryFilters, explainSignal, forwardReview, pct, tradeAtSignal, usd } from './signal-review.js'

const et = iso => formatEastern(Date.parse(iso) / 1000)
const decisionTitles = { buy: 'Why the strategy bought', wait: 'Why the strategy waited', close: 'Why the strategy exited', hold: 'Why the strategy held' }

function table(headers, rows) {
  return h('div', { class: 'backtest-table' }, [h('table', [
    h('thead', [h('tr', headers.map(label => h('th', { scope: 'col' }, label)))]),
    h('tbody', rows.map(cells => h('tr', cells.map(cell => h('td', cell))))),
  ])])
}

export default {
  setup() {
    const decisionChart = ref(null), decisionPanel = ref(null)
    const run = shallowRef(null), index = ref(0), revision = ref(0)
    const loading = ref(true), error = ref(''), decisionBusy = ref(false), chatBusy = ref(false)
    const showOutcomes = ref(false), compare = ref(false), chatOpen = ref(false)
    const runs = new Map()
    let generation = 0
    const facts = computed(() => run.value?.facts[index.value])
    const strategy = computed(() => ({ variant: facts.value?.variant, dataset_id: run.value?.dataset_id }))
    const signals = computed(() => run.value?.facts.filter(f => f.crossover && f.reason !== 'warmup') || [])
    const windowStart = computed(() => Math.max(0, index.value - 89))
    // This chart instance never receives post-cutoff bars, even during outcome review.
    const decisionBars = computed(() => run.value?.bars.slice(windowStart.value, index.value + 1) || [])
    const decisionFacts = computed(() => run.value?.facts.slice(windowStart.value, index.value + 1) || [])
    const outcome = computed(() => run.value && forwardReview(run.value, index.value, runs.get('baseline').orders))
    const trade = computed(() => run.value && tradeAtSignal(run.value, index.value))
    const reviewBars = computed(() => run.value?.bars.slice(Math.max(0, index.value - 50), index.value + 51))
    const reviewFacts = computed(() => run.value?.facts.slice(Math.max(0, index.value - 50), index.value + 51))

    function select(cutoff) {
      const selected = run.value.facts.findIndex(f => f.cutoff === cutoff)
      if (selected < 0) return
      index.value = selected
      showOutcomes.value = false
      revision.value++
    }

    async function load(variant) {
      const request = ++generation, previous = facts.value?.cutoff
      revision.value++
      loading.value = true
      error.value = ''
      try {
        if (!runs.has(variant)) {
          const response = await fetch('/api/backtests/daily?variant=' + variant)
          if (!response.ok) throw Error('Daily history could not be loaded.')
          runs.set(variant, await response.json())
        }
        if (request !== generation) return
        run.value = runs.get(variant)
        select(previous || signals.value.at(-1)?.cutoff || run.value.facts.at(-1).cutoff)
      } catch (failure) {
        if (request === generation) error.value = failure.message
      } finally {
        if (request === generation) loading.value = false
      }
    }

    async function captureVisibleChart() {
      const before = revision.value
      await nextTick()
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      if (before !== revision.value || !decisionChart.value || loading.value) throw Error('Historical selection changed.')
      const f = facts.value
      return { ticker: f.ticker, interval: '1d', candle_timestamp: f.cutoff,
        captured_at: new Date().toISOString(), visible_candles: decisionBars.value.length, is_stale: true,
        volume_status: 'unavailable', image: boundChartPng(decisionChart.value.screenshot(), {
          kind: 'daily_strategy', ticker: f.ticker, variant: f.variant, dataset_id: f.dataset_id,
          cutoff: f.cutoff, rule_version: f.rule_version }) }
    }
    const market = reactive({ chartRevision: revision, waiting: loading, candles: decisionBars,
      captureVisibleChart, askDeskAgent: (question, { capture, conversationId, strategy }) =>
        requestDeskAgent(question, capture, conversationId, 'backtest', strategy) })
    onMounted(() => load('baseline'))
    onBeforeUnmount(() => { generation++; revision.value++ })

    function outcomes(f) {
      const { rows, buy, exit, skipped } = outcome.value
      return h('section', { id: 'signal-outcomes', class: 'signal-outcomes', 'aria-label': 'Historical outcomes' }, [
        h('h3', 'What happened next?'),
        h('p', 'Trading days after the selected close. Account change includes subsequent simulated orders.'),
        table(['Trading days later', 'Session', 'Closing price', 'From signal close', 'Account change',
          ...(buy ? [skipped ? 'Baseline buy vs. cash' : 'P&L on this buy'] : [])], rows.map(row => [
          String(row.days), row.bar?.date || 'Beyond saved history', row.bar ? usd(row.bar.close) : '—',
          row.bar ? pct(row.movePct) : '—', row.bar ? usd(row.accountChange) : '—',
          ...(buy ? [row.bar ? usd(row.tradePnl) : '—'] : []),
        ])),
        buy ? h('p', { class: 'fine-print' }, (skipped ? 'The baseline bought' : 'The strategy bought') + ' one share for ' + usd(buy.fill_price) +
          ' on ' + easternDate(Date.parse(buy.fill_at) / 1000) + '. ' + (exit && rows.some(row => row.bar && exit.fill_at <= row.bar.cutoff)
            ? 'After its ' + easternDate(Date.parse(exit.fill_at) / 1000) + ' sale at ' + usd(exit.fill_price) + ', proceeds stay in cash.'
            : 'Open shares are valued at each close.')) : null,
        h('p', { class: 'fine-print' }, 'AI assessments use only the chart and facts through ' + et(f.cutoff) + '.'),
      ])
    }

    return () => {
      const r = run.value, f = facts.value
      if (!r) return h('section', { class: 'backtest', 'aria-label': 'Daily strategy backtest' }, [
        h('h2', 'Moving-average crossover'), error.value ? h('p', { role: 'alert' }, [error.value, ' ',
          h('button', { onClick: () => load('baseline') }, 'Retry')]) : h('p', { role: 'status' }, 'Loading daily history…')])
      const summary = r.comparisons.find(s => s.variant === f.variant)
      const previous = signals.value.findLast(row => row.cutoff < f.cutoff)
      const next = signals.value.find(row => row.cutoff > f.cutoff)
      const changed = signals.value.find(row => row.reason === 'entry_filter_failed')
      const reading = explainSignal(f)
      const chartProps = { cutoff: f.cutoff, variant: f.variant, onSelect: select }
      const { entry, exit, order } = trade.value
      const fillText = fill => et(fill.fill_at) + ' · ' + usd(fill.fill_price)
      return h('section', { class: 'backtest', 'aria-label': 'Daily strategy backtest' }, [
        h('header', [h('p', { class: 'scope' }, r.ticker + ' / Daily backtest'), h('h2', 'Moving-average crossover'),
          h('p', 'Buy one share when the 20-day average crosses above the 50-day average. Exit when it crosses back below.')]),
        h('div', { class: 'backtest-controls' }, [
          h('label', ['What else must be true before buying? ', h('select', { disabled: loading.value, value: f.variant,
            onChange: async e => {
              const select = e.target
              await load(select.value)
              select.value = facts.value.variant
            } }, Object.entries(entryFilters).map(([key, name]) => h('option', { value: key }, name)))]),
          h('button', { class: 'text-button', 'aria-expanded': compare.value, onClick: () => { compare.value = !compare.value } }, 'Compare entry filters')]),
        error.value ? h('p', { role: 'alert' }, error.value) : null,
        h('div', { class: 'backtest-result' }, [h('strong', 'Historical result'), h('span', r.start + ' – ' + r.end),
          h('b', '$1,000 → ' + usd(summary.equity)), h('span', pct(summary.return_pct) + ' return'),
          h('span', summary.skipped + ' skipped entries')]),
        compare.value ? h('div', [table(['Entry condition', 'Ending equity', 'Return', 'Max drawdown', 'Fills', 'Skipped entries'],
          r.comparisons.map(s => [entryFilters[s.variant], usd(s.equity), pct(s.return_pct), pct(s.max_drawdown_pct), s.fills, s.skipped])),
          changed ? h('button', { class: 'text-button', onClick: () => select(changed.cutoff) }, 'Inspect first skipped entry') : null]) : null,
        h('div', { class: 'signal-heading' }, [h('h3', 'Signal review'),
          h('label', [h('span', { class: 'sr-only' }, 'Review session'), h('select', { value: f.cutoff,
            onChange: e => select(e.target.value) }, r.facts.filter(row => row.reason !== 'warmup')
              .map(row => h('option', { value: row.cutoff }, et(row.cutoff))))])]),
        h('div', { key: 'review', class: 'backtest-grid' }, [
          h('section', [
            h('div', { class: 'backtest-legend' }, studies.filter(([k]) => ['sma20','sma50',f.variant].includes(k)).map(([k,label,color]) =>
              h('span', { style: { borderColor: color } }, label))),
            h('div', { class: 'signal-plots' }, [
              h(SignalChart, { key: 'decision', ref: decisionChart, ...chartProps, bars: decisionBars.value, facts: decisionFacts.value,
                class: 'capture-only-chart', 'aria-hidden': 'true' }),
              h(SignalChart, { key: 'review', ...chartProps, trade: trade.value, bars: reviewBars.value, facts: reviewFacts.value })]),
            h('section', { class: 'trade-timeline', 'aria-label': 'Simulated trade timeline' }, [
              h('h4', 'Simulated trade'), h('dl', [
                h('dt', 'Signal close'), h('dd', et(f.cutoff) + ' · ' + f.verdict.toUpperCase()),
                ...(entry ? [h('dt', 'Entry fill'), h('dd', fillText(entry)), h('dt', 'Exit fill'),
                  h('dd', exit ? fillText(exit) + ' · ' + usd(exit.fill_price - entry.fill_price) + ' on one share'
                    : 'Still open at the end of saved history (' + r.end + ').')] : []),
              ]),
              !entry ? h('p', order ? 'Entry order ' + order.status + (order.reason ? ' · ' + order.reason.replaceAll('_', ' ') : '') + '.'
                : 'No trade opened on this signal. There is no exit fill.') : null,
              exit && exit.signal_at !== f.cutoff ? h('button', { class: 'text-button',
                onClick: () => select(exit.signal_at) }, 'Review exit signal') : null,
            ]),
            h('div', { class: 'signal-nav' }, [
              h('button', { disabled: !previous, onClick: () => select(previous.cutoff) }, '← Previous signal'),
              h('button', { disabled: !next, onClick: () => select(next.cutoff) }, 'Next signal →')]),
            h('button', { class: 'outcome-toggle', 'aria-expanded': showOutcomes.value,
              onClick: () => { showOutcomes.value = !showOutcomes.value } }, showOutcomes.value ? 'Hide outcome table' : 'What happened next?'),
            showOutcomes.value ? outcomes(f) : null,
          ]),
          h('aside', { class: 'backtest-assistant' }, [
            h('div', { class: 'backtest-reading' }, [
              h('h3', decisionTitles[f.verdict]),
              h('dl', [h('dt', 'Signal'), h('dd', reading.trigger), h('dt', 'Decision reason'), h('dd', reading.reason)]),
              h('strong', { id: 'backtest-verdict' }, 'Rule decision · ' + f.verdict.toUpperCase()),
              h('p', f.verdict === 'buy' || f.verdict === 'close' ? 'Simulated order for the next session open.' : 'No simulated order.'),
              h('details', [h('summary', 'Session facts'), h('pre', JSON.stringify(f, null, 2))])]),
            h('h3', 'AI review'),
            h('p', { class: 'fine-print' }, 'Uses only sessions through ' + et(f.cutoff) + '.'),
            h('button', { class: 'primary', disabled: loading.value || chatBusy.value || decisionBusy.value,
              onClick: () => decisionPanel.value.analyze() }, decisionBusy.value ? 'Assessing…' : 'Get AI assessment'),
            h('button', { class: 'text-button', 'aria-expanded': chatOpen.value, onClick: () => { chatOpen.value = !chatOpen.value } }, 'Ask about this signal'),
            h(ClassroomDecision, { ref: decisionPanel, idPrefix: 'backtest-decision', dataMode: 'backtest', strategy: strategy.value,
              capture: captureVisibleChart, chartSession: 0, chartRevision: revision.value, onBusy: v => { decisionBusy.value = v } }),
            h('div', { hidden: !chatOpen.value }, [h(DeskAgentChat, { market, idPrefix: 'backtest-chat', strategy: strategy.value,
              sessionLabel: f.ticker + ' · ' + et(f.cutoff) + ' · ' + (f.variant === 'baseline' ? '20/50 baseline' : f.variant.toUpperCase()),
              decisionBusy: decisionBusy.value || loading.value, onBusy: v => { chatBusy.value = v }, onNewChat: () => decisionPanel.value?.clearChatResult(),
              presentAssessment: (d, cap, rev) => rev === revision.value && decisionPanel.value?.present(d, cap, rev) })])]),
        ]),
        h('details', { class: 'backtest-ledger' }, [h('summary', 'Orders and account details'),
          h('p', et(f.cutoff) + ' · Cash ' + usd(f.cash) + ' · Shares ' + f.shares + ' · Equity ' + usd(f.equity)),
          h('p', 'Realized ' + usd(f.realized) + ' · Unrealized ' + usd(f.unrealized)),
          table(['Decision session (ET)', 'Cross', 'Rule action', 'Order', 'Next-open fill (ET)', 'Fill price'], signals.value.toReversed().map(row => {
            const o = r.orders.find(order => order.signal_at === row.cutoff)
            return [h('button', { class: 'text-button', onClick: () => select(row.cutoff) }, et(row.cutoff)), row.crossover,
              row.reason === 'entry_filter_failed' ? 'Skipped entry' : row.verdict, o ? '#' + o.order_id + ' · ' + o.side + ' 1 · ' + o.status : '—',
              o?.fill_at ? et(o.fill_at) : '—', o?.fill_price ? usd(o.fill_price) : '—']
          }))]),
        h('details', [h('summary', 'Execution assumptions and data coverage'), h('p', r.assumptions),
          h('p', r.source + ' · One ticker, one frozen historical sample. Provider data can include later revisions.'),
          h('p', 'Rule version · ' + r.rule_version), h('p', 'Dataset SHA-256 · ' + r.dataset_id)]),
      ])
    }
  },
}

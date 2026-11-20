import { createApp, h, ref, computed, nextTick } from 'vue'
import { useMarketChart } from './useMarketChart.js'
import DailyBacktest from './DailyBacktest.js'
import { strategyLabels } from './desk-agent.js'
import DeskNavigation from './DeskNavigation.js'
import CandleChart from './CandleChart.js'
import ChartSummary from './ChartSummary.js'
import IndicatorPanel from './IndicatorPanel.js'
import PaperTrading from './PaperTrading.js'
import AutomationPanel from './AutomationPanel.js'
import DecisionPanel from './DecisionPanel.js'
import ClassroomDecision from './ClassroomDecision.js'
import DeskAgentChat from './DeskAgentChat.js'
import VoicePanel from './VoicePanel.js'
import './style.css'

// Park inactive panels without unmounting them. Frozen chart export needs a measured canvas.
function view(id, active, children) {
  return h('div', { id, class: ['tool-view', !active && 'parked'], inert: !active,
    'aria-hidden': active ? undefined : 'true' }, children)
}

createApp({
  setup() {
    const chartHost = ref(null)
    const setChartHost = el => { chartHost.value = el }
    const m = useMarketChart(chartHost)
    const tool = ref('chart')
    const menu = ref('indicators')
    const variant = ref('')
    const isApple = computed(() => m.symbol === 'AAPL')
    const strategy = computed(() => isApple.value && variant.value ? { variant: variant.value } : undefined)
    const tickerDraft = ref(m.symbol)
    const tickerError = ref('')
    function submitTicker(event) {
      event.preventDefault()
      const symbol = tickerDraft.value.trim().toUpperCase()
      if (!/^[A-Z][A-Z0-9.-]{0,15}$/.test(symbol)) {
        tickerError.value = 'Enter a ticker such as MSFT or BRK-B.'
        return
      }
      tickerDraft.value = symbol
      tickerError.value = ''
      if (symbol !== m.symbol) proposalOpen.value = false
      m.changeLiveSymbol(symbol)
    }
    const collapsed = ref(window.matchMedia('(max-width: 700px)').matches)
    const paperTab = ref('Orders')
    const proposalOpen = ref(false)
    const decisionPanel = ref(null)
    const classroomPanel = ref(null)
    const analysis = ref(null)
    const busy = ref(false)
    const chatBusy = ref(false)
    const notice = ref(null)
    const automation = ref(null)
    const automationOn = ref(false)
    const voice = ref(null)
    const voiceOn = ref(false)
    const selectionKey = (account, symbol, interval, time, short, long) =>
      JSON.stringify([account, symbol, interval, Date.parse(time), short, long])
    const currentKey = computed(() => selectionKey(m.paperAccount, m.symbol, m.timeframe, m.selected?.timestamp, m.appliedShort, m.appliedLong))

    const selectedAnalysis = computed(() => analysis.value?.key === currentKey.value ? analysis.value : null)
    function receiveAnalysis(outcome) {
      const { selection, decision } = outcome
      analysis.value = { ...outcome, key: selectionKey(selection.account_id, selection.symbol, selection.interval,
        selection.candle_timestamp, selection.short_window, selection.long_window) }
      notice.value = null
      if (analysis.value.key === currentKey.value && !voiceOn.value) voice.value?.selectDecision(decision.id, false)
    }
    async function analyze() {
      await classroomPanel.value.analyze()
    }
    async function toggleProposal() {
      proposalOpen.value = !proposalOpen.value
      if (!proposalOpen.value) return
      await nextTick()
      await decisionPanel.value.reviewSelection(selectedAnalysis.value)
    }
    async function navigate(destination) {
      tool.value = destination
      await nextTick()
      document.getElementById(destination === 'paper' ? 'paper-workspace' : 'desk')?.focus({ preventScroll: true })
      window.scrollTo({ top: 0 })
    }
    async function openVoice(id) {
      if (window.matchMedia('(max-width: 910px)').matches) tool.value = 'chart'
      menu.value = 'ai'
      collapsed.value = false
      proposalOpen.value = false
      if (id) await voice.value.selectDecision(id)
      else voice.value.openChooser()
      await nextTick()
      document.getElementById('voice-title')?.scrollIntoView({ block: 'nearest' })
    }
    function stopAutomation() {
      paperTab.value = 'Automation'
      navigate('paper')
      automation.value?.stop()
    }

    return () => [
      h(DeskNavigation, { tool: tool.value, mode: m.mode, automationOn: automationOn.value, voiceOn: voiceOn.value,
        onNavigate: navigate, onMode: value => { m.changeMode(value); if (tool.value === 'backtest') navigate('chart') }, onStop: stopAutomation, onVoice: () => openVoice() }),
      h('main', { id: 'desk', tabindex: -1 }, [
        tool.value === 'backtest' ? h(DailyBacktest) : null,
        h('div', { style: tool.value === 'backtest' ? { display: 'none' } : {}, class: ['workspace', collapsed.value && 'rail-closed', tool.value === 'chart' && 'trade-closed'] }, [
          h(IndicatorPanel, { market: m, collapsed: collapsed.value, menu: menu.value,
            onSelect: value => { menu.value = value }, onCollapse: value => { collapsed.value = value } }, {
            default: () => h('div', { class: 'rail-ai', 'aria-label': 'Analysis and voice' }, [
              isApple.value ? h('label', ['Assessment mode', h('select', { value: variant.value, onChange: event => {
                variant.value = event.target.value
                m.changeChartSnapshot()
              } }, [h('option', { value: '' }, 'Chart image'), ...Object.entries(strategyLabels).map(([key, label]) =>
                h('option', { value: key }, 'Daily · ' + label))])]) : null,
              h(DeskAgentChat, { market: m, strategy: strategy.value, decisionBusy: busy.value, onBusy: value => { chatBusy.value = value },
                onNewChat: () => classroomPanel.value?.clearChatResult(),
                presentAssessment: (decision, capture, revision) => revision === m.chartRevision &&
                  classroomPanel.value?.present(decision, capture, revision) }),
              h(ChartSummary, { market: m, decision: selectedAnalysis.value?.decision,
                busy: busy.value || chatBusy.value, message: notice.value?.key === currentKey.value ? notice.value.message : '',
                proposalOpen: proposalOpen.value, onAnalyze: analyze, onReview: toggleProposal }, {
                default: () => [h(ClassroomDecision, { ref: classroomPanel, capture: m.captureVisibleChart, dataMode: m.mode, strategy: strategy.value,
                  chartSession: m.chartSession, chartRevision: m.chartRevision,
                  onBusy: value => { busy.value = value } }), view('proposal-view', isApple.value && proposalOpen.value, [h(DecisionPanel, {
                  ref: decisionPanel, chartRange: m.visibleRange, accountId: m.paperAccount, symbol: m.symbol, interval: m.timeframe,
                  candleTimestamp: m.selected?.timestamp, completed: Boolean(m.selectedCoverage?.ended),
                  shortWindow: m.appliedShort, longWindow: m.appliedLong, onOutcome: receiveAnalysis, onBusy: value => { busy.value = value },
                  onDiscuss: openVoice,
                })])],
              }),
              h(VoicePanel, { ref: voice, onSession: value => { voiceOn.value = value } }),
            ]),
          }),
          h('div', { class: 'market-desk' }, [
            h('div', { class: 'instrument' }, [
              h('h2', isApple.value ? 'Apple Inc.' : m.symbol),
              m.mode === 'live' ? h('form', { class: 'ticker-form', onSubmit: submitTicker }, [
                h('input', { type: 'text', size: 8, value: tickerDraft.value, 'aria-label': 'Ticker',
                  'aria-invalid': tickerError.value ? 'true' : undefined,
                  'aria-describedby': tickerError.value ? 'ticker-error' : undefined,
                  autocomplete: 'off', autocapitalize: 'characters', spellcheck: false,
                  onInput: event => { tickerDraft.value = event.target.value; tickerError.value = '' } }),
                h('button', { type: 'submit' }, 'Go'),
              ]) : h('span', { class: 'ticker' }, m.symbol),
              tickerError.value && m.mode === 'live' ? h('p', { id: 'ticker-error', role: 'alert' }, tickerError.value) : null,
            ]),
            h(CandleChart, { market: m, chartHost: setChartHost, drawingOpen: menu.value === 'drawing' && !collapsed.value }),
          ]),

          h('aside', { id: 'paper-workspace', inert: tool.value !== 'paper', tabindex: -1,
            'aria-label': 'Paper trading account' }, [
            h('h2', 'Paper trading'),
            h('div', { class: 'subnav' }, ['Orders', 'Automation'].map(name => h('button', {
              'aria-pressed': paperTab.value === name, onClick: () => { paperTab.value = name },
            }, name))),
            view('trade-view', paperTab.value === 'Orders', [h(PaperTrading, { accountId: m.paperAccount, symbol: m.symbol })]),
            !isApple.value && paperTab.value === 'Automation' ? h('p', 'Paper automation is available for AAPL.') : null,
            view('automation-view', paperTab.value === 'Automation', [h(AutomationPanel, {
              ref: automation, accountId: m.paperAccount, symbol: m.symbol, interval: m.timeframe, shortWindow: m.appliedShort,
              longWindow: m.appliedLong, completed: m.completed, onRunning: value => { automationOn.value = value },
            })]),
          ]),
        ]),
      ]),
    ]
  },
}).mount('#app')

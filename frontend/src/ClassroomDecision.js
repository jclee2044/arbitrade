import { computed, h, ref } from 'vue'
import { decisionDetails, matchesCapture, strategyReading } from './desk-agent.js'

export default {
  props: { capture: Function, chartSession: Number, chartRevision: Number, strategy: Object, dataMode: String,
    idPrefix: { type: String, default: 'classroom' } },
  emits: ['busy'],
  setup(props, { emit, expose }) {
    const entry = ref(null), error = ref(''), busy = ref(false)
    const id = suffix => props.idPrefix + '-' + suffix
    const result = computed(() => {
      const current = entry.value
      if (!current || current.variant !== props.strategy?.variant || current.session !== props.chartSession) return null
      return current.manual || current.revision === props.chartRevision ? current.decision : null
    })
    function present(decision, capture, revision, manual = false) {
      if (revision !== props.chartRevision || !matchesCapture(decision, capture)) return false
      entry.value = { decision, revision, variant: props.strategy?.variant, manual: manual && !props.strategy, session: props.chartSession }
      error.value = ''
      return true
    }
    async function analyze() {
      if (busy.value) return
      const revision = props.chartRevision
      busy.value = true; emit('busy', true); error.value = ''; entry.value = null
      try {
        const strategy = props.strategy, mode = props.dataMode
        const capture = await props.capture()
        const response = await fetch(strategy ? '/api/decisions/strategy' : '/api/decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(strategy ? { capture, strategy, data_mode: mode } : { capture }) })
        const value = await response.json()
        if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : 'Invalid chart capture')
        present(value, capture, revision, true)
      } catch (failure) { if (revision === props.chartRevision) error.value = failure.message }
      finally { busy.value = false; emit('busy', false) }
    }
    function clearChatResult() {
      if (!entry.value?.manual) entry.value = null
    }
    expose({ analyze, present, clearChatResult })
    return () => {
      const facts = result.value && decisionDetails(result.value)
      return h('section', { class: 'classroom-decision', 'aria-label': 'Chart image decision' }, [
        h('p', { class: 'fine-print' }, props.strategy ? 'Read-only daily strategy assessment.' : 'Chart reading: long, short or wait. No trade is placed.'),
        error.value ? h('p', { role: 'alert' }, error.value) : null,
        result.value ? h('div', { id: id('result'), 'aria-live': 'polite' }, [
          result.value.strategy_facts ? h('p', strategyReading(result.value.strategy_facts)) : null,
          result.value.agrees_with_strategy === false ? h('strong', 'Model disagrees with the measured rule') : null,
          h('h3', facts.choice ? `Chart choice · ${facts.choice}` : 'Chart decision unavailable'),
          h('p', { id: id('status') }, `Status: ${result.value.status}${result.value.error_code ? ' · ' + result.value.error_code : ''}`),
          h('p', { id: id('capture-context') }, `${facts.chart} · ${result.value.context.is_stale ? 'Stale or historical data' : 'Fresh data'}${result.value.context.volume_status === 'visible' ? ' · Volume visible' : ''}`),
          facts.probability ? h('p', { id: id('probability') }, `Returned probability · ${facts.probability}`) : null,
          h('details', [h('summary', 'Decision details'),
            h('p', { id: id('decision-id') }, `Decision ID: ${result.value.id}`),
            h('p', `${result.value.provider} / ${result.value.model} · ${result.value.model_call_kind}`),
            h('pre', JSON.stringify({ context: result.value.context, strategy_facts: result.value.strategy_facts, questions: result.value.questions, answer: result.value.answer }, null, 2))]),
        ]) : null,
        h('details', { class: 'decision-flow' }, [h('summary', 'How the Decision API works'),
          props.strategy ? h('p', 'The backend selects the frozen daily facts at the chart cutoff and sends them with the image. The model choice and probability are recorded separately from the simulated action.') : h('ol', [
            'Capture the visible chart, including volume and indicators, with identifying context.',
            'Validate the capture and ask OpenAI for long, short or wait.',
            'Validate and save the answer or error.',
            'Display the validated choice; report failures without a replacement choice.',
          ].map(text => h('li', text))),
        ]),
      ])
    }
  },
}

import { h, ref } from 'vue'

export default {
  props: { capture: Function },
  emits: ['busy'],
  setup(props, { emit, expose }) {
    const captured = ref(null), result = ref(null), error = ref(''), busy = ref(false)
    async function analyze() {
      if (busy.value) return
      busy.value = true; emit('busy', true); error.value = ''; result.value = null; captured.value = null
      try {
        // This capture contains pixels and a fixed set of identifying context fields only.
        captured.value = await props.capture()
        const response = await fetch('/api/decisions', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ capture: captured.value }) })
        const value = await response.json()
        if (!response.ok) throw Error(typeof value.detail === 'string' ? value.detail : 'Invalid chart capture')
        result.value = value
      } catch (failure) { error.value = failure.message }
      finally { busy.value = false; emit('busy', false) }
    }
    expose({ analyze })
    return () => h('section', { class: 'classroom-decision', 'aria-label': 'Chart image decision' }, [
      h('p', { class: 'fine-print' }, 'Chart reading: long, short or wait. No trade is placed.'),
      error.value ? h('p', { role: 'alert' }, error.value) : null,
      result.value ? h('div', { id: 'classroom-result', 'aria-live': 'polite' }, [
        h('h3', result.value.choice ? `Chart choice · ${result.value.choice.toUpperCase()}` : 'Chart decision unavailable'),
        h('p', { id: 'classroom-status' }, `Status: ${result.value.status}${result.value.error_code ? ' · ' + result.value.error_code : ''}`),
        h('p', { id: 'classroom-capture-context' }, `${result.value.context.ticker} · ${result.value.context.interval} · ${result.value.context.is_stale ? 'Stale or historical data' : 'Fresh data'}${result.value.context.volume_status === 'visible' ? ' · Volume visible' : ''}`),
        h('details', [h('summary', 'Decision details'),
          h('p', { id: 'classroom-decision-id' }, `Decision ID: ${result.value.id}`),
          h('p', `${result.value.provider} / ${result.value.model} · ${result.value.model_call_kind}`),
          h('pre', JSON.stringify({ context: result.value.context, questions: result.value.questions, answer: result.value.answer }, null, 2))]),
      ]) : null,
      h('details', { class: 'decision-flow' }, [h('summary', 'How the Decision API works'),
        h('ol', [
          'Capture the visible chart, including volume and indicators, with identifying context.',
          'Validate the capture and ask OpenAI for long, short or wait.',
          'Validate and save the answer or error.',
          'Display the validated choice; report failures without a replacement choice.',
        ].map(text => h('li', text))),
      ]),
    ])
  },
}

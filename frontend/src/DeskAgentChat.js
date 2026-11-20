import { h, nextTick, reactive, ref } from 'vue'
import { decisionDetails, strategyReading } from './desk-agent.js'

export default {
  props: { market: Object, decisionBusy: Boolean, presentAssessment: Function, strategy: Object, sessionLabel: String, idPrefix: { type: String, default: 'desk-chat' } },
  emits: ['busy', 'new-chat'],
  setup(props, { emit }) {
    const question = ref('')
    const busy = ref(false)
    const transcript = ref(null)
    const messages = reactive([])
    let conversationId

    function newChat() {
      conversationId = undefined
      messages.splice(0)
      question.value = ''
      busy.value = false
      emit('busy', false)
      emit('new-chat')
    }

    async function send(event) {
      event.preventDefault()
      const text = question.value.trim()
      if (!text || busy.value || props.decisionBusy) return
      const m = props.market
      const revision = m.chartRevision
      const id = conversationId ??= crypto.randomUUID()
      const message = reactive({ question: text, revision, session: props.sessionLabel, pending: true })
      messages.push(message)
      question.value = ''
      busy.value = true
      emit('busy', true)
      let capture
      try {
        const response = await m.askDeskAgent(text, { conversationId: id, strategy: props.strategy, capture: async () => {
          if (!m.waiting && m.candles.length) capture = await m.captureVisibleChart()
          return capture
        } })
        if (id !== conversationId) return
        message.answer = response.answer
        message.tools = response.tool_results
        message.reading = message.tools?.find(tool => tool.name === 'read_strategy_facts')?.result.strategy_facts
        if (response.httpStatus >= 400 || response.status !== 'ok') message.error = response.error_code || `HTTP ${response.httpStatus}`
        const assessment = message.tools?.find(tool => tool.name === 'assess_visible_chart')?.result
        if (assessment?.context) {
          message.assessment = assessment
          if (assessment.status === 'valid') message.previousAssessment = response.previous_assessment
          message.detached = !props.presentAssessment(assessment, capture, revision)
        }
      } catch (error) {
        message.error = error.message
      } finally {
        if (id === conversationId) {
          message.pending = false
          busy.value = false
          emit('busy', false)
          await nextTick()
          const log = transcript.value
          if (log?.lastElementChild) {
            log.scrollTop += log.lastElementChild.getBoundingClientRect().top - log.getBoundingClientRect().top
          }
        }
      }
    }

    function turn(message) {
      const facts = message.assessment && decisionDetails(message.assessment)
      const prior = message.previousAssessment && decisionDetails(message.previousAssessment)
      return h('article', { class: 'desk-chat-turn' }, [
        message.session ? h('p', { class: 'fine-print' }, message.session) : null,
        h('p', { class: 'desk-chat-question' }, message.question),
        message.pending ? h('p', { role: 'status' }, 'Waiting for the assistant…') : null,
        message.answer ? h('p', { class: 'desk-chat-answer' }, message.answer) : null,
        message.error ? h('p', { role: 'alert' }, `Assistant request failed · ${message.error}`) : null,
        message.reading ? h('p', { class: 'desk-chat-assessment' }, strategyReading(message.reading)) : null,
        facts ? h('div', { class: 'desk-chat-assessment' }, [
          prior ? h('p', { class: 'desk-chat-previous' }, [`Earlier · ${prior.chart}`,
            prior.choice, prior.probability && `Returned probability · ${prior.probability}`].filter(Boolean).join(' · ')) : null,
          message.assessment.strategy_facts ? h('p', strategyReading(message.assessment.strategy_facts)) : null,
          message.assessment.agrees_with_strategy === false ? h('p', 'Model choice differs from the rule action.') : null,
          h('p', facts.chart),
          h('p', [facts.choice || 'Chart decision unavailable', facts.probability && `Returned probability · ${facts.probability}`].filter(Boolean).join(' · ')),
          message.detached || message.revision !== props.market.chartRevision
            ? h('p', { class: 'fine-print' }, 'Result for an earlier chart snapshot.') : null,
        ]) : null,
        message.tools?.length ? h('details', { class: 'desk-chat-tools' }, [
          h('summary', 'Tools and results'),
          ...message.tools.map(tool => h('div', [
            h('p', [h('code', tool.name), ` · ${tool.result.status}`]),
            tool.result.error_code ? h('p', { role: 'status' }, tool.result.error_code) : null,
            h('pre', JSON.stringify(tool.result, null, 2)),
          ])),
        ]) : null,
      ])
    }

    return () => h('section', { class: 'desk-chat', 'aria-labelledby': props.idPrefix + '-title' }, [
      h('div', { class: 'desk-chat-heading' }, [
        h('h2', { id: props.idPrefix + '-title' }, 'Desk Assistant'),
        h('button', { type: 'button', class: 'text-button', onClick: newChat }, 'New chat'),
      ]),
      props.sessionLabel ? h('p', { class: 'desk-session' }, 'Discussing ' + props.sessionLabel) : null,
      messages.length ? h('div', { class: 'desk-chat-log', ref: transcript, role: 'log', 'aria-label': 'Desk Assistant messages' },
        messages.map(turn)) : null,
      h('form', { onSubmit: send }, [
        h('label', { for: props.idPrefix + '-question', class: 'sr-only' }, 'Message for Desk Assistant'),
        h('textarea', { id: props.idPrefix + '-question', rows: 3, maxlength: 2000,
          placeholder: props.sessionLabel ? 'Ask why the strategy acted on this signal' : 'Ask about a rule or request a chart assessment', value: question.value,
          onInput: event => { question.value = event.target.value } }),
        h('button', { class: 'primary', type: 'submit', disabled: busy.value || props.decisionBusy || !question.value.trim() }, 'Send'),
      ]),
    ])
  },
}

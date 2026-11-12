import { h } from 'vue'

function icon(path) {
  return h('svg', { viewBox: '0 0 24 24', width: 22, height: 22, fill: 'none', stroke: 'currentColor',
    'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' }, [h('path', { d: path })])
}

export default {
  props: { tool: String, mode: String, automationOn: Boolean, voiceOn: Boolean },
  emits: ['navigate', 'mode', 'stop', 'voice'],
  setup(props, { emit }) {
    return () => [
      h('a', { class: 'skip-link', href: '#desk' }, 'Skip to workspace'),
      h('header', { class: 'masthead' }, [
        h('h1', { class: 'app-brand' }, [
          h('img', { src: '/brand/arbitrade-wordmark.svg', alt: 'Arbitrade', width: 165, height: 36 }),
        ]),
        h('div', { class: 'header-actions' }, [
          props.voiceOn ? h('button', { class: 'session-action', onClick: () => emit('voice') }, 'Voice active') : null,
          props.automationOn ? h('button', { class: 'session-action', onClick: () => emit('stop') }, 'Stop automation') : null,
          h('label', { class: 'sr-only', for: 'mode' }, 'Market mode'),
          h('select', { id: 'mode', class: 'mode-select', value: props.mode, onChange: e => emit('mode', e.target.value) },
            [h('option', { value: 'live' }, 'Live'), h('option', { value: 'replay' }, 'Replay')]),
          h('button', { class: 'paper-entry', 'aria-pressed': props.tool === 'paper', 'aria-controls': 'paper-workspace',
            onClick: () => emit('navigate', props.tool === 'paper' ? 'chart' : 'paper') },
          [icon('M3 7h18v12H3z M4 7V5l13-2v4 M16 12h5'), 'Paper trading']),
        ]),
      ]),
    ]
  },
}

import { h, ref, watch, onBeforeUnmount, computed } from 'vue'

export default {
  props: { accountId: String, symbol: { type: String, default: 'AAPL' } },
  setup(props) {
    const connectionError = ref('')
    const state = ref(null), quantity = ref('1'), error = ref(''), message = ref(''), busy = ref(false)
    const lastRequest = ref(null)
    let timer, generation = 0
    const pnlSummary = computed(() => state.value?.pnl_summary?.find((item) => item.symbol === props.symbol))
    const pnlRows = computed(() => (state.value?.pnl_history || []).filter((item) => item.symbol === props.symbol))
    const pnlUsd = (value) => value == null ? 'Unavailable' : usd(value)
    const usd = (value) => Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
    async function load() {
      const token = generation, account = props.accountId
      if (!account) return
      try {
        const response = await fetch(`/api/paper/account?${new URLSearchParams({ account_id: account })}`)
        const result = await response.json()
        if (!response.ok) throw new Error(result.detail || 'Could not load paper account')
        if (token === generation) {
          state.value = result; connectionError.value = ''
          const order = result.orders.find((item) => item.request_id === lastRequest.value?.request_id)
          if (order && order.status !== 'pending') message.value = order.rejection_reason || `Order ${order.id} · ${order.status}`
        }
      } catch (failure) { if (token === generation) connectionError.value = failure.message }
    }
    async function send(action, retry = false) {
      if (!props.accountId || busy.value) return
      error.value = ''
      message.value = ''
      let request = lastRequest.value
      if (!retry) {
        let amount = null
        if (action === 'buy' || action === 'sell') {
          amount = Number(quantity.value)
          if (!/^[1-9]\d*$/.test(quantity.value) || !Number.isSafeInteger(amount) || amount > 2147483647) {
            error.value = 'Quantity must be a positive whole number, at most 2147483647.'
            return
          }
        }
        request = { account_id: props.accountId, request_id: crypto.randomUUID(), action, symbol: props.symbol, quantity: amount }
        // Retain this exact intent/id through network failure and explicit retry.
        lastRequest.value = request
      }
      if (!request) return
      const token = generation
      busy.value = true
      try {
        const response = await fetch('/api/paper/actions', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
        })
        const result = await response.json()
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not submit paper action')
        if (token !== generation) return
        state.value = result.state
        message.value = result.result.rejection_reason || (result.result.status === 'pending' ? 'Order accepted · pending next eligible observed price.' :
          result.result.status === 'no_order' ? `${action || request.action}: no order created.` : `Order ${result.result.id} · ${result.result.status}`)
      } catch (failure) { if (token === generation) error.value = `Request uncertain: ${failure.message}. Use Retry last request to reuse its ID.` }
      finally { if (token === generation) busy.value = false }
    }
    watch(() => props.accountId, () => {
      generation++
      clearInterval(timer)
      state.value = null; error.value = ''; connectionError.value = ''; message.value = ''; lastRequest.value = null; busy.value = false
      load()
      timer = setInterval(load, 700)
    }, { immediate: true })
    onBeforeUnmount(() => { generation++; clearInterval(timer) })
    const holding = () => state.value?.positions.find((item) => item.symbol === props.symbol)?.shares || 0
    return () => h('div', { class: 'paper-trading', 'aria-labelledby': 'paper-title', 'data-account-id': props.accountId }, [
      h('h3', { id: 'paper-title' }, props.accountId?.startsWith('replay-') ? 'Replay paper account' : 'Live paper account'),
      h('details', [h('summary', 'Simulation rules'),
        h('p', 'Long-only · $1,000 starting cash · Zero fees. Orders fill at the next eligible new regular-session observation after submission.'),
        h('p', props.accountId?.startsWith('replay-') ? 'Only newly revealed observations can fill orders. Restarting replay creates a separate account.' : 'Orders remain pending while the feed is disabled or no eligible price arrives.'),
      ]),
      !props.accountId ? h('p', 'Waiting for a replay account.') : null,
      state.value ? h('dl', { class: 'paper-balances' }, [
        h('dt', 'Cash'), h('dd', { id: 'paper-cash' }, usd(state.value.account.cash)),
        h('dt', `${props.symbol} shares`), h('dd', { id: 'paper-shares' }, String(holding())),
      ]) : null,
      h('label', { for: 'paper-quantity' }, 'Whole shares '),
      h('input', { id: 'paper-quantity', type: 'number', min: 1, step: 1, value: quantity.value,
        onInput: (event) => { quantity.value = event.target.value } }),
      h('div', { class: 'paper-actions' }, [
        ...[['buy', 'Buy shares'], ['sell', 'Sell shares'], ['close', 'Close position'], ['hold', 'Hold'], ['wait', 'Wait']].map(([action, label]) =>
          h('button', { class: action, disabled: busy.value || !state.value, onClick: () => send(action) }, label)),
        h('button', { disabled: busy.value || !lastRequest.value, onClick: () => send(null, true) }, 'Retry last request'),
      ]),
      message.value ? h('p', { id: 'paper-result', role: 'status' }, message.value) : null,
      error.value ? h('p', { role: 'alert' }, error.value) : null,
      connectionError.value ? h('p', { role: 'alert' }, connectionError.value) : null,
      h('details', [h('summary', 'Paper order history'),
      h('div', { class: 'paper-history', role: 'region', 'aria-label': 'Paper order history', tabindex: 0 }, [h('table', [
        h('thead', [h('tr', ['ID', 'Symbol', 'Side', 'Quantity', 'Submitted (UTC)', 'Status / reason', 'Fill'].map((text) => h('th', text)))]),
        h('tbody', (state.value?.orders || []).map((order) => {
          const fill = state.value.fills.find((item) => item.order_id === order.id)
          return h('tr', { key: order.id, 'data-order-id': order.id }, [
            order.id, order.symbol, order.side, order.quantity ?? 'Invalid', order.submitted_at,
            `${order.status}${order.rejection_reason ? ` · ${order.rejection_reason}` : ''}`,
            fill ? `${fill.quantity} @ ${usd(fill.price)} · Observation ${fill.observation_id} / receipt ${fill.receipt_id} · ${fill.executed_at}` : '—',
          ].map((text) => h('td', String(text))))
        })),
      ])]),
      !state.value?.orders.length ? h('p', 'No paper orders. Hold and wait do not create orders.') : null]),
      h('div', { class: 'pnl-panel', 'aria-labelledby': 'pnl-title' }, [
        h('h4', { id: 'pnl-title' }, 'Profit and loss · USD'),
        h('p', 'Based on weighted average purchase cost.'),
        h('dl', { class: 'paper-balances pnl-summary' }, [
          h('dt', 'Average cost / share'), h('dd', { id: 'pnl-average' }, holding() ? pnlUsd(pnlSummary.value?.average_cost) : '—'),
          h('dt', 'Realized P&L'), h('dd', { id: 'pnl-realized' }, pnlUsd(pnlSummary.value?.realized ?? '0')),
          h('dt', 'Unrealized P&L'), h('dd', { id: 'pnl-unrealized' }, pnlUsd(pnlSummary.value?.unrealized ?? (holding() ? null : '0'))),
          h('dt', 'Total P&L'), h('dd', { id: 'pnl-total' }, pnlUsd(pnlSummary.value?.total ?? (holding() ? null : '0'))),
        ]),
        h('p', { id: 'pnl-price' }, pnlSummary.value?.price != null
          ? `Valuation price: ${usd(pnlSummary.value.price)} · ${pnlSummary.value.price_source} · Price time (UTC): ${pnlSummary.value.price_time}`
          : holding() ? 'Valuation unavailable: no usable price for this open position.' : 'No open position to value.'),
        h('details', [h('summary', 'P&L history'),
        h('div', { class: 'pnl-history', role: 'region', 'aria-label': 'Profit and loss history', tabindex: 0 }, [h('table', { id: 'pnl-history' }, [
          h('thead', [h('tr', ['Event / time (UTC)', 'Price / source / price time (UTC)', 'Cash', 'Shares', 'Average cost', 'Realized', 'Unrealized', 'Total P&L'].map((label) => h('th', label)))]),
          h('tbody', pnlRows.value.map((row) => h('tr', { key: row.id, 'data-pnl-event': row.event_key }, [
            `${row.symbol} · ${row.event_type === 'fill' ? `Fill ${row.fill_id}` : 'Completed 1m candle'} · ${row.event_time}`,
            `${pnlUsd(row.price)} · ${row.price_source} · ${row.price_time || 'Unknown time'}`,
            usd(row.cash), String(row.shares), row.average_cost == null ? '—' : usd(row.average_cost),
            pnlUsd(row.realized), pnlUsd(row.unrealized), pnlUsd(row.total),
          ].map((value) => h('td', value))))),
        ])]),
        !pnlRows.value.length ? h('p', 'No P&L events yet. A fill starts the history; completed candle marks update open positions.') : null]),
      ]),
    ])
  },
}

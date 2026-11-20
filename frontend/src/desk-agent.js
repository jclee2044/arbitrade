import { formatEastern } from './chart-data.js'

export function decisionDetails(decision) {
  const context = decision.context
  const chart = context && `${context.ticker} · ${context.interval} · ${formatEastern(Date.parse(context.candle_timestamp) / 1000)}`
  const choice = decision.choice?.toUpperCase()
  const probability = decision.answer?.probabilities?.find(item => item.value === decision.choice)?.probability
  return { chart, choice, probability: Number.isFinite(probability)
    ? new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 4 }).format(probability)
    : null }
}

export function matchesCapture(decision, capture) {
  const context = decision.context
  return Boolean(context && capture && context.ticker === capture.ticker && context.interval === capture.interval &&
    Date.parse(context.captured_at) === Date.parse(capture.captured_at) &&
    Date.parse(context.candle_timestamp) === Date.parse(capture.candle_timestamp))
}

export async function requestDeskAgent(question, captureChart, conversationId, dataMode, strategy) {
  const request = { question, conversation_id: conversationId, data_mode: dataMode }
  if (strategy) request.strategy = strategy
  const capture = await captureChart?.()
  if (capture) request.capture = capture
  const response = await fetch('/api/desk-agent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  const data = await response.json()
  return { ...data, httpStatus: response.status }
}

export const strategyLabels = { baseline: '20/50 baseline', sma200: 'Close above SMA 200', ema200: 'Close above EMA 200' }

export function strategyReading(f) {
  return [strategyLabels[f.variant], formatEastern(Date.parse(f.cutoff) / 1000),
    f.verdict.toUpperCase(), f.reason.replaceAll('_', ' ')].join(' · ')
}

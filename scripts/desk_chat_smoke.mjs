import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'

const [output, provider, scenario] = process.argv.slice(2)
const live = provider === 'live'
const conversation = scenario === 'conversation'
const base = 'http://127.0.0.1:15264'
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const page = await browser.newPage({ viewport: { width: 1440, height: conversation ? 1450 : 1050 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(live ? 70000 : 10000)
const panel = page.getByRole('region', { name: 'Desk Assistant' })
const chart = page.locator('#classroom-result')

async function send(question, afterSend) {
  const pending = page.waitForResponse(r => r.url().endsWith('/api/desk-agent') && r.request().method() === 'POST')
  await panel.getByRole('textbox').fill(question)
  await panel.getByRole('button', { name: 'Send' }).click()
  await afterSend?.()
  const response = await pending
  const request = response.request().postDataJSON()
  assert.equal(request.question, question)
  assert.equal(request.capture.ticker, 'AAPL')
  assert(request.capture.image.startsWith('data:image/png;base64,'))
  const result = await response.json()
  console.log(JSON.stringify({ scenario: question, http: response.status(), status: result.status,
    error: result.error_code, tools: result.tool_results?.map(tool => [tool.name, tool.result.status, tool.result.error_code]) }))
  assert.equal(response.status(), 200)
  const turn = panel.locator('.desk-chat-turn').last()
  await turn.locator('.desk-chat-answer').waitFor()
  assert.equal((await turn.locator('.desk-chat-answer').textContent()).trim(), result.answer.trim())
  if (result.tool_results.length) {
    await turn.getByText('Tools and results', { exact: true }).click()
    const returned = (await turn.locator('pre').allTextContents()).map(text => JSON.parse(text))
    assert.deepEqual(returned, result.tool_results.map(tool => tool.result))
    await turn.getByText('Tools and results', { exact: true }).click()
  }
  return { result, turn, capture: request.capture, conversationId: request.conversation_id, mode: request.data_mode }
}

async function verifyConversation() {
  await page.locator('#mode').selectOption('replay')
  await page.locator('#replay-symbol option').first().waitFor({ state: 'attached' })
  await page.locator('#replay-start').fill('2026-11-10T15:00:10Z')
  await page.locator('#replay-end').fill('2026-11-10T15:06:10Z')
  await page.getByRole('button', { name: 'Load / restart replay' }).click()
  await page.waitForFunction(() => document.querySelector('#replay-status')?.textContent.startsWith('0 /'))
  async function step(position) {
    await page.getByRole('button', { name: 'Next observation' }).click()
    await page.waitForFunction(n => document.querySelector('#replay-status')?.textContent.startsWith(n + ' /'), position)
  }
  await step(1)
  const rules = await send('What does WAIT mean in this app?')
  assert.deepEqual(rules.result.tool_results.map(tool => tool.name), ['lookup_trading_rules'])
  assert.equal(await chart.count(), 0)
  await page.screenshot({ path: resolve(output, '01-wait-rule.png') })

  function rawAssessment(turn) {
    assert.equal(turn.mode, 'replay')
    assert.deepEqual(turn.result.tool_results.map(tool => tool.name), ['assess_visible_chart'])
    const assessment = turn.result.tool_results[0].result
    assert.equal(assessment.status, 'valid')
    assert.equal(Date.parse(assessment.context.candle_timestamp), Date.parse(turn.capture.candle_timestamp))
    return assessment
  }
  const probability = decision => decision.answer.probabilities?.find(p => p.value === decision.choice)?.probability
  const percent = value => new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 4 }).format(value)
  async function verifyDisplay(turn, decision, earlier) {
    console.log(JSON.stringify({ answer: turn.result.answer,
      choice: decision.choice, time: decision.context.candle_timestamp, probability: probability(decision) }))
    assert.match(turn.result.answer, new RegExp(`\\b${decision.choice}\\b`, 'i'))
    const value = probability(decision)
    if (value !== undefined) {
      const label = 'Returned probability · ' + percent(value)
      assert(turn.result.answer.includes(percent(value)))
      assert.equal(await chart.locator('#classroom-probability').textContent(), label)
      assert((await turn.turn.locator('.desk-chat-assessment').textContent()).includes(label))
    }
    await chart.getByRole('heading', { name: 'Chart choice · ' + decision.choice.toUpperCase() }).waitFor()
    const eastern = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    })
    const time = result => eastern.format(new Date(result.context.candle_timestamp)) + ' ET'
    assert((await chart.locator('#classroom-capture-context').textContent()).includes(time(decision)))
    if (earlier) {
      assert(turn.result.answer.includes(time(earlier)) && turn.result.answer.includes(time(decision)))
      assert.match(turn.result.answer, new RegExp(`\\b${earlier.choice}\\b`, 'i'))
      if (probability(earlier) !== undefined) assert(turn.result.answer.includes(percent(probability(earlier))))
      const priorText = await turn.turn.locator('.desk-chat-previous').textContent()
      assert(priorText.includes(time(earlier)) && priorText.includes(earlier.choice.toUpperCase()))
    }
    await chart.getByText('Decision details', { exact: true }).click()
    await chart.getByText('Decision ID: ' + decision.id, { exact: true }).waitFor()
    await chart.getByText('Decision details', { exact: true }).click()
    const saved = await page.request.get(base + decision.image_url)
    assert.deepEqual(await saved.body(), Buffer.from(turn.capture.image.split(',')[1], 'base64'))
  }
  const first = await send("Run the decision on the chart I'm looking at. What do you recommend?")
  const earlier = rawAssessment(first)
  assert.equal(first.conversationId, rules.conversationId)
  assert.equal(first.result.previous_assessment, null)
  await verifyDisplay(first, earlier)
  await page.screenshot({ path: resolve(output, '02-first-assessment.png') })
  await step(2)
  const comparison = 'Run a new decision for this chart and compare it with the earlier assessment.'
  const later = await send(comparison)
  const newest = rawAssessment(later)
  assert.equal(later.conversationId, first.conversationId)
  assert.deepEqual(later.result.previous_assessment, earlier)
  assert(Date.parse(newest.context.candle_timestamp) > Date.parse(earlier.context.candle_timestamp))
  await verifyDisplay(later, newest, earlier)
  await page.screenshot({ path: resolve(output, '03-comparison.png') })
  await panel.getByRole('button', { name: 'New chat' }).click()
  assert.equal(await panel.locator('.desk-chat-turn').count(), 0)
  assert.equal(await chart.count(), 0)
  if (!live) {
    const fresh = await send(comparison)
    assert.notEqual(fresh.conversationId, first.conversationId)
    assert.equal(fresh.result.previous_assessment, null)
    assert.match(fresh.result.answer, /no earlier assessment/i)
    await page.screenshot({ path: resolve(output, '04-new-chat.png') })
  }
  console.log('PASS: same conversation compared both replay snapshots; New chat cleared the prior assessment')
}

async function verifySingleTurn() {
  const rules = await send('Explain the wait rule in Arbitrade’s paper strategy.')
  assert.deepEqual(rules.result.tool_results.map(tool => tool.name), ['lookup_trading_rules'])
  assert.equal(await chart.count(), 0)
  const unclear = await send('Should I wait?')
  assert.deepEqual(unclear.result.tool_results, [])
  assert.match(unclear.result.answer, /rule/i)
  assert.match(unclear.result.answer, /chart/i)
  assert.equal(await chart.count(), 0)

  const assessment = await send('Assess the visible chart and report the Decision API choice.')
  const decision = assessment.result.tool_results.find(tool => tool.name === 'assess_visible_chart')?.result
  assert.equal(decision?.status, 'valid')
  assert.match(assessment.result.answer, new RegExp(`\\b${decision.choice}\\b`, 'i'))
  assert.equal(decision.context.ticker, assessment.capture.ticker)
  assert.equal(Date.parse(decision.context.candle_timestamp), Date.parse(assessment.capture.candle_timestamp))
  const chartContext = await chart.locator('#classroom-capture-context').textContent()
  const summary = await assessment.turn.locator('.desk-chat-assessment').textContent()
  assert(chartContext.startsWith(`AAPL · ${decision.context.interval} · `))
  assert(summary.startsWith(chartContext.split(' · Stale')[0].split(' · Fresh')[0]))
  assert(summary.includes(decision.choice.toUpperCase()))
  await chart.getByRole('heading', { name: `Chart choice · ${decision.choice.toUpperCase()}` }).waitFor()
  const probability = decision.answer?.probabilities?.find(item => item.value === decision.choice)?.probability
  if (probability !== undefined) {
    const label = `Returned probability · ${new Intl.NumberFormat('en-US', {
      style: 'percent', maximumFractionDigits: 4,
    }).format(probability)}`
    assert(summary.includes(label))
    assert.equal(await chart.locator('#classroom-probability').textContent(), label)
  } else {
    assert.equal(await chart.locator('#classroom-probability').count(), 0)
  }
  const saved = await page.request.get(base + decision.image_url)
  assert.deepEqual(await saved.body(), Buffer.from(assessment.capture.image.split(',')[1], 'base64'))
  await page.screenshot({ path: resolve(output, 'assessment.png') })

  if (!live) {
    const failure = await send('Assess the visible chart again.')
    assert.equal(failure.result.tool_results[0].result.error_code, 'controlled_chart_timeout')
    assert.match(failure.result.answer, /timed out/)
    assert.match(await chart.locator('#classroom-status').textContent(), /controlled_chart_timeout/)
    assert.equal(await chart.locator('#classroom-probability').count(), 0)

    let releaseReply, processed
    const hold = new Promise(resolve => { releaseReply = resolve })
    const ready = new Promise(resolve => { processed = resolve })
    await page.route('**/api/desk-agent', async route => {
      const response = await route.fetch()
      processed()
      await hold
      await route.fulfill({ response })
    }, { times: 1 })
    const delayed = await send('Assess the visible chart one more time.', async () => {
      await ready
      try {
        await page.locator('[data-frame="5m"]').click()
        await page.locator('[data-frame="1m"]').click()
      } finally {
        releaseReply()
      }
    })
    assert.equal(delayed.result.tool_results[0].result.choice, 'long')
    await delayed.turn.getByText('Result for an earlier chart snapshot.').waitFor()
    assert.equal(await chart.count(), 0)
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  }
  console.log('PASS: assistant text, actual tool records, captured PNG and chart display agree')
}

try {
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: 'AI', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.summary-actions .primary')?.disabled)
  if (conversation) await verifyConversation()
  else await verifySingleTurn()
  assert.deepEqual(errors, [])
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {})
  throw error
} finally {
  await browser.close()
}

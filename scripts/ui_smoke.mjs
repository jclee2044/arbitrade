import { candleCount, hoverCandle, hoverValues, market } from './chart-browser.mjs'
// UI driver for ui_smoke.py. It is run only after Playwright use is approved.
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createInterface } from 'node:readline/promises'
import { resolve } from 'node:path'
import { mkdir } from 'node:fs/promises'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const output = resolve(process.argv[2] || '/tmp/arbitrade-ui-results')
const live = process.argv[3] === 'live'
await mkdir(output, { recursive: true })
const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]()
async function request(action) {
  process.stdout.write(JSON.stringify({ action }) + '\n')
  const reply = await lines.next()
  assert(!reply.done, 'Test coordinator disconnected')
  return JSON.parse(reply.value)
}
async function until(check, description, timeout = 10000) {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    if (await check()) return
    await new Promise((done) => setTimeout(done, 100))
  }
  throw new Error(`Timed out: ${description}`)
}
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 1000 } })
const page = await context.newPage()
const errors = []
const checks = []
const sockets = new Set()
page.on('pageerror', (error) => errors.push(error.message))
page.on('websocket', (socket) => {
  // Vite also opens a development/HMR socket; count only chart transport.
  if (new URL(socket.url()).pathname !== '/api/live') return
  sockets.add(socket)
  socket.on('close', () => sockets.delete(socket))
})
const eastern = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/New_York', dateStyle: 'short', timeStyle: 'short' })
const usd = value => value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })
async function compare(snapshot, index = snapshot.candles.length - 1) {
  const candle = snapshot.candles[index]
  const completion = snapshot.coverage[index]
  assert(candle, 'Expected a candle from stored observations')
  await until(async () => await candleCount(page) === snapshot.candles.length, 'matching number of chart candles')
  const card = await hoverCandle(page, candle.timestamp)
  const expected = {
    Open: usd(candle.open), High: usd(candle.high), Low: usd(candle.low), Close: usd(candle.close),
  }
  if (candle.volume != null) {
    const label = completion.volume_provenance === 'yahoo_quote_counter' ? 'Observed volume' : 'Volume'
    expected[label] = candle.volume.toLocaleString('en-US')
  }
  await until(async () => JSON.stringify(await hoverValues(card)) === JSON.stringify(expected), 'hover values equal stored backend candle')
  assert.equal(await card.locator('strong').innerText(), eastern.format(new Date(candle.timestamp)) + ' ET')
  const shown = await market(page).evaluate(el => el.__vueParentComponent.props.market.hoveredCandle?.time)
  assert.equal(shown, Date.parse(candle.timestamp) / 1000)
  assert.equal(await page.locator('#timeframe [aria-pressed=true]').getAttribute('data-frame'), snapshot.interval)
  await page.getByRole('heading', { name: `AAPL · ${snapshot.interval} candles`, exact: true }).waitFor()
  assert.equal(await page.getByRole('alert').count(), 0)
}
async function fillsViewport() {
  await until(() => page.locator('.chart').evaluate(chart =>
    Math.abs(chart.getBoundingClientRect().bottom - innerHeight) <= 1 &&
    document.documentElement.scrollHeight <= innerHeight + 1), 'chart reaches the viewport bottom')
}
try {
  await page.goto(process.argv[4] || 'http://127.0.0.1:5173', { waitUntil: 'networkidle' })
  assert.equal(await page.locator('#timeframe [aria-pressed=true]').getAttribute('data-frame'), '1m')
  await fillsViewport()
  assert.equal(await page.locator('.market-column').locator('.history-navigation, .feed-strip, .feed-details').count(), 0)
  assert.equal(await page.getByRole('button', { name: /^(Previous day|Latest candles)$/ }).count(), 0)
  assert.equal(await page.getByText('Go to date', { exact: false }).count(), 0)
  const feed = page.locator('.rail-pane:not([inert]) > .feed-details:last-child')
  await feed.locator('summary').click()
  await page.getByRole('button', { name: 'Check connection', exact: true }).click()
  await page.getByText('Backend connected:', { exact: false }).waitFor()
  await fillsViewport()
  checks.push('Removed chart controls and feed strip; Feed details is last in Indicators and Check connection works without resizing the chart')
  if (!live) {
    await page.getByText('Waiting for stored or live observations', { exact: false }).waitFor()
  } else {
    await until(async () => await candleCount(page) > 0, 'live candles received', 45000)
  }
  let snapshots = await request('seed')
  await compare(snapshots['1m'])
  if (!live) {
    const recovery = await context.newPage()
    const attempts = { voice: 0, replay: 0 }
    try {
      for (const [kind, path] of [['voice', '/api/voice/decisions'], ['replay', '/api/replay/selections']]) {
        await recovery.route('**' + path, async route => {
          if (++attempts[kind] === 1) await route.fulfill({ status: 503, json: { detail: 'Temporary test outage' } })
          else await route.continue()
        })
      }
      await recovery.goto(process.argv[4] || 'http://127.0.0.1:5173')
      await until(async () => attempts.voice === 1 && attempts.replay === 1, 'initial simulated outages')
      await recovery.selectOption('#mode', 'replay')
      await until(async () => attempts.voice >= 2 && attempts.replay >= 2, 'saved lists automatically retry', 15000)
      await until(async () => (await recovery.locator('#replay-start').inputValue()).length > 0, 'saved replay range recovers')
      const nextReceipt = recovery.getByRole('button', { name: 'Next observation', exact: true })
      await until(async () => await nextReceipt.isEnabled(), 'replay connects after saved range recovers')
      await nextReceipt.click()
      await until(async () => (await recovery.locator('#replay-status').textContent()).startsWith('1 /'), 'replay advances one stored receipt')
      await recovery.getByRole('tab', { name: 'AI', exact: true }).click()
      await until(async () => await recovery.getByText('Cannot load saved decisions', { exact: true }).count() === 0, 'voice outage error clears')
      await recovery.screenshot({ path: resolve(output, 'saved-list-recovery.png'), fullPage: true })
      checks.push('Initial voice/replay HTTP 503 retries without reload; voice error clears, replay range loads and Next advances a stored receipt')
    } finally {
      await recovery.close()
    }
  }
  await page.getByText(live ? 'Source: Yahoo Finance' : 'Source: CONSTRUCTED replay', { exact: false }).waitFor()
  checks.push(live ? 'Actual Yahoo stored quote/time/OHLCV equals visible hover card' : 'Labeled constructed input; exact OHLCV and Eastern hover timestamp')
  const initialCount = await candleCount(page)
  await page.screenshot({ path: resolve(output, 'initial.png'), fullPage: true })
  if (!live) {
    snapshots = await request('same')
    await compare(snapshots['1m'])
    assert.equal(await candleCount(page), initialCount)
    await page.screenshot({ path: resolve(output, 'same-minute.png'), fullPage: true })
    checks.push('Same-minute close and volume replaced without a duplicate candle')
    snapshots = await request('rollover')
    await compare(snapshots['1m'])
    assert.equal(await candleCount(page), initialCount + 1)
    await page.screenshot({ path: resolve(output, 'rollover-forming.png'), fullPage: true })
    await compare(snapshots['1m'], snapshots['1m'].candles.length - 2)
    await page.screenshot({ path: resolve(output, 'prior-minute-ended.png'), fullPage: true })
    checks.push('Next minute adds a candle; preceding minute remains available for hover')
  }
  for (const interval of ['5m', '15m', '30m', '1h', '1d', '1w', '1mo', '1m']) {
    await page.locator('[data-frame="' + interval + '"]').click()
    await compare(snapshots[interval])
    await page.screenshot({ path: resolve(output, `timeframe-${interval}.png`), fullPage: true })
  }
  checks.push('All timeframe selectors load matching backend history; daily included')
  const status = page.locator('#transport-status')
  await until(async () => /Source age: \d+ seconds/.test(await status.textContent()), 'source age shown')
  const firstAge = (await status.textContent()).match(/Source age: (\d+)/)[1]
  await until(async () => (await status.textContent()).match(/Source age: (\d+)/)?.[1] !== firstAge, 'source age advances')
  await request('disconnect')
  await until(async () => /Chart: Connected to FastAPI.*Feed: disconnected/.test(await status.textContent()), 'upstream loss shown with connected chart transport')
  await until(() => sockets.size === 1, 'one surviving chart WebSocket')
  checks.push('Source age advances; disconnected upstream displayed while chart WebSocket remains open')
  const canvas = page.locator('.chart canvas').first()
  await canvas.waitFor({ state: 'visible' })
  const box = await canvas.boundingBox()
  assert(box.width > 200 && box.height > 50, 'Rendered chart canvas has useful dimensions')
  await page.screenshot({ path: resolve(output, 'disconnected-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  await page.evaluate(() => window.scrollTo(0, 0))
  await fillsViewport()
  await compare(snapshots['1m'])
  const mobileChart = await page.locator('.chart').boundingBox()
  assert(mobileChart.x >= 0 && mobileChart.x + mobileChart.width <= 391)
  await page.screenshot({ path: resolve(output, 'mobile.png'), fullPage: true })
  assert.deepEqual(errors, [], 'No uncaught browser JavaScript errors')
  checks.push('Chart reaches the viewport bottom on desktop and collapsed mobile; screenshots saved; no uncaught browser errors')
  process.stdout.write(JSON.stringify({ action: 'done', checks }) + '\n')
} catch (error) {
  if (live && checks.length > 0 && errors.length === 0 && await candleCount(page) === 0) {
    await page.screenshot({ path: resolve(output, 'pending-live.png'), fullPage: true })
    process.stdout.write(JSON.stringify({ action: 'pending', checks, reason: 'No in-session candle received within the live browser deadline' }) + '\n')
  } else {
    await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
    process.stdout.write(JSON.stringify({ action: 'failed', checks, reason: error.message }) + '\n')
    console.error(error.stack)
    process.exitCode = 1
  }
} finally {
  await context.close()
  await browser.close()
  process.stdin.destroy()
}

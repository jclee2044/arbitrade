import assert from 'node:assert/strict'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
import { resolve } from 'node:path'
const output = process.argv[2]
const fixture = JSON.parse(process.argv[3])
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } })
const errors = []
const frames = []
const checks = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('websocket', (socket) => {
  if (new URL(socket.url()).pathname !== '/api/replay') return
  socket.on('framereceived', ({ payload }) => {
    const message = JSON.parse(payload.toString())
    if (message.type === 'snapshot') frames.push(message)
  })
})
async function until(test) {
  for (let i = 0; i < 100; i++) {
    if (await test()) return
    await new Promise((done) => setTimeout(done, 100))
  }
  throw new Error('Timed out waiting for SMA UI')
}
async function step(position) {
  await page.getByRole('button', { name: 'Next observation', exact: true }).click()
  await until(async () => frames.at(-1)?.replay.position === position &&
    (await page.locator('#replay-status').textContent()).startsWith(`${position} /`))
  return frames.at(-1)
}
async function inspect(row) {
  await page.locator('#candle-time').selectOption(String(Date.parse(row.timestamp) / 1000))
  const expected = [row.short === null ? 'Unavailable' : String(row.short),
    row.long === null ? 'Unavailable' : String(row.long), row.signal || 'None']
  await until(async () => JSON.stringify(await page.locator('.sma-values dd').allTextContents()) === JSON.stringify(expected))
}
try {
  await page.goto('http://127.0.0.1:15173', { waitUntil: 'networkidle' })
  await page.getByRole('tab', { name: 'Signals', exact: true }).click()
 await page.getByText('Crossover windows', {exact:true}).click()
  await page.locator('.feed-details summary').click()
  await page.getByText('Feed: disabled', { exact: false }).waitFor()
  // Server validation is independent of native input validation.
  for (const [short, long] of [['0', '3'], ['2', '2'], ['1.5', '3']]) {
    const response = await page.request.get(`http://127.0.0.1:15173/api/history?include_status=true&short_window=${short}&long_window=${long}`)
    assert.equal(response.status(), 422)
  }
  await page.locator('#sma-short').fill('0')
  assert.equal(await page.locator('#sma-short').evaluate((input) => input.checkValidity()), false)
  await page.locator('#sma-short').fill('1.5')
  assert.equal(await page.locator('#sma-short').evaluate((input) => input.checkValidity()), false)
  await page.locator('#sma-short').fill('3')
  await page.locator('#sma-long').fill('3')
  await page.getByRole('button', { name: 'Apply SMA windows', exact: true }).click()
  await page.getByRole('alert').filter({ hasText: 'short smaller than long' }).waitFor()
  await page.locator('#sma-short').fill('2')
  await page.locator('#sma-long').fill('3')
  await page.getByRole('button', { name: 'Apply SMA windows', exact: true }).click()
  await until(async () => (await page.locator('.pair-caption').textContent()).includes('SMA 2 and SMA 3'))
  checks.push('UI and HTTP reject zero, fractional and unordered windows; user applies 2/3')
  const params = new URLSearchParams({ source: 'observations', include_status: 'true', as_of: fixture.end,
    short_window: '2', long_window: '3' })
  const response = await page.request.get(`http://127.0.0.1:15173/api/history?${params}`)
  assert.equal(response.status(), 200)
  const batch = (await response.json()).moving_averages.rows
  assert.deepEqual(batch, fixture.expected)
  checks.push('Batch Python result matches all seven hand-calculated rows including warm-up gaps')
  await page.getByText('Selected candle values',{exact:true}).click()
  await inspect(batch.at(-1))
  await until(async () => await page.locator('.sma-crossovers li').count() === 2)
  checks.push('Live WebSocket with custom 2/3 windows displays the same completed-history averages and signals with Yahoo off')
  await page.locator('#mode').selectOption('replay')
  await until(() => frames.at(-1)?.replay.position === 0)
  await page.locator('#replay-start').fill(fixture.start)
  await page.locator('#replay-end').fill(fixture.end)
  frames.length = 0
  await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
  await until(() => frames.at(-1)?.replay.position === 0)
  const observed = []
  for (let count = 1; count <= 6; count++) {
    const frame = await step(count)
    assert.deepEqual(frame.moving_averages.rows, batch.slice(0, count))
    for (const row of frame.moving_averages.rows) await inspect(row)
    observed.push(frame.moving_averages.rows)
  }
  const forming = await step(7)
  assert.deepEqual(forming.moving_averages.rows.slice(0, -1), batch.slice(0, -1))
  assert.deepEqual(forming.moving_averages.rows.at(-1), { timestamp: batch.at(-1).timestamp, short: null, long: null, signal: null })
  await inspect(forming.moving_averages.rows.at(-1))
  assert.equal(await page.locator('.sma-crossovers li').count(), 1)
  await page.locator('.chart').screenshot({ path: resolve(output, 'forming-no-down.png') })
  const final = await step(8)
  assert.deepEqual(final.moving_averages.rows, batch)
  for (const row of batch) await inspect(row)
  await page.getByText('Source: Replay · CONSTRUCTED test_data=true', { exact: false }).waitFor()
  const signals = await page.locator('.sma-crossovers li').allTextContents()
  assert.equal(signals.length, 2)
  assert.match(signals[0], /Downward.*15:06.*Short 4.*Long 9/)
  assert.match(signals[1], /Upward.*15:04.*Short 16.*Long 13/)
  await page.locator('.sma-crossovers').getByRole('button', { name: /Upward.*15:04/ }).click()
  assert.equal(await page.locator('#candle-time').inputValue(), String(Date.parse(batch.find(row => row.signal === 'up').timestamp) / 1000))
  assert.equal(await page.getByRole('alert').count(), 0)
  await page.locator('.chart').screenshot({ path: resolve(output, 'two-crossovers.png') })
  await page.screenshot({ path: resolve(output, 'reference-desktop.png'), fullPage: true })
  checks.push('Every replay prefix and visible inspector matches batch; forming seventh candle has no confirmed down signal')
  checks.push('Final repeated receipt closes seventh candle: upward at 16/13 and downward at 4/9; two marker entries')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(output, 'reference-mobile.png'), fullPage: true })
  const box = await page.locator('.chart').boundingBox()
  assert(box.x >= 0 && box.x + box.width <= 391)
  // Interval change must recompute, without carrying 1m averages or markers.
  await page.locator('[data-frame="5m"]').click()
  await until(() => frames.at(-1)?.interval === '5m' && frames.at(-1)?.replay.position === 0)
  assert.equal(await page.locator('.sma-crossovers li').count(), 0)
  await page.getByRole('button', { name: 'Play replay', exact: true }).click()
  await until(() => frames.at(-1)?.interval === '5m' && frames.at(-1)?.replay.done)
  assert(frames.at(-1).moving_averages.rows.every((row) => row.long === null && row.signal === null))
  checks.push('Mobile chart fits; 5m starts fresh and has no borrowed 1m crossovers')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks, batch, completed_replay_prefixes: observed,
    forming: forming.moving_averages.rows, final: final.moving_averages.rows, signals }))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close()
}

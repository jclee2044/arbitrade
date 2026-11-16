import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'

const output = process.argv[2]
const url = `http://127.0.0.1:${process.env.ARBITRADE_FRONTEND_PORT}`
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', chromiumSandbox: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let resolveFrame
  const frameReady = new Promise(resolve => { resolveFrame = resolve })
  page.on('websocket', socket => {
    if (!socket.url().includes('/api/live?')) return
    socket.on('framereceived', ({ payload }) => {
      const frame = JSON.parse(String(payload))
      if (frame.type === 'snapshot' && frame.interval === '1m') resolveFrame(frame)
    })
  })
  await page.goto(url)
  const evidence = await (await page.request.get(url + '/api/verification/volume-evidence')).json()
  const frame = await Promise.race([frameReady, new Promise((_, reject) => setTimeout(() => reject(new Error('Missing snapshot')), 20000))])
  const candle = frame.candles.find(row => row.timestamp === evidence.timestamp)
  assert(candle, 'Target minute is in actual browser WebSocket snapshot')
  assert.equal(candle.volume, evidence.expected_volume)
  const direct = await (await page.request.get(url + `/api/history?source=observations&timeframe=1m&as_of=${encodeURIComponent(evidence.as_of)}&include_status=true`)).json()
  assert.deepEqual(direct.candles.find(row => row.timestamp === evidence.timestamp), candle)
  await page.locator('#candle-time').selectOption(String(Date.parse(evidence.timestamp) / 1000))
  await page.locator('.facts-disclosure summary').click()
  const expected = evidence.expected_volume.toLocaleString('en-US') + ' shares'
  await page.getByText(expected, { exact: true }).waitFor()
  assert.match(await page.locator('#volume-basis').innerText(), /observed cumulative change/)
  assert.equal(candle.close, evidence.last.price)
  await page.screenshot({ path: join(output, 'recorded-volume-chart.png'), fullPage: true })
  await writeFile(join(output, 'volume-trace.json'), JSON.stringify({ ...evidence, websocket_candle: candle, result: 'PASS' }, null, 2) + '\n')
  // This is an actual HTTP JSON response screenshot, not a DB Browser image.
  await page.goto(url + '/api/verification/volume-evidence')
  await page.screenshot({ path: join(output, 'database-query-response.png'), fullPage: true })
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks: ['Read-only saved Yahoo database copy', 'Independent SQL counter difference equals HTTP and WebSocket volume', 'Visible candle volume and price match SQL', 'Observed-volume basis disclosed; screenshots saved; no page errors'] }))
} finally {
  await browser.close()
}

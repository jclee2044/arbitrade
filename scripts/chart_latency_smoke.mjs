import assert from 'node:assert/strict'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'

const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', chromiumSandbox: true })
try {
  const page = await browser.newPage()
  await page.addInitScript(() => {
    const NativeSocket = window.WebSocket
    window.WebSocket = class extends NativeSocket {
      constructor(url, ...args) {
        super(url, ...args)
        if (String(url).includes('/api/live?')) window.chartSocket = this
      }
    }
  })
  await page.goto('http://127.0.0.1:' + process.env.ARBITRADE_FRONTEND_PORT)
  const count = n => page.waitForFunction(n => document.querySelectorAll('#candle-time option').length === n, n)
  await count(256)
  const days = page.locator('#history-day')
  await days.selectOption({ index: 0 })
  await count(360)
  await page.evaluate(() => window.chartSocket.close())
  await page.waitForFunction(() => document.querySelector('#market-status')?.textContent === 'Connection lost')
  assert.equal(await page.locator('#candle-time option').count(), 360)
  await page.waitForFunction(() => window.chartSocket.readyState === 1 && window.chartSocket.url.includes('oldest='))
  await page.evaluate(() => new Promise(resolve => window.chartSocket.addEventListener('message', resolve, { once: true })))
  await count(360)
  console.log(JSON.stringify({ checks: ['256 recent candles, 360 after older-day selection, all 360 retained during disconnect and after reconnect'] }))
} finally {
  await browser.close()
}

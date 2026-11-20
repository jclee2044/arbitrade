import { candleCount } from './chart-browser.mjs'
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
  const count = n => page.waitForFunction(n => document.querySelector('.market-column')?.__vueParentComponent?.props.market.candles.length === n, n)
  await count(256)
  const box = await page.locator('.chart').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + 100)
  await page.mouse.wheel(-1800, 0)
  await count(360)
  await page.evaluate(() => window.chartSocket.close())
  await page.waitForFunction(() => document.querySelector('#transport-status')?.textContent.includes('Disconnected from FastAPI'))
  assert.equal(await candleCount(page), 360)
  await page.waitForFunction(() => window.chartSocket.readyState === 1 && window.chartSocket.url.includes('oldest='))
  await page.evaluate(() => new Promise(resolve => window.chartSocket.addEventListener('message', resolve, { once: true })))
  await count(360)
  console.log(JSON.stringify({ checks: ['256 recent candles, 360 after panning toward older candles, all 360 retained during disconnect and after reconnect'] }))
} finally {
  await browser.close()
}

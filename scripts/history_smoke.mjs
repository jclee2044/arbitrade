import { candleCount, hoverCandle } from './chart-browser.mjs'
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output = process.argv[2], checks = [], errors = []
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } })
page.on('pageerror', e => errors.push(e.message))
const button = name => page.getByRole('button', { name, exact: true })
const market = fn => page.locator('.market-column').evaluate((el, source) => {
  const m = el.__vueParentComponent.props.market
  return Function('m', `return (${source})(m)`)(m)
}, fn.toString())
const showNovember10 = () => market(m => {
  const first = m.candles.findIndex(c => c.timestamp.startsWith('2026-11-10'))
  m.drawingAxes().scale.setVisibleLogicalRange({ from: first, to: first + 110 })
})
async function visibleClose(close) {
  await until(async () => await market(m => m.latest?.close) === close)
  const card = await hoverCandle(page)
  await card.getByText(close.toLocaleString('en-US', { style: 'currency', currency: 'USD' }), { exact: true }).first().waitFor()
}
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (await fn()) return
    await new Promise(r => setTimeout(r, 100))
  }
  throw Error('Timed out waiting for chart')
}
try {
  await page.goto(`http://127.0.0.1:${process.env.ARBITRADE_FRONTEND_PORT}`, { waitUntil: 'networkidle' })
  await until(async () => await candleCount(page) === 256)
  const initial = await market(m => m.visibleRange())
  const chart = page.locator('.chart')
  const initialBox = await chart.boundingBox()
  await page.mouse.move(initialBox.x + initialBox.width / 2, initialBox.y + 100)
  await page.mouse.wheel(-1800, 0)
  await until(async () => await candleCount(page) === 360)
  await page.mouse.click(initialBox.x + initialBox.width / 2, initialBox.y + 100)
  assert((await market(m => m.visibleRange())).from < initial.from)
  checks.push('Panning toward older candles pages in earlier history')
  await showNovember10()
  const before = await market(m => m.visibleRange())
  const response = await page.request.post(`http://127.0.0.1:${process.env.ARBITRADE_BACKEND_PORT}/fixture/rollover`)
  assert(response.ok())
  await until(async () => await candleCount(page) === 361)
  assert.deepEqual(await market(m => m.visibleRange()), before)
  checks.push('A new streamed candle arrives while earlier-day viewport remains unchanged')
  const gestureBox = await page.locator('.chart').boundingBox()
  await page.mouse.move(gestureBox.x + gestureBox.width * 0.45, gestureBox.y + 100)
  const span = () => market(m => {
    const r = m.visibleRange()
    return m.candles.findIndex(c => c.time === r.to) - m.candles.findIndex(c => c.time === r.from)
  })
  const originalSpan = await span()
  await page.mouse.wheel(0, 20)
  await until(async () => await span() > originalSpan * 1.15)
  const zoomSamples = [await span()]
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(100)
    zoomSamples.push(await span())
  }
  assert(zoomSamples[3] > zoomSamples[0] + 2, 'Zoom must continue after release')
  assert(zoomSamples[3] - zoomSamples[0] > zoomSamples[8] - zoomSamples[5], 'Zoom must decelerate')
  assert(zoomSamples[8] > zoomSamples[5] + 2, 'Zoom should retain a noticeable longer release tail')
  await page.waitForTimeout(2200)
  const settled = await span()
  await page.waitForTimeout(200)
  assert.equal(await span(), settled, 'Zoom must stop')
  await page.mouse.wheel(0, -20)
  await until(async () => await span() < settled * 0.85)
  // A new pointer input cancels an active release tail immediately.
  await page.mouse.click(gestureBox.x + gestureBox.width * 0.45, gestureBox.y + 100)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  const resetRange = await market(m => m.visibleRange())
  await page.waitForTimeout(500)
  assert.deepEqual(await market(m => m.visibleRange()), resetRange)
  const pinch = deltaY => page.locator('.chart').dispatchEvent('wheel', {
    deltaY, ctrlKey: true, clientX: gestureBox.x + gestureBox.width * 0.45,
    clientY: gestureBox.y + 100, bubbles: true, cancelable: true,
  })
  const beforePinch = await span()
  await pinch(-20)
  await until(async () => await span() < beforePinch * 0.85)
  await pinch(20)
  await until(async () => await span() > beforePinch * 0.95)
  assert.equal(await page.evaluate(() => window.visualViewport.scale), 1)
  await showNovember10()
  const startIndex = () => market(m => {
    const r = m.visibleRange()
    return m.candles.findIndex(c => c.time === r.from)
  })
  await page.mouse.wheel(90, 0)
  const panSamples = [await startIndex()]
  for (let i = 0; i < 8; i++) {
    await page.waitForTimeout(100)
    panSamples.push(await startIndex())
  }
  assert(panSamples[3] > panSamples[0], 'Scroll must continue after release')
  assert(panSamples[3] - panSamples[0] > panSamples[8] - panSamples[5], 'Scroll must decelerate')
  assert(panSamples[8] > panSamples[5] + 2, 'Scrolling should retain a noticeable longer release tail')
  await page.waitForTimeout(2200)
  const panSettled = await startIndex()
  await page.waitForTimeout(200)
  assert.equal(await startIndex(), panSettled, 'Scroll must stop')
  checks.push({ zoom_release_samples: zoomSamples, scroll_release_samples: panSamples,
    result: 'More sensitive zoom; zoom and horizontal scroll continue after release, decelerate, and stop. New pointer input cancels momentum; reverse pinch stays responsive.' })
  await market(m => m.drawingAxes().scale.scrollToRealTime())
  await until(async () => (await market(m => m.visibleRange())).to >= Date.parse('2026-11-11T17:01Z') / 1000)
  const tail = await market(m => m.visibleRange())
  const box = await page.locator('.chart').boundingBox()
  await page.mouse.move(box.x + box.width * 0.25, box.y + 100)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.85, box.y + 100, { steps: 20 })
  await page.mouse.up()
  await until(async () => (await market(m => m.visibleRange())).to < tail.to)
  const dragRelease = await market(m => m.visibleRange())
  await page.waitForTimeout(180)
  const dragCoast = await market(m => m.visibleRange())
  assert(dragCoast.from < dragRelease.from, 'A quick mouse drag must coast after release')
  checks.push('Dragging right scrolls into older candles and coasts after release')
  // Measure rendered candle height, rather than adding chart-only testing APIs.
  await showNovember10()
  await page.waitForTimeout(100)
  const candleHeight = () => page.locator('.chart').evaluate(host => {
    let low = Infinity, high = -Infinity
    const bounds = host.getBoundingClientRect()
    for (const canvas of host.querySelectorAll('canvas')) {
      const rect = canvas.getBoundingClientRect()
      if (rect.width < bounds.width / 2 || rect.height < bounds.height / 2) continue
      const ctx = canvas.getContext('2d'), pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        const i = (y * canvas.width + x) * 4
        if (pixels[i+3] > 0 && ((pixels[i] === 8 && pixels[i+1] === 76 && pixels[i+2] === 61) ||
            (pixels[i] === 104 && pixels[i+1] === 45 && pixels[i+2] === 64))) {
          low = Math.min(low, y * rect.height / canvas.height)
          high = Math.max(high, y * rect.height / canvas.height)
        }
      }
    }
    return high - low
  })
  const axisBox = await page.locator('.chart').boundingBox()
  const axisX = axisBox.x + axisBox.width - 20, axisY = axisBox.y + 160
  const verticalBefore = await candleHeight()
  assert(verticalBefore > 30)
  const horizontalBefore = await market(m => m.visibleRange())
  await page.mouse.move(axisX, axisY)
  await page.mouse.down()
  await page.mouse.move(axisX, axisY + 30, { steps: 5 })
  await page.waitForTimeout(100)
  const verticalCompressed = await candleHeight()
  assert(verticalCompressed < verticalBefore * 0.8, 'Small price-axis drag should compress candles noticeably')
  await page.mouse.move(axisX, axisY - 20, { steps: 5 })
  await page.waitForTimeout(100)
  const verticalExpanded = await candleHeight()
  assert(verticalExpanded > verticalBefore * 1.15, 'Reverse price-axis drag should expand candles noticeably')
  await page.mouse.up()
  assert.deepEqual(await market(m => m.visibleRange()), horizontalBefore, 'Price scaling must preserve time range')
  await page.mouse.wheel(0, 20)
  await page.waitForTimeout(100)
  assert(await candleHeight() < verticalExpanded * 0.9, 'Price-axis wheel should scale vertically')
  await page.mouse.dblclick(axisX, axisY)
  await page.waitForTimeout(100)
  assert(Math.abs((await candleHeight()) / verticalBefore - 1) < 0.06, 'Double-click must restore automatic price scaling')
  checks.push({ price_axis_candle_height_px: { before: verticalBefore, drag_down_30px: verticalCompressed, drag_up_20px: verticalExpanded },
    result: 'Sensitive vertical price drag/wheel, unchanged horizontal range, native double-click reset' })
  // Read histogram pixels so the regression covers the visible zero baseline.
  const volumeBars = () => page.locator('.chart').evaluate(host => {
    const bounds = host.getBoundingClientRect()
    for (const canvas of host.querySelectorAll('canvas')) {
      const rect = canvas.getBoundingClientRect()
      if (rect.width < bounds.width / 2 || rect.height < 30 || rect.height > bounds.height / 2) continue
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
      let top = Infinity, bottom = -Infinity
      for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
        const i = (y * canvas.width + x) * 4
        if (pixels[i+3] && ((pixels[i] === 96 && pixels[i+1] === 139 && pixels[i+2] === 120) ||
            (pixels[i] === 163 && pixels[i+1] === 111 && pixels[i+2] === 126))) {
          top = Math.min(top, y)
          bottom = Math.max(bottom, y)
        }
      }
      if (Number.isFinite(top)) return { height: (bottom - top + 1) * rect.height / canvas.height,
        bottomGap: rect.height - (bottom + 1) * rect.height / canvas.height,
        axisY: rect.top + rect.height / 2 }
    }
    throw Error('No visible volume histogram pixels')
  })
  const volumeBefore = await volumeBars()
  const volumeTimeRange = await market(m => m.visibleRange())
  const assertBaseline = bars => assert(bars.bottomGap <= 1, `Volume zero must stay at pane bottom: ${JSON.stringify(bars)}`)
  assertBaseline(volumeBefore)
  await page.mouse.move(axisX, volumeBefore.axisY)
  await page.mouse.wheel(0, 20)
  await page.waitForTimeout(100)
  const volumeCompressed = await volumeBars()
  assertBaseline(volumeCompressed)
  assert(volumeCompressed.height < volumeBefore.height * 0.9, 'Volume wheel must compress bars')
  await page.mouse.wheel(0, -20)
  await page.waitForTimeout(100)
  const volumeExpanded = await volumeBars()
  assertBaseline(volumeExpanded)
  assert(volumeExpanded.height > volumeCompressed.height * 1.1, 'Reverse volume wheel must expand bars')
  await page.mouse.down()
  await page.mouse.move(axisX, volumeBefore.axisY + 30, { steps: 5 })
  await page.mouse.up()
  await page.waitForTimeout(100)
  const volumeDragged = await volumeBars()
  assertBaseline(volumeDragged)
  assert(volumeDragged.height < volumeExpanded.height * 0.8, 'Volume axis drag must compress bars from zero')
  assert.deepEqual(await market(m => m.visibleRange()), volumeTimeRange, 'Volume scaling must preserve time range')
  await page.mouse.dblclick(axisX, volumeBefore.axisY)
  await page.waitForTimeout(100)
  const volumeReset = await volumeBars()
  assertBaseline(volumeReset)
  assert(Math.abs(volumeReset.height / volumeBefore.height - 1) < 0.06, 'Volume reset must restore automatic scaling')
  const priceHeight = await candleHeight()
  await page.mouse.move(axisBox.x + axisBox.width / 2, volumeBefore.axisY)
  await page.mouse.wheel(0, 20)
  await page.waitForTimeout(100)
  const volumePlotCompressed = await volumeBars()
  assertBaseline(volumePlotCompressed)
  assert(volumePlotCompressed.height < volumeReset.height * 0.9, 'Wheel over volume bars must compress only volume')
  assert.deepEqual(await market(m => m.visibleRange()), volumeTimeRange)
  assert.equal(await candleHeight(), priceHeight, 'Volume scrolling must not scale the main price pane')
  await page.mouse.dblclick(axisX, volumeBefore.axisY)
  await page.waitForTimeout(100)
  // Cross numeric/K/M tick-label widths in both directions, including frames
  // between wheel inputs. Resizing the shared axis shifts every bar sideways.
  const plotWidth = () => page.locator('.chart canvas').evaluateAll(canvases =>
    Math.max(...canvases.map(canvas => canvas.getBoundingClientRect().width)))
  const widths = [await plotWidth()]
  for (const delta of [40, -40]) {
    for (let i = 0; i < 24; i++) {
      await page.mouse.move(axisX, volumeBefore.axisY)
      await page.mouse.wheel(0, delta)
      await page.waitForTimeout(35)
      widths.push(await plotWidth())
    }
  }
  assert.equal(new Set(widths).size, 1, `Volume scrolling must preserve plot width: ${widths}`)
  assert.deepEqual(await market(m => m.visibleRange()), volumeTimeRange, 'Repeated volume scrolling must preserve time range')
  await page.mouse.dblclick(axisX, volumeBefore.axisY)
  await page.waitForTimeout(100)
  checks.push({ volume_scroll_plot_widths: [...new Set(widths)], result: 'Repeated volume scrolling preserves horizontal geometry' })
  checks.push({ volume_axis: { before: volumeBefore, compressed: volumeCompressed, expanded: volumeExpanded,
    dragged: volumeDragged, reset: volumeReset, plotScroll: volumePlotCompressed }, result: 'Volume wheel over bars and axis leaves the price and time scales fixed and anchors volume at zero' })
  await page.screenshot({ path: resolve(output, 'history-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Collapse sidebar' }).click()
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.screenshot({ path: resolve(output, 'history-mobile.png'), fullPage: true })
  const ticker = page.getByRole('textbox', { name: 'Ticker', exact: true })
  assert.equal(await ticker.inputValue(), 'AAPL')
  await ticker.fill('bad ticker')
  await ticker.press('Enter')
  assert(await page.getByRole('alert').filter({ hasText: 'Enter a ticker such as MSFT' }).isVisible())
  assert(await page.getByRole('heading', { name: 'AAPL · 1m candles' }).count())
  await ticker.fill(' msft ')
  await ticker.press('Enter')
  await page.getByRole('heading', { name: 'MSFT · 1m candles' }).waitFor()
  await visibleClose(403)
  assert.equal(await ticker.inputValue(), 'MSFT')
  const history = await page.request.get(new URL('/api/history?symbol=MSFT&timeframe=1m&source=observations&calendar=NASDAQ', page.url()).href)
  assert(history.ok())
  const stored = await history.json()
  assert.deepEqual(stored.map(row => [row.close, row.volume]), [[400, null], [403, 15]])
  assert.equal(await candleCount(page), 2)
  await page.locator('[data-frame="5m"]').click()
  await page.getByRole('heading', { name: 'MSFT · 5m candles' }).waitFor()
  await visibleClose(403)
  assert.equal(await candleCount(page), 1)
  await page.locator('#mode').selectOption('replay')
  assert.equal(await ticker.count(), 0)
  await page.locator('#replay-symbol').selectOption('MSFT')
  await button('Load / restart replay').click()
  await button('Next observation').click()
  await visibleClose(400)
  await page.locator('#mode').selectOption('live')
  assert.equal(await ticker.inputValue(), 'MSFT')
  await visibleClose(403)
  await ticker.fill('AAPL')
  await button('Go').click()
  await page.getByRole('heading', { name: 'AAPL · 5m candles' }).waitFor()
  await visibleClose(115)
  checks.push('Ticker validation, lowercase MSFT entry, matching stored candles and volume, timeframe, replay, and Go back to AAPL')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ checks, initial_candles: 256, after_rollover: 361, earlier_viewport: before }))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally { await browser.close() }

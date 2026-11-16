import assert from 'node:assert/strict'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
import { resolve } from 'node:path'
const output = process.argv[2]
const fixture = JSON.parse(process.argv[3])
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const page = await browser.newPage({ viewport: { width: 1400, height: 1200 } })
const errors = [], checks = []
let latest
page.on('pageerror', (error) => errors.push(error.message))
page.on('websocket', (socket) => {
  if (new URL(socket.url()).pathname !== '/api/replay') return
  socket.on('framereceived', ({ payload }) => {
    const message = JSON.parse(payload.toString())
    if (message.type === 'snapshot') latest = message
  })
})
async function until(test) {
  for (let i = 0; i < 100; i++) {
    if (await test()) return
    await new Promise((done) => setTimeout(done, 100))
  }
  throw new Error('Timed out waiting for named indicator UI')
}
const entry = (name) => page.locator('.configured-indicators li').filter({ has: page.locator('strong', { hasText: name }) })
async function expectValue(name, value) {
  await until(async () => (await entry(name).locator('.indicator-value').allTextContents()).join('') === value)
}
async function add(type, name, window) {
  await page.locator('#indicator-type').selectOption(type)
  await page.locator('#indicator-name').fill(name)
  await page.locator('#indicator-window').fill(String(window))
  await page.getByRole('button', { name: 'Add indicator', exact: true }).click()
}
try {
  await page.goto('http://127.0.0.1:15173', { waitUntil: 'networkidle' })
  await page.getByRole('tab', {name:'Indicators', exact:true}).click()
  await page.setViewportSize({ width: 1280, height: 640 })
  await page.locator('.custom-studies > summary').click()
  const rail = page.locator('.study-rail')
  const heading = rail.locator('.rail-heading')
  await rail.evaluate(el => { el.scrollTop = 0 })
  const headingY = (await heading.boundingBox()).y
  const pageY = await page.evaluate(() => window.scrollY)
  await heading.hover()
  await page.mouse.wheel(0, 300)
  await until(() => rail.evaluate(el => el.scrollTop > 0))
  assert.equal((await heading.boundingBox()).y, headingY)
  await rail.evaluate(el => { el.scrollTop = el.scrollHeight })
  await rail.hover()
  await page.mouse.wheel(0, 500)
  await page.waitForTimeout(200)
  assert.equal(await page.evaluate(() => window.scrollY), pageY)
  assert.equal((await heading.boundingBox()).y, headingY)
  checks.push('Wheel over the menu scrolls its content, keeps tabs stationary and contains scrolling at the bottom')
  await page.setViewportSize({ width: 1400, height: 1200 })
  const squares = page.locator('.periods')
  assert.equal(await squares.count(), 12)
  for (const group of await squares.all()) assert.deepEqual(await group.locator('button').allTextContents(), ['10','20','30','50','100','200'])
  const buttonColors = await squares.locator('button').evaluateAll(buttons => [...new Set(buttons.map(button => {
    const style = getComputedStyle(button)
    return style.color + ' on ' + style.backgroundColor
  }))])
  assert.deepEqual(buttonColors, ['rgb(8, 76, 61) on rgb(220, 247, 235)'])
  const ema10 = page.getByRole('button',{name:'EMA 10 · 1m',exact:true})
  await ema10.click()
  await until(async () => await ema10.getAttribute('aria-pressed') === 'true' && await page.locator('.overlay-legend .dashed').filter({hasText:'EMA 10'}).count() === 1)
  await page.locator('.feed-details summary').click()
  await page.getByText('Feed: disabled', { exact: false }).waitFor()
  const catalog = await (await page.request.get('http://127.0.0.1:15173/api/indicators/types')).json()
  assert.deepEqual(catalog.map((type) => type.type), ['sma', 'price_range', 'ema'])
  assert.equal(catalog[1].settings.window.minimum, 1)
  assert.equal(catalog[1].units, 'price difference')
  await page.locator('#candle-time').selectOption(String(Date.parse('2026-11-10T15:02:00Z')/1000))
  await add('price_range', 'Range 2', 2)
  await expectValue('Range 2', '5')
  await add('price_range', 'Range 3', 3)
  await expectValue('Range 2', '5')
  await expectValue('Range 3', '6')
  assert.equal(await page.locator('.configured-indicators li').count(), 2)
  checks.push('User creates Range 2 and Range 3 from API-supplied catalog; third-candle values are 5 and 6')
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('tab', {name:'Indicators', exact:true}).click()
 await page.locator('.custom-studies > summary').click()
  await until(async () => await ema10.getAttribute('aria-pressed') === 'true')
  checks.push('All twelve six-period rows render and the dashed EMA 10 overlay persists after reload')
  await expectValue('Range 2', '5')
  await expectValue('Range 3', '6')
  checks.push('Refresh restores both names, settings and values')
  const before = await (await page.request.get('http://127.0.0.1:15173/api/indicators')).json()
  await add('price_range', 'Range zero', 0)
  await page.getByRole('alert').filter({ hasText: 'Window must be a positive whole number' }).waitFor()
  await expectValue('Range 2', '5')
  await expectValue('Range 3', '6')
  const invalid = await page.request.post('http://127.0.0.1:15173/api/indicators', {
    data: { name: 'Server zero', type: 'price_range', settings: { window: 0 } },
  })
  assert.equal(invalid.status(), 422)
  assert.match((await invalid.json()).detail, /positive whole number/)
  assert.deepEqual(await (await page.request.get('http://127.0.0.1:15173/api/indicators')).json(), before)
  checks.push('Zero window explains error in UI and HTTP; valid indicators/settings remain unchanged')
  await add('sma', 'SMA 2', 2)
  await expectValue('SMA 2', '14')
  await add('ema', 'EMA 2', 2)
  await expectValue('EMA 2', '13.166667')
  assert.equal(await page.getByRole('alert').count(), 0)
  const legendColors = await page.locator('.overlay-legend .study-key').evaluateAll(items => items.map(item => ({
    name: item.textContent, color: getComputedStyle(item, '::before').borderTopColor,
  })))
  for (const item of legendColors.filter(item => /^(EMA|SMA) /.test(item.name))) {
    assert.equal(item.color, item.name.startsWith('EMA') ? 'rgb(200, 117, 25)' : 'rgb(48, 116, 146)')
  }
  for (const kind of ['sma', 'ema']) {
    const colors = await page.locator('.periods[aria-label^="' + kind.toUpperCase() + ' "] button').evaluateAll(buttons =>
      [...new Set(buttons.map(button => button.style.getPropertyValue('--line')))])
    assert.deepEqual(colors, [kind === 'ema' ? '#c87519' : '#307492'])
  }
  // Check rendered canvas colors as well as the legend and preset selection keys.
  const painted = await page.locator('.chart canvas').evaluateAll(canvases => {
    const found = { orange: false, blue: false }
    for (const canvas of canvases) {
      const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
      for (let i = 0; i < data.length; i += 4) {
        if (data[i] === 200 && data[i+1] === 117 && data[i+2] === 25) found.orange = true
        if (data[i] === 48 && data[i+1] === 116 && data[i+2] === 146) found.blue = true
      }
    }
    return found
  })
  assert.deepEqual(painted, { orange: true, blue: true })
  checks.push('EMA presets/custom lines are orange and SMA blue in rendered chart, legend and every interval/period selection key')
  checks.push('SMA created through same catalog/settings interface; third-candle SMA 2 equals 14')
  // HTTP aligns warm-up gaps and values independently for each configuration.
  const params = new URLSearchParams({ source: 'observations', include_status: 'true', as_of: fixture.end })
  const history = await (await page.request.get(`http://127.0.0.1:15173/api/history?${params}`)).json()
  const values = Object.fromEntries(history.indicators.map((item) => [item.name, item.rows.map((row) => row.value)]))
  assert.deepEqual(values, { 'Range 2': [null, 6, 5], 'Range 3': [null, null, 6], 'SMA 2': [null, 13.5, 14], 'EMA 2': [null, 13.5, 13.5 + (13-13.5)*2/3] })
  await page.locator('#candle-time').selectOption(String(Date.parse('2026-11-10T15:00:00Z')/1000))
  await expectValue('Range 2', 'Unavailable')
  await expectValue('Range 3', 'Unavailable')
  await page.locator('#candle-time').selectOption(String(Date.parse('2026-11-10T15:02:00Z')/1000))
  await expectValue('Range 2', '5')
  await page.locator('.chart').screenshot({ path: resolve(output, 'range-lines.png') })
  await page.screenshot({ path: resolve(output, 'saved-indicators-desktop.png'), fullPage: true })
  // Replay must use exactly the visible observation prefix for all named types.
  await page.locator('#mode').selectOption('replay')
  await until(() => latest?.replay.position === 0)
  await page.locator('#replay-start').fill(fixture.start)
  await page.locator('#replay-end').fill(fixture.end)
  latest = null
  await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
  await until(() => latest?.replay.position === 0)
  for (let position = 1; position <= 6; position++) {
    await page.getByRole('button', { name: 'Next observation', exact: true }).click()
    await until(() => latest?.replay.position === position)
    if (position % 2 === 1) {
      assert(latest.indicators.every((item) => item.rows.at(-1).value === null), 'Forming candle must have a gap')
    }
  }
  await expectValue('Range 2', '5')
  await expectValue('Range 3', '6')
  assert.deepEqual(Object.fromEntries(latest.indicators.map((item) => [item.name, item.rows.map((row) => row.value)])), values)
  checks.push('All named indicators use replay-visible completed candles; forming gaps and final batch/replay values agree')
  const position = latest.replay.position
  await page.locator('[data-frame="5m"]').click()
  await until(async () => await page.locator('.configured-indicators li').count() === 0)
  const empty = await (await page.request.get('http://127.0.0.1:15173/api/indicators?symbol=AAPL&timeframe=5m')).json()
  assert.deepEqual(empty, [])
  await page.locator('[data-frame="1m"]').click()
  await until(() => latest?.interval === '1m' && latest?.replay.position === 0)
  assert.equal(latest.indicators.length, 4)
  assert(latest.presets.some(item => item.id === '1m-ema-10'))
  await page.getByRole('button', { name: 'Play replay', exact: true }).click()
  await until(() => latest?.replay.done)
  await expectValue('Range 3', '6')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: resolve(output, 'saved-indicators-mobile.png'), fullPage: true })
  const box = await page.locator('.chart').boundingBox()
  assert(box.x >= 0 && box.x+box.width <= 391)
  await page.locator('.feed-details summary').click()
  await page.getByText('Source: Replay · CONSTRUCTED test_data=true', { exact: false }).waitFor()
  assert.deepEqual(errors, [])
  checks.push('Settings scoped to symbol/timeframe, return on reopening 1m; desktop/mobile render without page errors')
  console.log(JSON.stringify({ checks, values, saved: before, replay_position: position }))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close()
}

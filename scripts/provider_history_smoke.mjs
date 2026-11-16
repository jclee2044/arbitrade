import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output = process.argv[2], checks = [], errors = []
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } })
page.on('pageerror', e => errors.push(e.message))
const market = fn => page.locator('.market-column').evaluate((el, source) => {
  const m = el.__vueParentComponent.props.market
  return Function('m', `return (${source})(m)`)(m)
}, fn.toString())
async function until(fn) {
  for (let i=0;i<100;i++) { if (await fn()) return; await page.waitForTimeout(100) }
  throw Error('Timed out waiting for historical chart')
}
try {
  await page.goto(`http://127.0.0.1:${process.env.ARBITRADE_FRONTEND_PORT}`, { waitUntil: 'networkidle' })
  await until(async () => await page.locator('#candle-time option').count() >= 2)
  const historyCaption = page.getByText(/Three-month window ·/)
  assert.equal(await historyCaption.count(), 0)
  const daily10 = page.getByRole('button', {name:'SMA 10 · 1D', exact:true})
  const minute10 = page.getByRole('button', {name:'SMA 10 · 1m', exact:true})
  await daily10.click()
  await until(async () => await market(m => m.presets.find(i => i.id === '1d-sma-10')?.rows.at(-1)?.value > 0))
  assert.equal(await minute10.getAttribute('aria-pressed'), 'false')
  assert.equal(await market(m => m.timeframe), '1m')
  assert(await page.locator('.overlay-legend').getByText('SMA 10 · 1D', {exact:true}).isVisible())
  const dailyOverlay = await market(m => m.presets.find(i => i.id === '1d-sma-10').rows.at(-1).value)
  await page.locator('[data-frame="1d"]').click()
  await until(async () => await page.locator('#candle-time option').count() >= 60)
  const priorCloses = await market(m => m.candles.slice(-11,-1).map(c=>c.close))
  assert.equal(dailyOverlay, priorCloses.reduce((a,b)=>a+b,0)/10)
  await daily10.click()
  await until(async () => await daily10.getAttribute('aria-pressed') === 'false')
  assert.equal(await page.locator('.overlay-legend').getByText('SMA 10 · 1D', {exact:true}).count(),0)
  checks.push('Daily SMA 10 on a minute chart matches ten completed daily closes and toggles independently')
  const daily = await market(m => ({ count:m.candles.length, first:m.candles[0].timestamp, range:m.visibleRange() }))
  assert.equal(daily.first, '2026-08-12T13:30:00Z')
  assert.equal(daily.range.from, Date.parse(daily.first)/1000)
  assert.equal(await historyCaption.count(), 0)
  await page.locator('#history-day').selectOption('2026-08-12')
  assert.equal(await page.locator('#history-day').inputValue(), '2026-08-12')
  await page.screenshot({ path:resolve(output,'daily.png'), fullPage:true })
  checks.push('D loads three months of daily candles; earliest date is visible and selectable')
  await page.locator('[data-frame="1w"]').click()
  await until(async () => { const n=await page.locator('#candle-time option').count(); return n>=13 && n<=15 })
  const weekly = await market(m => ({count:m.candles.length,first:m.candles[0].timestamp,range:m.visibleRange()}))
  assert.equal(weekly.first,'2026-08-10T13:30:00Z')
  assert.equal(weekly.range.from,Date.parse(weekly.first)/1000)
  assert.equal(await historyCaption.count(), 0)
  await page.screenshot({path:resolve(output,'weekly.png'),fullPage:true})
  checks.push('W loads three months of aggregated weekly candles and initially fits the full range')
  const cachePath = process.env.ARBITRADE_DATABASE.replace(/\.sqlite3$/,'.history.json')
  const cached = JSON.parse(readFileSync(cachePath,'utf8'))
  assert(cached.rows.length>=125)
  const oldFetch = cached.fetched_at
  await page.request.post(`http://127.0.0.1:${process.env.ARBITRADE_BACKEND_PORT}/fixture/history-failure`)
  await until(async () => await page.getByRole('status').filter({hasText:'Cached history; download retry pending'}).isVisible())
  assert.equal(await page.locator('#candle-time option').count(),weekly.count)
  assert.equal(JSON.parse(readFileSync(cachePath,'utf8')).fetched_at,oldFetch)
  checks.push('Provider outage preserves visible history and stored cache, and reports automatic retry')
  await page.setViewportSize({width:390,height:844})
  await page.locator('[data-frame="1d"]').click()
  await until(async () => await page.locator('#candle-time option').count() === daily.count)
  await page.waitForTimeout(300)
  assert.equal((await market(m=>m.visibleRange())).from,Date.parse(daily.first)/1000)
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))
  await page.screenshot({path:resolve(output,'mobile.png'),fullPage:true})
  for (const frame of ['1mo', '1h', '30m', '15m', '5m', '1m']) {
    await page.locator(`[data-frame="${frame}"]`).click()
    const first = frame === '1mo' ? '2026-08-03' : '2026-08-12'
    await until(async () => await page.locator(`#history-day option[value="${first}"]`).count() > 0)
    await page.locator('#history-day').selectOption(first)
    assert.equal(await page.locator('#history-day').inputValue(), first)
  }
  checks.push('Monthly and all five intraday charts allow navigation to the earliest fixture period')
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({checks,daily,weekly,cache_rows:cached.rows.length,errors}))
} catch(error) {
  await page.screenshot({path:resolve(output,'failure.png'),fullPage:true})
  throw error
} finally { await browser.close() }

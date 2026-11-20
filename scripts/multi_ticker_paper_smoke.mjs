import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'

const output = process.argv[2]
const backend = `http://127.0.0.1:${process.env.ARBITRADE_BACKEND_PORT}`
const frontend = `http://127.0.0.1:${process.env.ARBITRADE_FRONTEND_PORT}`
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, chromiumSandbox: true })
const db = new DatabaseSync(process.env.ARBITRADE_CONFIG_DATABASE, { readOnly: true })
const errors = [], checks = []
let page

function order(symbol, side = 'buy') {
  return db.prepare("SELECT * FROM paper_orders WHERE account_id='live' AND symbol=? AND side=? ORDER BY id DESC LIMIT 1").get(symbol, side)
}
function fills() {
  return db.prepare("SELECT o.symbol,f.quantity,f.price FROM paper_fills f JOIN paper_orders o ON o.id=f.order_id WHERE o.account_id='live' ORDER BY f.id")
    .all().map(row => [row.symbol, row.quantity, row.price])
}
function valuation(symbol) {
  return db.prepare("SELECT price,realized,unrealized FROM paper_pnl_history WHERE account_id='live' AND symbol=? ORDER BY id DESC LIMIT 1").get(symbol)
}
async function until(test, description) {
  for (let i = 0; i < 100; i++) {
    if (await test()) return
    await new Promise(done => setTimeout(done, 100))
  }
  throw Error(description)
}
async function subscriptions() {
  const response = await fetch(backend + '/fixture/subscriptions')
  assert(response.ok)
  return response.json()
}
async function quote(time, symbol, price, currency = 'USD') {
  const query = new URLSearchParams({ timestamp: `2026-11-10T15:${time}Z` })
  if (symbol) {
    query.set('symbol', symbol)
    query.set('price', price)
    query.set('currency', currency)
  }
  const response = await fetch(backend + '/fixture/market?' + query, { method: 'POST' })
  assert.equal(response.status, 200)
}
const button = name => page.getByRole('button', { name, exact: true })
async function openDesk() {
  page = await browser.newPage({ viewport: { width: 1440, height: 1200 } })
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(frontend, { waitUntil: 'networkidle' })
  await button('Trade').click()
  await page.locator('#paper-cash').waitFor()
}
async function select(symbol) {
  const input = page.getByRole('textbox', { name: 'Ticker', exact: true })
  await input.fill(symbol)
  await input.press('Enter')
  await page.getByRole('heading', { name: `${symbol} · 1m candles` }).waitFor()
  await until(async () => (await subscriptions()).upstream.includes(symbol), `No ${symbol} subscription`)
}
async function submit(label, quantity, symbol, side) {
  if (quantity) await page.locator('#paper-quantity').fill(String(quantity))
  await button(label).click()
  await page.locator('#paper-result').filter({ hasText: `${symbol} order accepted · pending` }).waitFor()
  assert.equal(order(symbol, side).status, 'pending')
}
async function expectText(id, value) {
  await until(async () => await page.locator(id).textContent() === value, `${id} did not display ${value}`)
}

try {
  assert.equal(order('IBM').status, 'pending')
  await until(async () => {
    const streams = await subscriptions()
    return streams.paper.includes('IBM') && streams.upstream.includes('IBM') && !streams.viewers.IBM
  }, 'Startup did not subscribe to the durable IBM order')
  checks.push('Startup restores the feed for an existing pending order without a chart')

  await openDesk()
  await submit('Buy shares', 1, 'AAPL', 'buy')
  await quote('00:10', 'AAPL', 100)
  await expectText('#paper-cash', '$900.00')
  await select('MSFT')
  await submit('Buy shares', 2, 'MSFT', 'buy')
  await select('AAPL')
  await until(async () => {
    const streams = await subscriptions()
    return streams.paper.includes('MSFT') && streams.upstream.includes('MSFT') && !streams.viewers.MSFT
  }, 'The pending MSFT order did not keep the feed after switching charts')
  await page.close()
  page = null

  await quote('00:20', 'AAPL', 105)
  await quote('00:25', 'MSFT', 300, 'CAD')
  await until(() => db.prepare("SELECT last_receipt_id FROM paper_accounts WHERE id='live'").get().last_receipt_id >= 3,
    'The background broker did not consume the AAPL and non-USD receipts')
  assert.equal(order('MSFT').status, 'pending')
  assert.deepEqual(fills(), [['AAPL', 1, '100']])
  await quote('00:30', 'MSFT', 400)
  await until(() => order('MSFT').status === 'filled', 'The background broker did not fill MSFT')
  await quote('00:40', 'MSFT', 410)
  await quote('00:45', 'MSFT', 999, 'CAD')
  await until(() => db.prepare("SELECT last_receipt_id FROM paper_accounts WHERE id='live'").get().last_receipt_id >= 6,
    'The background broker did not consume the later MSFT receipts')
  await quote('01:00')
  await until(() => valuation('MSFT').unrealized === '20', 'The background broker did not mark MSFT at $410')
  assert.deepEqual({ ...valuation('AAPL') }, { price: '105', realized: '0', unrealized: '5' })
  assert.deepEqual({ ...valuation('MSFT') }, { price: '410', realized: '0', unrealized: '20' })
  assert.deepEqual(fills(), [['AAPL', 1, '100'], ['MSFT', 2, '400']])
  checks.push('AAPL and non-USD MSFT quotes left MSFT pending. With the browser page closed, MSFT filled at $400 USD and marked at $410 while AAPL marked at $105')

  await openDesk()
  await expectText('#paper-cash', '$100.00')
  const positions = page.getByRole('region', { name: 'Open positions' })
  assert.deepEqual(await positions.locator('tbody tr').allTextContents(), ['AAPL1$105.00$5.00', 'MSFT2$410.00$20.00'])
  assert(await positions.evaluate(region => region.scrollWidth <= region.clientWidth))
  await select('MSFT')
  await expectText('#paper-shares', '2')
  await expectText('#pnl-unrealized', '$20.00')
  await submit('Sell shares', 1, 'MSFT', 'sell')
  await quote('01:10', 'MSFT', 415)
  await expectText('#pnl-realized', '$15.00')
  await quote('01:40', 'MSFT', 410)
  await quote('02:00')
  await expectText('#pnl-total', '$25.00')
  assert.deepEqual({ ...valuation('MSFT') }, { price: '410', realized: '15', unrealized: '10' })
  await page.locator('.paper-trading').screenshot({ path: resolve(output, 'msft-paper-pnl.png') })
  await submit('Close position', null, 'MSFT', 'close')
  await quote('02:10', 'MSFT', 412)
  await expectText('#pnl-realized', '$27.00')
  assert.deepEqual(fills(), [['AAPL', 1, '100'], ['MSFT', 2, '400'], ['MSFT', 1, '415'], ['MSFT', 1, '412']])
  await select('AAPL')
  await until(async () => !(await subscriptions()).upstream.includes('MSFT'), 'The flat MSFT position retained its unused feed')
  assert.equal(await positions.locator('tbody tr').textContent(), 'AAPL1$105.00$5.00')
  checks.push('The AAPL view showed both open positions. MSFT partial sale and next candle produced $15 realized and $10 unrealized; closing MSFT yielded $27 realized and released its unused feed')

  await page.locator('#mode').selectOption('replay')
  await page.locator('#replay-symbol').selectOption('MSFT')
  await button('Load / restart replay').click()
  await expectText('#paper-cash', '$1,000.00')
  const replay = await page.locator('.paper-trading').getAttribute('data-account-id')
  assert(replay.startsWith('replay-'))
  const mismatch = await page.request.post(frontend + '/api/paper/actions', {
    data: { account_id: replay, request_id: 'wrong-symbol', action: 'buy', symbol: 'AAPL', quantity: 1 },
  })
  assert.equal(mismatch.status(), 422)
  await page.locator('#paper-quantity').fill('1')
  await button('Buy shares').click()
  await page.locator('#paper-result').filter({ hasText: 'MSFT order accepted · pending' }).waitFor()
  await button('Next observation').click()
  await page.locator('#replay-status').filter({ hasText: '1 / ' }).waitFor()
  await expectText('#paper-cash', '$1,000.00')
  await button('Next observation').click()
  await expectText('#paper-cash', '$600.00')
  assert.equal(db.prepare("SELECT cash FROM paper_accounts WHERE id='live'").get().cash, '927')
  assert.deepEqual(errors, [])
  checks.push('MSFT Replay rejected a different ticker and filled only on the next eligible revealed receipt in its separate account')
  console.log(JSON.stringify({ checks, fills: fills(), portfolio: { AAPL: valuation('AAPL'), MSFT: valuation('MSFT') } }))
} catch (error) {
  await page?.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  db.close()
  await browser.close()
}

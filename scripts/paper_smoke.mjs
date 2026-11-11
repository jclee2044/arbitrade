import assert from 'node:assert/strict'
import { createInterface } from 'node:readline/promises'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output = process.argv[2]
const lines = createInterface({ input: process.stdin })[Symbol.asyncIterator]()
async function request(action, fields={}) {
  process.stdout.write(JSON.stringify({ action, ...fields })+'\n')
  const reply = await lines.next()
  assert(!reply.done)
  return JSON.parse(reply.value)
}
const browser = await chromium.launch({ executablePath:'/usr/bin/chromium', headless:true, chromiumSandbox:true })
const page = await browser.newPage({ viewport:{ width:1400,height:1100 } })
const errors=[], checks=[]
page.on('pageerror', error=>errors.push(error.message))
const button = name => page.getByRole('button',{ name,exact:true })
async function until(test) {
  for(let index=0;index<150;index++) {
    if(await test()) return
    await new Promise(done=>setTimeout(done,100))
  }
  throw new Error('Timed out waiting for paper UI')
}
async function balances(cash,shares) {
  await until(async()=>await page.locator('#paper-cash').textContent()===cash && await page.locator('#paper-shares').textContent()===String(shares))
}
async function pending() {
  await page.locator('#paper-result').filter({hasText:'pending next eligible'}).waitFor()
  assert.match(await page.locator('.paper-history tbody tr').last().textContent(), /pending/)
}
async function sqlCheck(phase,cash,shares,fills) {
  const sql=await request('snapshot',{phase})
  assert.equal(sql.cash,String(cash)); assert.equal(sql.shares,shares); assert.equal(sql.fills.length,fills)
  return sql
}
try {
  await page.goto('http://127.0.0.1:15173',{waitUntil:'networkidle'})
  await balances('$1,000.00',0)
  await button('Wait').click()
  assert.equal(await page.locator('.paper-history tbody tr').count(),0)
  await page.locator('#paper-quantity').fill('4')
  await button('Buy shares').click(); await pending()
  await balances('$1,000.00',0)
  await sqlCheck('buy-pending',1000,0,0)
  await request('price',{price:100,phase:'supply-100'})
  await balances('$600.00',4)
  const first = await sqlCheck('buy-filled',600,4,1)
  await button('Retry last request').click()
  await page.locator('#paper-result').filter({hasText:'filled'}).waitFor()
  const retried=await sqlCheck('retry-buy',600,4,1)
  assert.equal(retried.orders.length,1); assert.equal(retried.orders[0].id,first.orders[0].id)
  await button('Hold').click()
  assert.equal(await page.locator('.paper-history tbody tr').count(),1)
  checks.push('Wait/hold create no order; buy 4 waits, fills at next observed $100, shows $600/4; same request retry adds no order/fill')
  await page.locator('#paper-quantity').fill('1')
  await button('Sell shares').click(); await pending()
  await request('price',{price:110,phase:'supply-110'})
  await balances('$710.00',3); await sqlCheck('sell-filled',710,3,2)
  await button('Close position').click(); await pending()
  await request('price',{price:105,phase:'supply-105'})
  await balances('$1,025.00',0); await sqlCheck('close-filled',1025,0,3)
  checks.push('Sell 1 at $110 gives $710/3; close remaining 3 at $105 gives $1,025/0')
  await button('Sell shares').click()
  await page.locator('#paper-result').filter({hasText:'Cannot sell more shares than held'}).waitFor()
  const rejected=await sqlCheck('sell-empty-rejected',1025,0,3)
  assert.equal(rejected.orders.length,4); assert.equal(rejected.orders.at(-1).status,'rejected')
  await page.locator('.paper-trading').screenshot({path:resolve(output,'three-fills.png')})
  await request('restart',{phase:'after-backend-restart'})
  await page.reload({waitUntil:'networkidle'})
  await balances('$1,025.00',0)
  await until(async()=>await page.locator('.paper-history tbody tr').count()===4)
  const restarted=await sqlCheck('dashboard-after-restart',1025,0,3)
  assert.equal(restarted.total_fills,3)
  assert.deepEqual(restarted.fills.map(fill=>[fill.quantity,fill.price]),[[4,'100'],[1,'110'],[3,'105']])
  checks.push('Empty-account sale rejected and audited; real backend process restarted; dashboard/SQLite retain exactly 3 fills and $1,025/0')
  await page.getByText('Source: CONSTRUCTED paper fixture',{exact:false}).waitFor()
  await page.locator('.paper-trading').screenshot({path:resolve(output,'after-restart.png')})
  // Saved prices exist, but replay order must remain pending until a next step.
  await page.locator('#mode').selectOption('replay')
  await until(async()=>(await page.locator('.paper-trading').getAttribute('data-account-id'))?.startsWith('replay-'))
  await balances('$1,000.00',0)
  await page.locator('#paper-quantity').fill('11')
  await button('Buy shares').click(); await pending()
  await balances('$1,000.00',0)
  const account=await page.locator('.paper-trading').getAttribute('data-account-id')
  const state=await (await page.request.get(`http://127.0.0.1:15173/api/paper/account?account_id=${account}`)).json()
  assert.equal(state.fills.length,0); assert.equal(state.orders[0].status,'pending')
  await button('Next observation').click()
  await until(async()=>/Insufficient cash at fill/.test(await page.locator('.paper-history tbody tr').last().textContent()))
  await balances('$1,000.00',0)
  const untouched=await sqlCheck('replay-no-live-leak',1025,0,3)
  assert.equal(untouched.total_fills,3)
  checks.push('Replay uses separate $1,000 account: no fill from prices already on disk; next revealed quote triggers cash recheck rejection; live account unchanged')
  await page.setViewportSize({width:390,height:844})
  await page.locator('.paper-trading').screenshot({path:resolve(output,'paper-mobile.png')})
  const box=await page.locator('.paper-trading').boundingBox()
  assert(box.x>=0 && box.x+box.width<=391)
  assert.deepEqual(errors,[])
  checks.push('Desktop/mobile paper panel renders without uncaught browser errors')
  process.stdout.write(JSON.stringify({action:'done',checks})+'\n')
} catch(error) {
  await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{})
  process.stdout.write(JSON.stringify({action:'failed',reason:error.stack})+'\n')
  process.exitCode=1
} finally {
  await browser.close()
  process.stdin.destroy()
}

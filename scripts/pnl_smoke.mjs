import assert from 'node:assert/strict'
import { createInterface } from 'node:readline/promises'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2]
const lines=createInterface({input:process.stdin})[Symbol.asyncIterator]()
async function request(action,fields={}) {
  process.stdout.write(JSON.stringify({action,...fields})+'\n')
  const reply=await lines.next(); assert(!reply.done); return JSON.parse(reply.value)
}
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true})
const page=await browser.newPage({viewport:{width:1500,height:1100}})
const errors=[],checks=[]
page.on('pageerror',failure=>errors.push(failure.message))
const button=name=>page.getByRole('button',{name,exact:true})
const usd=value=>Number(value).toLocaleString('en-US',{style:'currency',currency:'USD'})
const expected=[['600',4,'100','0','0','0'],['600',4,'100','0','40','40'],['710',3,'100','10','30','40'],
  ['710',3,'100','10','-15','-5'],['1025',0,null,'25','0','25']]
async function until(test) {
  for(let i=0;i<150;i++) { if(await test())return; await new Promise(done=>setTimeout(done,100)) }
  throw new Error('Timed out waiting for P&L UI')
}
async function compare(count,phase) {
  await until(async()=>await page.locator('#pnl-history tbody tr').count()===count)
  for(let i=0;i<count;i++) {
    const cells=await page.locator('#pnl-history tbody tr').nth(i).locator('td').allTextContents()
    const [cash,shares,average,realized,unrealized,total]=expected[i]
    assert.deepEqual(cells.slice(2),[usd(cash),String(shares),average===null?'—':usd(average),usd(realized),usd(unrealized),usd(total)])
    assert.match(cells[0],/AAPL.*2026-11-10T15:/)
    assert.match(cells[1],/2026-11-10T15:/)
    assert.match(cells[1],i===1||i===3?/Completed 1m candle close/:/Fill · order/)
  }
  const sql=await request('snapshot',{phase})
  assert.deepEqual(sql.history.map(row=>[row.cash,row.shares,row.average_cost,row.realized,row.unrealized,row.total]),expected.slice(0,count))
  await until(async()=>await page.locator('#pnl-total').textContent()===usd(expected[count-1][5]))
  assert.equal(await page.locator('#paper-cash').textContent(),usd(sql.cash))
  assert.equal(await page.locator('#paper-shares').textContent(),String(sql.shares))
  return sql
}
async function pending() { await page.locator('#paper-result').filter({hasText:'pending next eligible'}).waitFor() }
try {
  await page.goto('http://127.0.0.1:15173',{waitUntil:'networkidle'})
  await page.getByRole('button', { name: 'Paper trading', exact: true }).click()
  await until(async()=>await page.locator('#paper-cash').textContent()==='$1,000.00')
  await page.locator('#paper-quantity').fill('4'); await button('Buy shares').click(); await pending()
  await request('price',{price:100,seconds:10}); await compare(1,'buy')
  await request('price',{price:110,seconds:40})
  await page.request.get('http://127.0.0.1:15173/api/paper/account')
  assert.equal(await page.locator('#pnl-history tbody tr').count(),1,'Forming candle must not create valuation')
  await request('advance',{seconds:60}); await compare(2,'value-110')
  assert.match(await page.locator('#pnl-price').textContent(),/\$110\.00.*Completed 1m candle.*15:01:00/)
  await page.locator('#paper-quantity').fill('1'); await button('Sell shares').click(); await pending()
  await request('price',{price:110,seconds:70}); await compare(3,'partial-sale')
  await request('price',{price:95,seconds:100}); await request('advance',{seconds:120}); await compare(4,'value-95')
  await page.locator('.pnl-panel').screenshot({path:resolve(output,'open-loss.png')})
  await button('Close position').click(); await pending()
  await request('price',{price:105,seconds:130}); await compare(5,'closed')
  await button('Retry last request').click()
  for(let i=0;i<3;i++)await page.request.get('http://127.0.0.1:15173/api/paper/account')
  const before=await compare(5,'before-restart')
  assert.equal(before.fills,3)
  await page.locator('.pnl-panel').screenshot({path:resolve(output,'history-before-restart.png')})
  await button('Back to chart').click()
  await page.locator('.feed-details summary').click()
  await page.getByText('Source: CONSTRUCTED P&L fixture',{exact:false}).waitFor()
  checks.push('All five browser rows equal direct SQLite and reference, including $40, -$5, and final $25; partial sale preserves $100 average')
  checks.push('Forming candle produces no mark; completing 1m candles supplies $110/$95 with source/time; repeated reads/request preserve five events')
  await request('restart',{phase:'after-backend-restart'})
  await page.reload({waitUntil:'networkidle'})
  await page.getByRole('button', { name: 'Paper trading', exact: true }).click()
  const after=await compare(5,'browser-after-restart')
  assert.deepEqual(after.history,before.history)
  assert.equal(after.fills,3)
  await page.locator('.pnl-panel').screenshot({path:resolve(output,'history-after-restart.png')})
  await page.setViewportSize({width:390,height:844})
  await page.locator('.pnl-panel').screenshot({path:resolve(output,'history-mobile.png')})
  const box=await page.locator('.paper-trading').boundingBox()
  assert(box.x>=0 && box.x+box.width<=391)
  assert.deepEqual(errors,[])
  checks.push('Actual backend restart and page reload preserve exact row IDs/amounts/sources, three fills, $1,025/0; mobile table scrolls, no page errors')
  process.stdout.write(JSON.stringify({action:'done',checks})+'\n')
} catch(failure) {
  await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{})
  process.stdout.write(JSON.stringify({action:'failed',reason:failure.stack})+'\n'); process.exitCode=1
} finally { await browser.close(); process.stdin.destroy() }

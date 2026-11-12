import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
import { createInterface } from 'node:readline'
const output=process.argv[2],base='http://127.0.0.1:15173'
const lines=createInterface({input:process.stdin})[Symbol.asyncIterator]()
async function host(action){console.log(JSON.stringify({action}));const {value,done}=await lines.next();if(done)throw Error('Runner closed');return JSON.parse(value)}
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true})
const page=await browser.newPage({viewport:{width:1400,height:1200}}),errors=[],checks=[]
page.on('pageerror',e=>errors.push(e.message))
const button=name=>page.getByRole('button',{name,exact:true})
async function api(path,body){const url=(path.startsWith('/fixture/')?'http://127.0.0.1:18000':base)+path;const r=body===undefined?await page.request.get(url):await page.request.post(url,{data:body});assert(r.ok(),await r.text());return r.json()}
async function until(fn){for(let i=0;i<250;i++){if(await fn())return;await new Promise(done=>setTimeout(done,100))}throw Error('Timed out')}
async function advance(now,price){await api('/fixture/advance',{now,...(price===undefined?{}:{price})})}
async function state(){return api('/api/paper/automation')}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('tab', { name: 'Signals', exact: true }).click()
 await page.getByText('Crossover windows', {exact:true}).click()
 await page.locator('#sma-short').fill('2');await page.locator('#sma-long').fill('3');await button('Apply SMA windows').click()
 await page.getByRole('button', { name: 'Paper trading', exact: true }).click()
 await page.getByRole('button', { name: 'Automation', exact: true }).click()
 await button('Start paper automation').click()
 await until(async()=>(await page.locator('#automation-status').textContent()).includes('enabled'))
 const initial=await state();assert(initial.run.account_id.startsWith('test-'));assert.equal(initial.state.account.cash,'1000');assert.equal(initial.state.fills.length,0)
 await advance('2026-11-10T15:07:10Z',13);await advance('2026-11-10T15:08:10Z',19);await advance('2026-11-10T15:09:00Z')
 // 15:07 also completes after Start: it has no crossover and remains a recorded skip.
 // The first analyzed candle can be that no-signal candle; fixture/model selects buy and Python vetoes it.
 await until(async()=>(await state()).attempts.some(a=>a.candle_timestamp==='2026-11-10T15:08:00+00:00'&&a.status==='pending'))
 let s=await state();const a=s.attempts.find(a=>a.status==='pending');assert.equal(a.signal,'up')
 assert(await page.locator('#automation-preview').evaluate(img=>img.complete&&img.naturalWidth>100))
 await api('/api/paper/automation/attempts/'+a.id+'/apply',{});await advance('2026-11-10T15:09:10Z',20)
 await until(async()=>(await state()).attempts.find(x=>x.id===a.id)?.status==='filled')
 await until(async()=>(await page.locator('#automation-balances').textContent()).includes('920'))
 s=await state();assert.equal(s.state.account.cash,'920');assert.equal(s.state.positions[0].shares,4);assert.equal(s.state.fills.length,1)
 await api('/api/paper/automation/attempts/'+a.id+'/apply',{});assert.equal((await state()).state.fills.length,1)
 assert((await page.locator('#automation-history').textContent()).includes(a.decision_id));assert((await page.locator('#automation-history').textContent()).includes('Fill '))
 await page.locator('.automation-panel').screenshot({path:resolve(output,'approved-fill.png')})
 checks.push('Start uses $1000 disposable test account; up crossover gets fresh chart/analyst/review, duplicate approved application yields exactly one 4x20 fill, cash920/shares4 and linked P&L')
 await advance('2026-11-10T15:09:50Z',1);await advance('2026-11-10T15:10:00Z')
 await until(async()=>(await state()).attempts.some(x=>x.candle_timestamp==='2026-11-10T15:09:00+00:00'&&x.status==='skipped'))
 s=await state();const veto=s.attempts.find(x=>x.candle_timestamp==='2026-11-10T15:09:00+00:00')
 assert.equal(veto.decision.review.reviewer.verdict,'reject_unsupported_signal');assert.equal(s.state.account.cash,'920');assert.equal(s.state.fills.length,1)
 await page.locator('.automation-panel').screenshot({path:resolve(output,'reviewer-veto.png')})
 checks.push('Reviewer veto is visible under decision ID; no extra order/fill/cash/position change')
 await button('Stop paper automation').click();await host('audit')
 await host('restart');await page.reload({waitUntil:'networkidle'})
 await page.getByRole('button', { name: 'Paper trading', exact: true }).click()
 await page.getByRole('button', { name: 'Automation', exact: true }).click()
 await until(async()=>(await page.locator('#automation-status').textContent()).includes('stopped'))
 const restored=await state();assert.equal(restored.state.account.cash,'920');assert.equal(restored.state.fills.length,1)
 const start=await api('/api/paper/automation/start',{account_id:'live',symbol:'AAPL',interval:'1m',short_window:2,long_window:3})
 const duplicate=await api('/api/paper/automation/claim',{run_id:start.run.id,candle_timestamp:a.candle_timestamp})
 assert.equal(duplicate.claimed,false);assert.equal(duplicate.attempt.id,a.id)
 await api('/api/paper/automation/'+start.run.id+'/stop',{})
 checks.push('Actual backend restart keeps decision/fill/P&L/cash; automation stopped, same candle deduplicates under a new Start')
 await page.setViewportSize({width:390,height:844});await page.locator('.automation-panel').screenshot({path:resolve(output,'automation-mobile.png')})
 assert.deepEqual(errors,[])
 await host('audit');console.log(JSON.stringify({action:'done',checks,decision_id:a.decision_id,attempt_id:a.id,veto_id:veto.decision_id}))
}catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});console.log(JSON.stringify({action:'failed',reason:error.stack}));process.exitCode=1}
finally{await browser.close();process.stdin.destroy()}

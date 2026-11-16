import assert from 'node:assert/strict'
import { checkDrawings } from './drawing_smoke.mjs'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2], base='http://127.0.0.1:15173', checks=[], errors=[]
const browser=await chromium.launch({...(process.env.ARBITRADE_CHROMIUM==='playwright'?{}:{executablePath:process.env.ARBITRADE_CHROMIUM || '/usr/bin/chromium'}), headless:true, chromiumSandbox:!process.env.CI})
const page=await browser.newPage({viewport:{width:1400,height:1200},reducedMotion:'reduce'})
page.on('pageerror',e=>errors.push(e.message))
// Browser requests are local only, including WebSockets to Vite/FastAPI.
await page.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort())
const button=name=>page.getByRole('button',{name,exact:true})
async function api(path,body){const url=(path.startsWith('/fixture/')?'http://127.0.0.1:18000':base)+path;const r=body===undefined?await page.request.get(url):await page.request.post(url,{data:body});assert(r.ok(),await r.text());return r.json()}
async function until(fn){for(let i=0;i<250;i++){if(await fn())return;await new Promise(r=>setTimeout(r,100))}throw Error('Timed out waiting for expected UI/state')}
const state=()=>api('/api/paper/automation')
const event=(now,price)=>api('/fixture/event',{now,...(price===undefined?{}:{price})})
const control=body=>api('/fixture/control',body)
const stamp=minute=>`2026-11-10T15:${String(minute).padStart(2,'0')}:00+00:00`
const clock=(minute,seconds=0)=>`2026-11-10T15:${String(minute).padStart(2,'0')}:${String(seconds).padStart(2,'0')}Z`
async function completed(minute,price,scenario='manual',veto=false){
 await control({scenario,veto})
 await event(clock(minute,10),price);await event(clock(minute+1))
 await until(async()=>(await state()).attempts.some(a=>a.candle_timestamp===stamp(minute)&&['pending','filled','skipped','no_order'].includes(a.status)))
 return (await state()).attempts.find(a=>a.candle_timestamp===stamp(minute))
}
async function balances(cash,shares,realized,unrealized){
 const s=await state();assert.equal(s.state.account.cash,cash);assert.equal(s.state.positions[0]?.shares||0,shares)
 if(realized!==undefined){const p=s.state.pnl_summary[0];assert.equal(p.realized,realized);assert.equal(p.unrealized,unrealized)}
 await until(async()=>(await page.locator('#automation-balances').textContent())===`Automation cash: ${cash} · Shares: ${shares}`)
}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('tab', { name: 'Signals', exact: true }).click()
 await page.getByText('Crossover windows', {exact:true}).click()
 await page.locator('#sma-short').fill('2');await page.locator('#sma-long').fill('3');await button('Apply SMA windows').click()
 // Open the recorded session and load every receipt through the real replay WebSocket.
 await page.locator('#mode').selectOption('replay')
 await page.locator('#replay-start').fill('2026-11-10T15:01:00+00:00')
 await page.locator('#replay-end').fill('2026-11-10T15:07:00+00:00')
 await button('Load / restart replay').click();await button('Play replay').click()
 await until(async()=>(await page.locator('#replay-status').textContent()).includes('8 / 8'))
 await page.locator('#candle-time').selectOption(String(Date.parse('2026-11-10T15:04:00Z')/1000))
 await checkDrawings(page, resolve(output, 'drawing-tools.png'))
 checks.push('Trend Line, Freehand, drag-sized ratio previews, locked resizing, contact eraser and drawing undo')
 await page.getByRole('tab', {name:'Indicators', exact:true}).click()
 await page.locator('.custom-studies > summary').click()
 await page.locator('#indicator-type').selectOption('sma');await page.locator('#indicator-name').fill('Smoke SMA');await page.locator('#indicator-window').fill('2');await button('Add indicator').click()
 const entry=page.locator('[data-indicator-name="Smoke SMA"]')
 await until(async()=>(await entry.locator('.indicator-value').textContent())==='16') // (13+19)/2
 await entry.locator('input').fill('3');await entry.getByRole('button',{name:'Save window',exact:true}).click()
 await until(async()=>(await entry.locator('.indicator-value').textContent())==='13') // (7+13+19)/3
 checks.push('Recorded replay: added SMA2=(13+19)/2=16; edited same saved SMA to window3=(7+13+19)/3=13 on 15:04 candle')
 const selectedTime = await page.locator('#candle-time').inputValue()
 await button('Collapse sidebar').click()
 assert.equal(await page.locator('#candle-time').inputValue(), selectedTime)
 await page.locator('.masthead').hover()
 await page.screenshot({path:resolve(output,'trading-desk.png')})
 await button('Expand sidebar').click()
 await page.locator('.configured-indicators').screenshot({path:resolve(output,'sma.png')})
 await page.getByRole('tab', {name:'AI', exact:true}).click()
 await page.getByRole('button', { name: 'Review paper proposal', exact: true }).click()
 await button('Ask about chart').click();await page.locator('#chart-preview').waitFor({state:'visible'})
 const sid=(await page.locator('#snapshot-id').textContent()).replace('Snapshot ID: ','')
 const saved=await api('/api/decision-snapshots/'+sid)
 const account={id:saved.snapshot.account.account_id}
 const before=await api('/api/paper/account?account_id='+account.id)
 const capture=await page.locator('#chart-preview').getAttribute('src');assert(capture.startsWith('data:image/png;base64,'))
 assert(await page.locator('#chart-preview').evaluate(img=>img.complete&&img.naturalWidth>100))
 // Hold the first analysis request until the user has left the AI panel.
 let releaseAnalysis
 const resumeAnalysis=new Promise(resolve=>{releaseAnalysis=resolve})
 await page.route('**/api/decisions',async route=>{await resumeAnalysis;await route.continue()},{times:1})
 const isAnalysis=request=>new URL(request.url()).pathname==='/api/decisions' && request.method()==='POST'
 const analyzed=page.waitForResponse(response=>isAnalysis(response.request()))
 const replayPosition=await page.locator('#replay-status').innerText()
 try {
   await Promise.all([page.waitForRequest(isAnalysis),button('Analyze captured chart').click()])
   await button('Close paper proposal').click()
   assert.equal(await page.locator('#candle-time').inputValue(),selectedTime)
   assert.equal(await page.locator('#replay-status').innerText(),replayPosition)
 } finally { releaseAnalysis() }
 assert((await analyzed).ok())
 await page.getByRole('button', { name: 'Review paper proposal', exact: true }).click()
 await until(async()=>(await page.locator('#decision-status').innerText()).includes('Status: valid'))
 for(const [name,value] of Object.entries({action:'wait',crossover:'up',evidence:'sufficient'}))assert.equal(await page.locator(`[data-answer="${name}"]`).textContent(),`${name}: ${value}`)
 assert.deepEqual((await api('/api/paper/account?account_id='+account.id)).fills,before.fills)
 await page.locator('.decision-result').screenshot({path:resolve(output,'chart-answers.png')})
 const decisionId=(await page.locator('#decision-id').innerText()).replace('Decision ID: ','')
 await button('Discuss this decision').click()
 await until(async()=>await page.locator('#voice-selected').isVisible() && (await page.locator('#voice-selected').innerText()).includes(decisionId))
 assert.equal(await page.locator('#voice-microphone').innerText(),'Mic off')
 await page.getByRole('button', { name: 'Review paper proposal', exact: true }).click()
 assert.equal(await page.locator('#chart-preview').getAttribute('src'),capture)
 await control({scenario:'failure'});await button('Analyze captured chart').click()
 await until(async()=>(await page.locator('#decision-status').textContent()).includes('Status: provider_error'))
 assert.deepEqual((await api('/api/paper/account?account_id='+account.id)).fills,before.fills)
 checks.push('Analysis finishes while viewing Chart; pinned replay selection and progress persist. Saved PNG and decision survive a round trip to Voice. Stub answers and provider failure leave fills unchanged')
 await page.locator('.decision-result').screenshot({path:resolve(output,'provider-failure.png')})
 await control({scenario:'manual'});await page.locator('#mode').selectOption('live')
 await page.getByRole('button', { name: 'Trade', exact: true }).click()
 await page.getByRole('button', { name: 'Automation', exact: true }).click()
 await button('Start paper automation').click();await until(async()=>(await page.locator('#automation-status').textContent()).includes('enabled'))
 const initial=await state();assert.equal(initial.state.account.cash,'1000');assert.equal(initial.state.fills.length,0);assert.equal(initial.state.fees,'0');assert.deepEqual(initial.state.positions,[])
 await button('Trade').click()
 await completed(7,13)
 const buy=await completed(8,19,'buy');assert.equal(buy.signal,'up');assert.equal(buy.status,'pending')
 await event(clock(9,10),100);await until(async()=>(await state()).state.fills.length===1);await balances('600',4,'0','0')
 await page.getByRole('button', { name: 'Trade', exact: true }).click()
 assert.equal(await button('Stop paper automation').isEnabled(), true)
 await api('/api/paper/automation/attempts/'+buy.id+'/apply',{})
 await event(clock(9,10),100) // duplicate receipt/event must not add another fill
 const duplicate=await api('/api/paper/automation/claim',{run_id:initial.run.id,candle_timestamp:buy.candle_timestamp})
 assert.equal(duplicate.claimed,false);assert.equal(duplicate.attempt.id,buy.id);assert.equal((await state()).state.fills.length,1)
 checks.push('Start in browser: clean $1000/zero shares/zero fees; approved buy4 fills at next $100 mark, $600/4; duplicate event, claim and apply add no fill')
 await control({order_size:1,scenario:'sell'});await event(clock(9,50),1);await event(clock(10))
 await until(async()=>(await state()).attempts.some(a=>a.candle_timestamp===stamp(9)&&a.status==='pending'))
 await event(clock(10,10),110);await until(async()=>(await state()).state.fills.length===2);await balances('710',3,'10','30')
 // Finish 15:10 at the fill price. Hold through the intervening non-down candles.
 await control({scenario:'manual'});await event(clock(11))
 await until(async()=>(await state()).attempts.some(a=>a.candle_timestamp===stamp(10)&&a.status==='no_order'))
 await completed(11,1)
 const veto=await completed(12,1,'close',true);assert.equal(veto.status,'skipped');assert.equal(veto.decision.review.reviewer.verdict,'reject_unsupported_signal')
 assert.equal((await state()).state.fills.length,2)
 await until(async()=>(await page.locator('#automation-history').textContent()).includes('reject_unsupported_signal'))
 checks.push('Configured sell1 fills at $110: $710/3, realized10/unrealized30; subsequent down-crossover reviewer veto stays visible and adds no fill')
 await completed(13,200);await completed(14,1)
 const close=await completed(15,1,'close');assert.equal(close.signal,'down');assert.equal(close.status,'pending')
 await event(clock(16,10),105);await until(async()=>(await state()).state.fills.length===3);await balances('1025',0,'25','0')
 await until(async()=>(await page.locator('#automation-pnl').textContent())==='Realized P&L: 25 · Unrealized P&L: 0')
 await page.locator('.automation-panel').screenshot({path:resolve(output,'final-account.png')})
 checks.push('Approved close3 fills at $105: visible cash1025/shares0/realized25/unrealized0; SQLite audited independently by runner')
 await button('Trade').click();await button('Stop automation').click()
 await until(async()=>await page.locator('#automation-status').isVisible() && (await page.locator('#automation-status').innerText()).includes('stopped'))
 const stopped=await state();await event(clock(17),500)
 await page.waitForTimeout(1800)
 const after=await state();assert.equal(after.state.orders.length,3);assert.equal(after.state.fills.length,3);assert.equal(after.attempts.length,stopped.attempts.length)
 checks.push('Stop in browser then deliver another completed candle/mark: no new attempt, order or fill')
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({checks,initial_account:initial.state.account.id,final_account:after.state.account.id,buy_attempt:buy.id,veto_attempt:veto.id,close_attempt:close.id}))
}catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});console.log(JSON.stringify({failure:error.stack,checks}));process.exitCode=1}
finally{await browser.close()}

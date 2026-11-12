import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { writeFile } from 'node:fs/promises'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2],base=process.env.CHART_REVIEW_URL||'http://127.0.0.1:15173'
const live=process.env.CHART_LIVE_CHECK==='1'
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true})
const page=await browser.newPage({viewport:{width:1400,height:1200}}),errors=[],checks=[]
page.on('pageerror',e=>errors.push(e.message))
const button=name=>page.getByRole('button',{name,exact:true})
async function until(fn){for(let i=0;i<300;i++){if(await fn())return;await new Promise(done=>setTimeout(done,100))}throw Error('Timed out')}
try {
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('tab', { name: 'Signals', exact: true }).click()
 await page.getByText('Crossover windows', {exact:true}).click()
 await page.locator('#sma-short').fill('2');await page.locator('#sma-long').fill('3');await button('Apply SMA windows').click()
 await until(async()=>await page.locator('#candle-time option').count()>3)
 let stamp=String(Date.parse('2026-11-10T15:04:00Z')/1000)
 if(live){
   const history=await(await page.request.get(base+'/api/history?source=observations&include_status=true&short_window=2&long_window=3')).json()
   const rows=history.moving_averages.rows
   const chosen=[...rows].reverse().find(r=>r.signal&&r.short!=null&&r.long!=null)||[...rows].reverse().find(r=>r.short!=null&&r.long!=null)
   assert(chosen,'Need completed candle with SMA values');stamp=String(Date.parse(chosen.timestamp)/1000)
 }
 await page.locator('#candle-time').selectOption(stamp)
 await page.getByRole('button', { name: 'Review decision proposal', exact: true }).click()
 await button('Ask about chart').click()
 await page.locator('#chart-preview').waitFor({state:'visible'})
 assert.equal(await page.locator('.decision-result').count(),0)
 const capture=await page.locator('#chart-preview').getAttribute('src')
 assert(capture.startsWith('data:image/png;base64,'))
 assert(await page.locator('#chart-preview').evaluate(img=>img.complete&&img.naturalWidth>100&&img.naturalHeight>100))
 const sid=(await page.locator('#snapshot-id').textContent()).replace('Snapshot ID: ','')
 const saved=await(await page.request.get(base+'/api/decision-snapshots/'+sid)).json()
 assert.equal(Date.parse(saved.snapshot.candle_timestamp)/1000,Number(stamp))
 assert.equal(saved.snapshot.chart.candles.at(-1).timestamp,saved.snapshot.candle.timestamp)
 assert.equal(await page.locator('.chart-question').count(),3)
 assert((await page.locator('#capture-cutoff').textContent()).includes(saved.snapshot.decision_time))
 if(!live){assert.equal(saved.snapshot.indicators.crossover,'up');assert.equal(saved.snapshot.candle.close,19)
   assert(saved.snapshot.chart.candles.some(c=>c.volume===100));assert.equal(saved.snapshot.chart.indicators[0].name,'Range 2')}
 await writeFile(resolve(output,'submitted.png'),Buffer.from(capture.split(',')[1],'base64'))
 await page.locator('.chart-capture').screenshot({path:resolve(output,'preview-and-questions.png')})
 checks.push('Freeze selected cutoff and visible range; chart-only native PNG renders before submission with three exact questions')
 // One backend decision request in live mode; at most one analyst and one reviewer call.
 await button('Analyze captured chart').click()
 await until(async()=>await page.locator('.decision-result').count()===1)
 const id=(await page.locator('#decision-id').textContent()).replace('Decision ID: ','')
 const result=await(await page.request.get(base+'/api/decisions/'+id)).json()
 assert.equal(result.snapshot_id,sid);assert(result.image_analysis.answers)
 for(const [name,answer] of Object.entries(result.image_analysis.answers))assert.equal(await page.locator(`[data-answer="${name}"]`).textContent(),`${name}: ${answer.choice}`)
 const image=await page.request.get(base+result.image_analysis.image_url)
 assert.equal(Buffer.compare(await image.body(),Buffer.from(capture.split(',')[1],'base64')),0)
 assert.equal(await page.locator('#chart-preview').getAttribute('src'),capture)
 await page.locator('.decision-panel').screenshot({path:resolve(output,'answers.png')})
 checks.push('Preview bytes equal retrievable saved PNG; displayed named answers equal durable API result; capture stays frozen')
 if(!live){
   assert.equal(result.status,'valid');assert.equal(result.image_analysis.comparison,'match');assert.equal(result.proposal,'hold')
   for(const expected of ['conflicting_signal','unreadable_image','malformed_answer','timeout']){
     await button('Analyze captured chart').click()
     await until(async()=>(await page.locator('#decision-status').textContent()).includes(`Status: ${expected}`))
     const did=(await page.locator('#decision-id').textContent()).replace('Decision ID: ','')
     const d=await(await page.request.get(base+'/api/decisions/'+did)).json();assert.equal(d.paper_order_eligible,false)
   }
   checks.push('Conflict, unreadable image, missing named answer and provider timeout are distinct saved ineligible results')
   const rejected=await(await page.request.post(base+'/api/decisions',{data:{snapshot_id:sid,capture:{image_url:'data:image/png;base64,!!',manifest:{}}}})).json()
   assert.equal(rejected.status,'invalid_image')
   const swapped=await(await page.request.post(base+'/api/decisions',{data:{snapshot_id:sid,capture:{image_url:capture,manifest:{snapshot_id:'wrong'}}}})).json()
   assert.equal(swapped.status,'snapshot_mismatch')
   await page.setViewportSize({width:390,height:844});await page.locator('.decision-panel').screenshot({path:resolve(output,'mobile.png')})
   const box=await page.locator('#chart-preview').boundingBox();assert(box.x>=0&&box.x+box.width<=391)
 }
 assert.deepEqual(errors,[])
 console.log(JSON.stringify({checks,snapshot_id:sid,decision_id:id,result,snapshot:saved,live}))
} catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser.close()}

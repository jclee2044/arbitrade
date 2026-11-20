import { pinCandle } from './chart-browser.mjs'
import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2],base='http://127.0.0.1:15173'
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true})
const page=await browser.newPage({viewport:{width:1400,height:1200}}),errors=[],checks=[],decisions=[]
page.on('pageerror',e=>errors.push(e.message))
const button=name=>page.getByRole('button',{name,exact:true})
async function until(fn){for(let i=0;i<150;i++){if(await fn())return;await new Promise(done=>setTimeout(done,100))}throw Error('Timed out waiting for review')}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('tab', { name: 'Signals', exact: true }).click()
 await page.getByText('Crossover windows', {exact:true}).click()
 await page.locator('#sma-short').fill('2');await page.locator('#sma-long').fill('3');await button('Apply SMA windows').click()
 await pinCandle(page, '2026-11-10T15:04:00Z')
 await page.getByRole('tab', {name:'AI', exact:true}).click()
 await page.getByRole('button', { name: 'Review paper proposal', exact: true }).click()
 await button('Freeze selected candle').click();await page.locator('#snapshot-id').waitFor()
 const sid=(await page.locator('#snapshot-id').textContent()).replace('Snapshot ID: ','')
 const saved=await(await page.request.get(base+'/api/decision-snapshots/'+sid)).json()
 assert.equal(saved.snapshot.account.order_size,100);assert.equal(saved.snapshot.indicators.crossover,'up')
 for(const [index,expected] of ['valid','review_rejected','invalid_proposal','review_timeout','review_malformed_answer'].entries()){
  await button('Request model proposal').click()
  await until(async()=>{const text=await page.locator('#decision-status').textContent();return text.includes(`Status: ${expected}`)})
  const id=(await page.locator('#decision-id').textContent()).replace('Decision ID: ','')
  const d=await(await page.request.get(base+'/api/decisions/'+id)).json();decisions.push(d)
  assert.equal(d.snapshot_id,sid);assert.equal(d.review.snapshot_sha256,saved.sha256)
  assert((await page.locator('#analyst-output').textContent()).includes(d.review.analyst.proposal))
  assert((await page.locator('#reviewer-output').textContent()).includes(d.review.reviewer.verdict||'No verdict'))
  assert.equal(d.paper_order_eligible,false)
  if(index==0){assert.equal(d.review.final_check.passed,true);assert.equal(d.proposal,'hold')}
  if(index==1){assert.equal(d.review.reviewer.verdict,'reject_unsupported_signal');assert.equal(d.review.final_check.passed,false)}
  if(index==2){
   assert.equal(d.review.analyst.proposal,'buy');assert.equal(d.review.reviewer.verdict,'accept')
   assert.equal(d.review.supporting_facts.cash,'948');assert.equal(d.review.supporting_facts.configured_buy_cost,'1900')
   assert((await page.locator('#reviewer-explanation').textContent()).includes('cash 948'))
   assert((await page.locator('#reviewer-explanation').textContent()).includes('configured buy cost 1900'))
  }
  await page.locator('.agent-review').screenshot({path:resolve(output,`review-${expected}.png`)})
 }
 await page.locator('.agent-review summary').click();await page.getByRole('heading',{name:'Reviewer question',exact:true}).waitFor()
 assert((await page.locator('.agent-review').textContent()).includes('independent reviewer'))
 assert((await page.locator('.agent-review').textContent()).includes('review_verdict'))
 checks.push('Agreed eligible hold, reviewer rejection, jointly accepted unaffordable buy, review timeout and invalid reply displayed and saved under original decision IDs')
 assert.deepEqual((await(await page.request.get(base+'/api/decision-snapshots/'+sid)).json()),saved)
 await page.setViewportSize({width:390,height:844});await page.locator('.agent-review').screenshot({path:resolve(output,'mobile-review.png')})
 const box=await page.locator('.agent-review').boundingBox();assert(box.x>=0&&box.x+box.width<=391)
 assert.deepEqual(errors,[])
 checks.push('Same frozen snapshot/hash, inspectable distinct role instructions/answers and final checks; no page errors on desktop/mobile')
 console.log(JSON.stringify({checks,snapshot_id:sid,decisions}))
}catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser.close()}

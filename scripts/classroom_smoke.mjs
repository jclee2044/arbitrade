import assert from 'node:assert/strict'
import { resolve } from 'node:path'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2], base='http://127.0.0.1:15262'
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true})
const page=await browser.newPage({viewport:{width:1400,height:1100}}), errors=[], checks=[], ids=[]
page.on('pageerror',e=>errors.push(e.message))
try {
 await page.goto(base,{waitUntil:'networkidle'})
 await page.getByRole('tab', {name:'AI', exact:true}).click()
 await page.waitForFunction(()=>!document.querySelector('.summary-actions .primary')?.disabled)
 for(const [index,expected] of ['long','short','wait',null,null,null].entries()) {
   const pending=page.waitForResponse(r=>r.url().endsWith('/api/decisions')&&r.request().method()==='POST')
   await page.getByRole('button',{name:'Decision API',exact:true}).click()
   const response=await pending, request=response.request().postDataJSON(), result=await response.json()
   assert.deepEqual(Object.keys(request),['capture'])
   assert.deepEqual(Object.keys(request.capture).sort(), ['ticker','interval','captured_at','candle_timestamp','image','visible_candles','last_quote_at','last_source_at','is_stale','volume_status'].sort())
   assert(request.capture.visible_candles>0)
   assert.equal(result.kind,'classroom_chart'); assert.equal(result.choice,expected); assert.equal(result.paper_order_eligible,false)
   const status=['valid','valid','valid','malformed_answer','timeout','provider_error'][index]
   assert.equal(result.status,status)
   await page.locator('#classroom-status').waitFor()
   assert((await page.locator('#classroom-status').innerText()).includes(status))
   assert.equal(await page.locator('#classroom-decision-id').isVisible(),false)
   assert((await page.locator('#classroom-capture-context').innerText()).includes(result.context.is_stale ? 'Stale or historical data' : 'Fresh data'))
   if(index===0) await page.screenshot({path:resolve(output,'success.png'),fullPage:true})
   await page.getByText('Decision details',{exact:true}).click()
   await page.getByText(`Decision ID: ${result.id}`,{exact:true}).waitFor()
   assert.deepEqual(JSON.parse(await page.locator('#classroom-result pre').innerText()), {
     context:result.context, questions:result.questions, answer:result.answer,
   })
   await page.getByText('Decision details',{exact:true}).click()
   if(expected) await page.getByRole('heading',{name:`Chart choice · ${expected.toUpperCase()}`,exact:true}).waitFor()
   else assert.equal(await page.getByRole('heading',{name:'Chart decision unavailable',exact:true}).count(),1)
   assert.equal(await page.locator('.classroom-decision img, .classroom-decision a').count(),0)
   assert.deepEqual((await page.request.get(base+'/api/decisions/'+result.id).then(r=>r.json())),result)
   const image=await page.request.get(base+result.image_url)
   assert.equal(Buffer.compare(await image.body(),Buffer.from(request.capture.image.split(',')[1],'base64')),0)
   ids.push(result.id)
 }
 checks.push('Browser displays long, short, wait and distinct malformed/timeout/provider failures; errors have no substitute choice')
 checks.push('Actual Vue request has only pixels and exact context fields; stored image still equals submitted capture despite removal of preview')
 const invalid=await page.request.post(base+'/api/decisions',{data:{capture:{image:'invalid',candles:[]}}})
 assert.equal(invalid.status(),422)
 await page.getByText('How the Decision API works',{exact:true}).click()
 assert.equal(await page.locator('.decision-flow li').count(),4)
 await page.screenshot({path:resolve(output,'desktop.png'),fullPage:true})
 await page.setViewportSize({width:390,height:844})
 await page.locator('#classroom-result').scrollIntoViewIfNeeded()
 await page.getByText('Decision details',{exact:true}).click()
 await page.locator('#classroom-decision-id').waitFor()
 await page.screenshot({path:resolve(output,'mobile.png'),fullPage:true})
 const box=await page.locator('.classroom-decision').boundingBox();assert(box.x>=0&&box.x+box.width<=391)
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth))
 assert.deepEqual(errors,[])
 checks.push('Four-stage explanation renders; audit metadata expands on desktop/phone; no screenshot, overflow or uncaught browser errors')
 console.log(JSON.stringify({ids,checks}))
} catch(error){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw error}
finally{await browser.close()}

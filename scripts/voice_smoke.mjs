import assert from 'node:assert/strict'
import {resolve} from 'node:path'
import {chromium} from '../frontend/node_modules/playwright-core/index.mjs'
const output=process.argv[2],base='http://127.0.0.1:15173',backend='http://127.0.0.1:18000'
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,chromiumSandbox:true,
 args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required']})
const context=await browser.newContext({viewport:{width:1400,height:1100},permissions:['microphone']})
await context.addInitScript(()=>{
 window.__streams=[];window.__peers=[];window.__NativePeer=window.RTCPeerConnection
 window.RTCPeerConnection=class extends window.__NativePeer {constructor(...a){super(...a);window.__peers.push(this)}}
 const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
 navigator.mediaDevices.getUserMedia=async(options)=>{
  if(window.__deny)throw new DOMException('Denied by test','NotAllowedError')
  const stream=await get(options);window.__streams.push(stream)
  if(window.__delay)return new Promise(done=>{window.__resolveMic=()=>done(stream)})
  return stream
 }
})
const page=await context.newPage(),errors=[],checks=[]
page.on('pageerror',e=>errors.push(e.message))
const button=name=>page.getByRole('button',{name,exact:true})
async function until(fn){for(let i=0;i<200;i++){if(await fn())return;await new Promise(done=>setTimeout(done,100))}throw Error('Voice UI timed out')}
async function released(){assert.equal(await page.locator('#voice-microphone').textContent(),'Microphone: off');assert(await page.evaluate(()=>window.__streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'))));assert(await page.evaluate(()=>window.__peers.every(p=>p.connectionState==='closed')))}
await page.route('**/api/voice/sessions',async route=>{
 const r=await route.fetch()
 if(!r.ok()){await route.fulfill({response:r});return}
 const body=route.request().postDataJSON(),result=await r.json()
 // Actual in-browser WebRTC pair and media tracks; provider answers/transcripts mocked.
 const answer=await page.evaluate(async({offer,id})=>{
  const peer=new window.__NativePeer();window.__remotePeer=peer;window.__sent=[];window.__receivedAudio=0
  const ac=new AudioContext();await ac.resume();const osc=ac.createOscillator(),gain=ac.createGain(),dest=ac.createMediaStreamDestination()
  gain.gain.value=.001;osc.connect(gain).connect(dest);osc.start();window.__remoteAudio={ac,osc,dest}
  peer.addTrack(dest.stream.getAudioTracks()[0],dest.stream)
  peer.ontrack=()=>window.__receivedAudio++
  peer.ondatachannel=e=>{
   const dc=e.channel;window.__remoteDc=dc
   dc.onopen=()=>dc.send(JSON.stringify({type:'session.started',session:{id}}))
   dc.onmessage=e=>{const m=JSON.parse(e.data);window.__sent.push(m);if(m.type==='session.close')dc.send(JSON.stringify({type:'session.closed'}))}
  }
  await peer.setRemoteDescription({type:'offer',sdp:offer});await peer.setLocalDescription(await peer.createAnswer())
  if(peer.iceGatheringState!=='complete')await new Promise(done=>{peer.onicegatheringstatechange=()=>{if(peer.iceGatheringState==='complete')done()}})
  return peer.localDescription.sdp
 },{offer:body.sdp,id:result.session.id})
 result.transport.sdp=answer;await route.fulfill({response:r,json:result})
})
async function closeRemote(){await page.evaluate(()=>{window.__remotePeer?.close();window.__remoteAudio?.dest.stream.getTracks().forEach(t=>t.stop());window.__remoteAudio?.osc.stop();window.__remoteAudio?.ac.close()})}
try{
 await page.goto(base,{waitUntil:'networkidle'})
 await until(async()=>await page.locator('#voice-decision option').count()>1)
 const list=await(await page.request.get(base+'/api/voice/decisions')).json();const selected=list.find(d=>d.proposal==='hold');assert(selected)
 await page.locator('#voice-decision').selectOption(selected.id)
 await until(async()=>(await page.locator('#voice-selected').textContent()).includes(selected.id))
 const record=await(await page.request.get(base+'/api/voice/decisions/'+selected.id)).json()
 assert.equal(record.paper_outcome.trade_recorded,false);assert.equal(record.current_recorded_account.cash,'948')
 await button('Start voice').click();await until(async()=>(await page.locator('#voice-status').textContent()).startsWith('Voice connected'))
 assert.equal(await page.locator('#voice-microphone').textContent(),'Microphone: active')
 assert(await page.evaluate(()=>window.__receivedAudio>0&&document.querySelector('audio').srcObject.getAudioTracks().length===1))
 const heard=[] // Mocked captions, not a live listening result.
 for(const [question,reply] of [
  ['What did the agents decide for this symbol?','For AAPL the analyst proposed hold, the reviewer accepted, and Python validation was valid. '],
  ['What happened to the paper account?','No fill is linked to this decision. The recorded account has 948 cash and 4 AAPL shares. '],
 ]){
  await page.evaluate(({question,reply})=>{window.__remoteDc.send(JSON.stringify({type:'session.input_transcript.delta',delta:question+' ',start_ms:0,end_ms:1}));window.__remoteDc.send(JSON.stringify({type:'session.output_transcript.delta',delta:reply,start_ms:2,end_ms:3}))},{question,reply})
  await until(async()=>(await page.locator('[data-speaker="Assistant"]').textContent()).includes(reply));heard.push({question,mocked_reply:reply})
 }
 assert.equal((await(await page.request.get(backend+'/fixture/voice-calls')).json()).length,1)
 await page.locator('.voice-panel').screenshot({path:resolve(output,'two-way-session.png')})
 await button('End voice').click();await until(async()=>(await page.locator('#voice-status').textContent()).includes('Voice ended'));await released()
 assert.deepEqual(await page.evaluate(()=>window.__sent.map(e=>e.type)),['session.close']);await closeRemote()
 checks.push('Mocked provider, real local WebRTC media pair: two questions/captions in one session, incoming/outgoing audio tracks, selected SQLite context, End releases native microphone tracks/peer/audio')
 await page.evaluate(()=>window.__deny=true);await button('Start voice').click()
 await until(async()=>(await page.locator('#voice-status').textContent()).includes('permission denied'));await released()
 assert.equal((await(await page.request.get(backend+'/fixture/voice-calls')).json()).length,1)
 await page.locator('.voice-panel').screenshot({path:resolve(output,'permission-denied.png')});await page.evaluate(()=>window.__deny=false)
 await page.request.post(backend+'/fixture/voice-fail',{data:{fail:true}});await button('Start voice').click()
 await until(async()=>(await page.locator('#voice-status').textContent()).includes('controlled_voice_failure'));await released()
 await page.request.post(backend+'/fixture/voice-fail',{data:{fail:false}})
 await button('Start voice').click();await until(async()=>(await page.locator('#voice-status').textContent()).startsWith('Voice connected'))
 await closeRemote();await until(async()=>(await page.locator('#voice-microphone').textContent()).includes('off'));await released()
 await page.evaluate(()=>window.__delay=true);await button('Start voice').click();await until(async()=>page.evaluate(()=>!!window.__resolveMic))
 await button('End voice').click();await page.evaluate(()=>window.__resolveMic());await until(async()=>page.evaluate(()=>window.__streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'))));await released()
 checks.push('Denied microphone makes no provider call; failed provider, RTC disconnect and End during pending permission release all tracks and peers')
 await page.setViewportSize({width:390,height:844});await page.locator('.voice-panel').screenshot({path:resolve(output,'voice-mobile.png')})
 const box=await page.locator('.voice-panel').boundingBox();assert(box.x>=0&&box.x+box.width<=391);assert.deepEqual(errors,[])
 console.log(JSON.stringify({checks,decision_id:selected.id,mocked_conversation:heard,record,provider_calls:await(await page.request.get(backend+'/fixture/voice-calls')).json()}))
}catch(e){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true}).catch(()=>{});throw e}
finally{await browser.close()}

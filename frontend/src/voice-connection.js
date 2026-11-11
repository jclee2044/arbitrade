// Native WebRTC only. The server owns all credentials and conversation context.
export class VoiceConnection {
 constructor(audio,update,transcript){this.audio=audio;this.update=update;this.transcript=transcript;this.generation=0;this.phase='idle'}
 state(phase,message){this.phase=phase;this.update({phase,message,microphone:!!this.stream?.getAudioTracks().some(t=>t.readyState==='live')})}
 releaseMic(){this.stream?.getTracks().forEach(t=>t.stop());this.stream=null}
 cleanup(message='Voice ended',phase='idle'){
  this.generation++;clearTimeout(this.deadline);clearTimeout(this.closeDeadline);this.abort?.abort();this.abort=null
  this.releaseMic();const dc=this.dc,pc=this.pc;this.dc=null;this.pc=null
  dc?.close();pc?.close();this.audio.pause();this.audio.srcObject=null
  this.state(phase,message)
 }
 end(){
  this.releaseMic()
  if(this.phase==='active'&&this.dc?.readyState==='open'){
   this.state('ending','Ending voice · microphone released')
   this.dc.send(JSON.stringify({type:'session.close'}))
   this.closeDeadline=setTimeout(()=>this.cleanup('Voice ended; provider close confirmation unavailable'),15000)
  }else this.cleanup()
 }
 async ice(pc,signal){
  if(signal.aborted)throw new DOMException('Ended','AbortError')
  if(pc.iceGatheringState==='complete')return
  await new Promise((resolve,reject)=>{
   const finish=(error)=>{clearTimeout(timer);pc.removeEventListener('icegatheringstatechange',check);signal.removeEventListener('abort',cancel);error?reject(error):resolve()}
   const check=()=>{if(pc.iceGatheringState==='complete')finish()}
   const cancel=()=>finish(new DOMException('Ended','AbortError'))
   const timer=setTimeout(()=>finish(Error('ICE gathering timed out')),10000)
   pc.addEventListener('icegatheringstatechange',check);signal.addEventListener('abort',cancel,{once:true});check()
  })
 }
 async start(decisionId){
  this.cleanup('Requesting microphone','requesting');const token=this.generation
  try{
   if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia||!window.RTCPeerConnection)throw Error('Voice requires microphone support on localhost or HTTPS')
   const pc=new RTCPeerConnection();this.pc=pc;this.abort=new AbortController();const signal=this.abort.signal
   pc.addEventListener('track',e=>{
    if(token!==this.generation)return
    this.audio.srcObject=e.streams[0]||new MediaStream([e.track])
    this.audio.play().catch(()=>{if(token===this.generation)this.state(this.phase,'Use Play on the audio controls to hear the assistant')})
   })
   pc.addEventListener('connectionstatechange',()=>{
    if(token===this.generation&&['failed','disconnected','closed'].includes(pc.connectionState))this.cleanup('Voice disconnected; microphone released','error')
   })
   const stream=await navigator.mediaDevices.getUserMedia({audio:true})
   if(token!==this.generation){stream.getTracks().forEach(t=>t.stop());return}
   this.stream=stream
   for(const track of stream.getAudioTracks()){
    pc.addTrack(track,stream)
    track.addEventListener('ended',()=>{if(token===this.generation&&this.phase!=='ending')this.cleanup('Microphone disconnected','error')})
   }
   this.state('connecting','Microphone active · connecting')
   this.deadline=setTimeout(()=>this.cleanup('Voice startup timed out; microphone released','error'),35000)
   const dc=pc.createDataChannel('oai-events');this.dc=dc
   dc.addEventListener('message',({data})=>{
    if(token!==this.generation)return
    let e;try{e=JSON.parse(data)}catch{return}
    if(e.type==='session.started'){
     clearTimeout(this.deadline);this.state('active','Voice connected · ask your question and follow-up')
    }else if(e.type==='session.closed')this.cleanup('Voice ended · microphone released')
    else if(['session.input_transcript.delta','session.output_transcript.delta'].includes(e.type)&&typeof e.delta==='string'){
     this.transcript({speaker:e.type==='session.input_transcript.delta'?'You':'Assistant',delta:e.delta,start_ms:e.start_ms,end_ms:e.end_ms})
    }else if(e.type==='error')this.cleanup('Voice session reported an error; microphone released','error')
   })
   dc.addEventListener('close',()=>{if(token===this.generation&&this.dc===dc)this.cleanup('Voice disconnected; microphone released')})
   const offer=await pc.createOffer();await pc.setLocalDescription(offer);await this.ice(pc,signal)
   if(token!==this.generation)return
   const response=await fetch('/api/voice/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({decision_id:decisionId,sdp:pc.localDescription.sdp}),signal})
   const result=await response.json()
   if(token!==this.generation)return
   if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Voice connection failed')
   if(result.decision_id!==decisionId||!result.session?.id||result.transport?.type!=='webrtc'||!result.transport.sdp)throw Error('Invalid voice session answer')
   this.sessionId=result.session.id;this.record=result.record
   this.update({sessionId:this.sessionId,record:this.record,providerMode:result.provider_mode})
   await pc.setRemoteDescription({type:'answer',sdp:result.transport.sdp})
   // Wait for session.started; HTTP creation already starts the provider session.
  }catch(e){
   if(token!==this.generation)return
   this.cleanup(e.name==='NotAllowedError'?'Microphone permission denied':e.message||'Voice startup failed','error')
  }
 }
}

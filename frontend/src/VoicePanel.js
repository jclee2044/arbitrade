import {h,ref,onMounted,onBeforeUnmount,nextTick} from 'vue'
import {VoiceConnection} from './voice-connection.js'

export default {
 setup(){
  const choices=ref([]),selected=ref(''),record=ref(null),phase=ref('idle'),message=ref('Select a recorded decision to discuss.'),mic=ref(false),audio=ref(null),captions=ref([]),session=ref(''),mode=ref(''),error=ref('')
  let connection,disposed=false,selectionVersion=0
  async function load(){
   try{
    const r=await fetch('/api/voice/decisions');if(!r.ok)throw Error('Cannot load saved decisions')
    choices.value=await r.json()
    if(!selected.value&&choices.value.length){selected.value=choices.value[0].id;await choose()}
   }catch(e){error.value=e.message}
  }
  async function choose(){
   selectionVersion++;const token=selectionVersion
   connection?.cleanup();record.value=null;captions.value=[];session.value='';mode.value='';error.value=''
   if(!selected.value)return
   try{
    const r=await fetch('/api/voice/decisions/'+encodeURIComponent(selected.value));const d=await r.json()
    if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Cannot load decision')
    if(!disposed&&token===selectionVersion)record.value=d
   }catch(e){if(token===selectionVersion)error.value=e.message}
  }
  async function start(){
   if(busy())return
   phase.value='requesting';error.value='';captions.value=[];session.value=''
   await nextTick()
   connection=new VoiceConnection(audio.value,state=>{
    if(disposed)return
    if(state.phase!==undefined)phase.value=state.phase
    if(state.message!==undefined)message.value=state.message
    if(state.microphone!==undefined)mic.value=state.microphone
    if(state.sessionId)session.value=state.sessionId
    if(state.record)record.value=state.record
    if(state.providerMode)mode.value=state.providerMode
   },fragment=>{if(!disposed)captions.value=[...captions.value,fragment]})
   await connection.start(selected.value)
  }
  onMounted(load)
  onBeforeUnmount(()=>{disposed=true;selectionVersion++;connection?.cleanup()})
  const busy=()=>['requesting','connecting','active','ending'].includes(phase.value)
  return()=>h('section',{class:'voice-panel','aria-labelledby':'voice-title'},[
   h('h3',{id:'voice-title'},'Discuss a recorded decision by voice'),
   h('p','Two-way voice about one saved record. Ask a question, listen, then ask a follow-up in the same session. Voice cannot change the paper account.'),
   h('label',{for:'voice-decision'},'Selected decision '),
   h('select',{id:'voice-decision',value:selected.value,onChange:e=>{selected.value=e.target.value;choose()}},[
    h('option',{value:''},'Choose a saved decision'),...choices.value.map(d=>h('option',{value:d.id},`${d.symbol} / ${d.interval} · ${d.proposal||'No proposal'} · ${d.status} · ${d.id}`)),
   ]),
   h('button',{disabled:busy(),onClick:load},'Reload saved decisions'),
   record.value?h('div',{class:'voice-record'},[
    h('p',{id:'voice-selected'},`${record.value.decision_id} · ${record.value.symbol} / ${record.value.interval} · Cutoff ${record.value.cutoff}`),
    h('p',{id:'voice-record-facts'},`Analyst ${record.value.analyst.proposal||'No proposal'} · Reviewer ${record.value.reviewer?.verdict||'Not recorded'} · Python ${record.value.validation.status}`),
    h('p',{id:'voice-record-outcome'},record.value.paper_outcome.fill?`Recorded fill ${record.value.paper_outcome.fill.quantity} @ ${record.value.paper_outcome.fill.price} · Cash ${record.value.paper_outcome.fill_account?.cash} · Shares ${record.value.paper_outcome.fill_account?.shares}`:`No recorded fill · ${record.value.paper_outcome.application?.reason||record.value.paper_outcome.order?.status||record.value.paper_outcome.application?.status||'Manual analysis; no linked order'}`),
    h('p',`Record read at ${record.value.summary_read_at}. End and start again to refresh later outcomes.`),
   ]):h('p','No saved decision selected. Create a manual decision or choose one from the saved list.'),
   h('button',{disabled:busy()||!record.value,onClick:start},'Start voice'),
   h('button',{disabled:!busy(),onClick:()=>connection?.end()},'End voice'),
   h('p',{id:'voice-status',role:'status'},message.value),
   h('p',{id:'voice-microphone'},`Microphone: ${mic.value?'active':'off'}`),
   session.value?h('p',{id:'voice-session'},`Session ${session.value} · ${mode.value}`):null,
   error.value?h('p',{role:'alert'},error.value):null,
   h('audio',{ref:audio,autoplay:true,controls:true,'aria-label':'Voice assistant audio'}),
   h('p','Try: “What did the agents decide for this symbol?” Then: “What happened to the paper account?”'),
   h('div',{id:'voice-transcript'},[
    ...['You','Assistant'].map(speaker=>h('p',{'data-speaker':speaker},[h('strong',speaker+': '),captions.value.filter(f=>f.speaker===speaker).map(f=>f.delta).join('')])),
   ]),
  ])
 }
}

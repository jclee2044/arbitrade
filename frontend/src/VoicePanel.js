import {h,ref,onMounted,onBeforeUnmount,nextTick,watch} from 'vue'
import {VoiceConnection} from './voice-connection.js'
import {formatUtc} from './chart-data.js'

export default {
 emits:['session'],
 setup(props,{emit,expose}){
  const choices=ref([]),selected=ref(''),record=ref(null),phase=ref('idle'),message=ref('Select a recorded decision to discuss.'),mic=ref(false),audio=ref(null),captions=ref([]),session=ref(''),mode=ref(''),error=ref('')
  const chooser=ref(false)
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
  async function selectDecision(id,open=true){
   if(open)chooser.value=true
   if(selected.value===id&&record.value)return
   selected.value=id
   const detail=choose()
   if(!choices.value.some(choice=>choice.id===id))await load()
   await detail
  }
  function openChooser(){chooser.value=true;load()}
  expose({selectDecision,openChooser})
  watch(phase,value=>emit('session',['requesting','connecting','active','ending'].includes(value)))
  onMounted(load)
  onBeforeUnmount(()=>{disposed=true;selectionVersion++;connection?.cleanup()})
  const busy=()=>['requesting','connecting','active','ending'].includes(phase.value)
  return()=>h('section',{class:'voice-panel','aria-labelledby':'voice-title'},[
   h('header',[h('h2',{id:'voice-title'},'Voice chat'),h('span',{id:'voice-microphone',class:mic.value?'mic-active':''},mic.value?'Mic on':'Mic off')]),
   h('p',{class:'voice-intro'},record.value ? 'Discuss '+record.value.symbol+' · '+record.value.interval+' · '+(record.value.analyst.proposal||record.value.status||'saved decision')+' · '+formatUtc(Date.parse(record.value.cutoff)/1000) : 'Choose a recorded decision to discuss.'),
   h('div',{class:'voice-actions'},[
    h('button',{class:'primary',disabled:busy()||!record.value,onClick:start},'Start voice'),
    busy()?h('button',{onClick:()=>connection?.end()},'End voice'):null,
    h('button',{class:'review-link','aria-expanded':chooser.value,'aria-controls':'voice-chooser',onClick:()=>{if(chooser.value)chooser.value=false;else openChooser()}},chooser.value?'Close decision list':'Choose decision'),
   ]),
   h('div',{id:'voice-chooser',hidden:!chooser.value},[
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
   ]),
   h('p',{id:'voice-status',role:'status',hidden:phase.value==='idle'&&!session.value},message.value),
   session.value?h('p',{id:'voice-session'},`Session ${session.value} · ${mode.value}`):null,
   error.value?h('p',{role:'alert'},error.value):null,
   h('audio',{ref:audio,autoplay:true,controls:true,hidden:!busy()&&!session.value,'aria-label':'Voice assistant audio'}),
   h('div',{id:'voice-transcript',hidden:!captions.value.length},[
    ...['You','Assistant'].map(speaker=>h('p',{'data-speaker':speaker},[h('strong',speaker+': '),captions.value.filter(f=>f.speaker===speaker).map(f=>f.delta).join('')])),
   ]),
  ])
 }
}

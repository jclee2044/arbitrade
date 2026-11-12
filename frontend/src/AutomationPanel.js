import { h,ref,watch,onBeforeUnmount,nextTick } from 'vue'
import { chartPng,renderFrozenChart } from './chart-capture.js'

export default {
 props:{accountId:String,symbol:String,interval:String,shortWindow:Number,longWindow:Number,completed:Array},
 emits:['running'],
 setup(props,{emit,expose}){
  const status=ref({run:null,attempts:[],state:null}),error=ref(''),working=ref(false),stopRequested=ref(false),container=ref(null),preview=ref(null),frozen=ref(null)
  const handled=new Set()
  let chart,disposed=false,processing=false,polling=false,timer,version=0
  async function api(path,body){
   const r=await fetch('/api/paper/automation'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
   const data=await r.json();if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'Automation request failed');return data
  }
  async function load(){
   if(polling||disposed)return;polling=true;const token=version
   try{const result=await api(status.value.run?'?run_id='+status.value.run.id:'');if(!disposed&&token===version)status.value=result}
   catch(e){if(!disposed)error.value=e.message}finally{polling=false}
  }
  async function start(){
   error.value='';working.value=true;version++
   try{stopRequested.value=false;status.value=await api('/start',{account_id:props.accountId,symbol:props.symbol,interval:props.interval,short_window:props.shortWindow,long_window:props.longWindow})}
   catch(e){error.value=e.message}finally{working.value=false}
  }
  async function stop(){
   version++;stopRequested.value=true;const run=status.value.run
   if(run){try{status.value=await api('/'+run.id+'/stop',{})}catch(e){error.value='Stop not confirmed: '+e.message}}
  }
  async function process(){
   if(processing||disposed||stopRequested.value||!status.value.run?.enabled)return
   const run=status.value.run
   if(props.accountId!=='live'||props.symbol!==run.symbol||props.interval!==run.interval||props.shortWindow!==run.short_window||props.longWindow!==run.long_window){await stop();return}
   processing=true;const token=version
   try{
    for(const row of props.completed||[]){
     if(disposed||token!==version||!status.value.run?.enabled)break
     const key=run.account_id+':'+run.strategy+':'+run.interval+':'+row.timestamp
     if(handled.has(key)||Date.parse(row.interval_end)<=Date.parse(run.started_at))continue
     const claimed=await api('/claim',{run_id:run.id,candle_timestamp:row.timestamp})
     handled.add(key)
     if(!claimed.claimed||!claimed.snapshot||claimed.attempt.status!=='capturing')continue
     let capture=null,capture_error=null
     try{
      frozen.value=claimed.snapshot;await nextTick();chart?.remove()
      chart=await renderFrozenChart(container.value,claimed.snapshot)
      if(!container.value?.isConnected)throw Error('Chart unavailable')
      capture=chartPng(chart,claimed.snapshot);preview.value=capture.image_url
     }catch(e){capture_error='chart_unavailable'}
     // Stop can run while capture or model analysis is pending; server rechecks its run token.
     await api('/attempts/'+claimed.attempt.id+'/analyze',{capture,capture_error})
     await load()
    }
   }catch(e){if(!disposed)error.value=e.message}finally{processing=false}
  }
  expose({stop})
  watch(()=>Boolean(status.value.run?.enabled),enabled=>emit('running',enabled))
  watch(()=>[props.accountId,props.symbol,props.interval,props.shortWindow,props.longWindow],()=>{if(status.value.run?.enabled)stop()})
  watch(()=>[props.completed,status.value.run?.enabled],()=>process(),{deep:true})
  load();timer=setInterval(async()=>{await load();process()},800)
  onBeforeUnmount(()=>{disposed=true;version++;clearInterval(timer);chart?.remove();const r=status.value.run;if(r?.enabled)fetch('/api/paper/automation/'+r.id+'/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{})})
  return()=>h('section',{class:'automation-panel','aria-labelledby':'automation-title'},[
   h('h3',{id:'automation-title'},'Paper automation'),
   h('p','Review each newly completed live candle and simulate eligible orders at the next qualifying quote.'),
   h('details',[h('summary','Execution rules'),h('p','Each candle gets one frozen chart, analyst and reviewer. Stop blocks pending replies and cancels pending automation orders. No historical backfill. Maximum decision age: 120 seconds; fill quotes must be at most 30 seconds old. Constructed observations use a separate test account. Replay remains manual.')]),
   h('button',{disabled:working.value||!!status.value.run?.enabled||props.accountId!=='live',onClick:start},'Start paper automation'),
   h('button',{disabled:!status.value.run?.enabled,onClick:stop},'Stop paper automation'),
   h('p',{id:'automation-status'},`Automation: ${status.value.run?.enabled?(stopRequested.value?'stop requested; awaiting confirmation':'enabled'):'stopped'}${status.value.run?` · Account ${status.value.run.account_id} · ${status.value.run.strategy}`:''}`),
   error.value?h('p',{role:'alert'},error.value):null,
   status.value.state?h('p',{id:'automation-balances'},`Automation cash: ${status.value.state.account.cash} · Shares: ${status.value.state.positions.find(p=>p.symbol===props.symbol)?.shares||0}`):null,
   status.value.state?h('p',{id:'automation-pnl'},`Realized P&L: ${status.value.state.pnl_summary.find(p=>p.symbol===props.symbol)?.realized??'0'} · Unrealized P&L: ${status.value.state.pnl_summary.find(p=>p.symbol===props.symbol)?.unrealized??'Unavailable'}`):null,
   h('div',{ref:container,class:'decision-chart',style:{display:frozen.value?'block':'none'},'aria-label':'Frozen automation chart'}),
   frozen.value?h('p',{id:'automation-cutoff'},`${frozen.value.snapshot.symbol} / ${frozen.value.snapshot.interval} · Cutoff ${frozen.value.snapshot.decision_time} · Snapshot ${frozen.value.snapshot.snapshot_id}`):null,
   preview.value?h('img',{id:'automation-preview',src:preview.value,alt:'Fresh automation chart PNG'}):null,
   h('div',{class:'paper-history',role:'region','aria-label':'Automation history',tabindex:0},[h('table',{id:'automation-history'},[
    h('thead',[h('tr',['Candle / signal','Decision / roles','Execution / reason','Fill / resulting account'].map(t=>h('th',t)))]),
    h('tbody',status.value.attempts.map(a=>{
     const d=a.decision,fill=status.value.state?.fills.find(f=>f.id===a.fill_id),pnl=status.value.state?.pnl_history.find(p=>p.fill_id===a.fill_id)
     return h('tr',{'data-attempt-id':a.id},[
      h('td',`${a.candle_timestamp} · ${a.signal||'Pending'} · ${a.strategy} / ${a.interval}`),
      h('td',d?`${d.id} · Analyst ${d.proposal||'None'} · Reviewer ${d.review?.reviewer.verdict||d.review?.reviewer.status||'None'} · Final ${d.status}`:a.snapshot_id||'No snapshot'),
      h('td',`${a.status}${a.reason?' · '+a.reason:''}${a.order_id?' · Order '+a.order_id:''}`),
      h('td',fill?`Fill ${fill.id}: ${fill.quantity} @ ${fill.price} · Cash ${pnl?.cash} · Shares ${pnl?.shares} · P&L ${pnl?.total}`:'No fill'),
     ])
    })),
   ])]),
  ])
 }
}

import { h, ref, watch, onBeforeUnmount, nextTick } from 'vue'
import { chartPng, renderFrozenChart } from './chart-capture.js'

export default {
  emits: ['discuss', 'outcome', 'busy'],
  props: { accountId:String, symbol:String, interval:String, candleTimestamp:String,
    shortWindow:Number, longWindow:Number, completed:Boolean, chartRange:Function },
  setup(props, { emit, expose }) {
    const frozen=ref(null),decision=ref(null),busy=ref(false),error=ref(''),container=ref(null)
    const capture=ref(null),questions=ref([]),imageRequested=ref(false)
    let chart,disposed=false,frozenSelection
    watch(busy, value => emit('busy', value))
    async function jsonRequest(path,options) {
      const response=await fetch(path,options);const result=await response.json()
      if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Request failed')
      return result
    }
    function clearFrozen() {
      chart?.remove();chart=null;frozen.value=null;frozenSelection=null
      decision.value=null;capture.value=null;questions.value=[];imageRequested.value=false;error.value=''
    }
    async function reviewSelection(view) {
      if (busy.value) return
      const same = frozenSelection && frozenSelection.account_id===props.accountId && frozenSelection.symbol===props.symbol &&
        frozenSelection.interval===props.interval && Date.parse(frozenSelection.candle_timestamp)===Date.parse(props.candleTimestamp) &&
        frozenSelection.short_window===props.shortWindow && frozenSelection.long_window===props.longWindow
      if (same && (!view || view.decision.id===decision.value?.id)) return
      clearFrozen()
      if (!view) return
      busy.value=true
      try {
        frozenSelection=view.selection;frozen.value=view.frozen;decision.value=view.decision
        capture.value=view.capture;questions.value=view.questions;imageRequested.value=Boolean(view.capture)
        await nextTick()
        chart=await renderFrozenChart(container.value,view.frozen)
      } catch(failure){error.value=failure.message}
      finally{if(!disposed)busy.value=false}
    }
    async function freeze(withImage=false) {
      if (busy.value) return
      clearFrozen()
      busy.value=true;imageRequested.value=withImage
      try {
        const range=withImage?props.chartRange?.():null
        const selection={account_id:props.accountId,symbol:props.symbol,interval:props.interval,
          candle_timestamp:props.candleTimestamp,short_window:props.shortWindow,long_window:props.longWindow,
          ...(range?.from?{chart_start:new Date(range.from*1000).toISOString(),chart_end:new Date(range.to*1000).toISOString()}: {})}
        const result=await jsonRequest('/api/decision-snapshots',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(selection)})
        if(disposed)return
        frozen.value=result
        frozenSelection=selection
        await nextTick()
        chart=await renderFrozenChart(container.value,result)
        if(withImage){
          questions.value=await jsonRequest('/api/decision-questions/chart')
          await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)))
          if(!disposed)capture.value=chartPng(chart,result)
        }
        return result.snapshot
      } catch(failure){error.value=failure.message}
      finally{if(!disposed)busy.value=false}
    }
    async function analyze() {
      busy.value=true;error.value=''
      try {
        const result=await jsonRequest('/api/decisions',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({snapshot_id:frozen.value.snapshot.snapshot_id,...(capture.value?{capture:capture.value}:{})})})
        if(!disposed) {
          decision.value=result
          emit('outcome', {selection:frozenSelection, decision:result, frozen:frozen.value, capture:capture.value, questions:questions.value})
        }
      } catch(failure){if(!disposed)error.value=failure.message}
      finally{if(!disposed)busy.value=false}
    }
    async function generateSummary() {
      if (busy.value) return
      const snapshot = await freeze()
      if (!snapshot) return error.value
      if (!snapshot.completeness.complete) return 'Analysis needs more recorded evidence: ' + snapshot.completeness.missing.join(', ').replaceAll('_', ' ') + '.'
      await analyze()
      return error.value
    }
    expose({generateSummary,reviewSelection})
    onBeforeUnmount(()=>{disposed=true;chart?.remove()})
    return()=>h('div',{class:'decision-panel','aria-labelledby':'decision-title'},[
      h('h3',{id:'decision-title'},'Paper decision proposal'),
      h('p','Separate paper workflow: frozen candle/account evidence, position-aware actions and reviewer checks. A proposal never places an order.'),
      h('p',{class:'fine-print'},props.candleTimestamp ? 'Selected: '+props.symbol+' · '+props.candleTimestamp+' · '+(props.completed?'Ended':'Forming') : 'No candle selected.'),
      h('button',{disabled:busy.value||!props.accountId||!props.candleTimestamp||!props.completed,onClick:()=>freeze(false)},'Freeze selected candle'),
      h('button',{disabled:busy.value||!props.accountId||!props.candleTimestamp||!props.completed,onClick:()=>freeze(true)},'Ask about chart'),
      !props.completed?h('p','Select a completed candle in the candle inspector to freeze it.'):null,
      error.value?h('p',{role:'alert'},error.value):null,
      frozen.value?h('div',{key:'frozen-snapshot',class:'frozen-snapshot'},[
        h('p',{id:'snapshot-id'},`Snapshot ID: ${frozen.value.snapshot.snapshot_id}`),
        h('p',{id:'snapshot-market'},`Market data: ${frozen.value.snapshot.provenance.market_data_kind} · ${frozen.value.snapshot.symbol} / ${frozen.value.snapshot.interval} · Decision time: ${frozen.value.snapshot.decision_time}`),
        h('p',`Frozen account: ${frozen.value.snapshot.account?.account_id || 'Unavailable'} · SHA-256: ${frozen.value.sha256}`),
        h('dl',{class:'snapshot-facts'},[
          ['Close',frozen.value.snapshot.candle?.close??'Unavailable'],
          ['Short SMA',frozen.value.snapshot.indicators.short??'Unavailable'],
          ['Long SMA',frozen.value.snapshot.indicators.long??'Unavailable'],
          ['Crossover',frozen.value.snapshot.indicators.crossover||'None'],
          ['Simulated cash',frozen.value.snapshot.account?.cash??'Unavailable'],
          ['Shares',frozen.value.snapshot.account?.shares??'Unavailable'],
          ['Configured order size',frozen.value.snapshot.account?.order_size??'Unavailable'],
        ].flatMap(([label,value])=>[h('dt',label),h('dd',String(value))])),
        h('div',{ref:container,class:'decision-chart','aria-label':'Frozen snapshot candles and SMA lines'}),
        h('p',{id:'snapshot-eligibility'},frozen.value.snapshot.completeness.complete
          ? frozen.value.snapshot.completeness.paper_order_eligible?'Complete application snapshot. This panel never submits an order.':'Complete test-data snapshot · Ineligible for paper orders.'
          : `Incomplete snapshot · Ineligible for paper orders: ${frozen.value.snapshot.completeness.missing.join(', ')}`),
        capture.value?h('div',{class:'chart-capture'},[
          h('h4','Captured chart · Blue short SMA / amber long SMA'),
          h('p',{id:'capture-cutoff'},`${capture.value.manifest.symbol} / ${capture.value.manifest.interval} · Cutoff ${capture.value.manifest.cutoff} · Range ${capture.value.manifest.range_start} to ${capture.value.manifest.range_end}`),
          h('p','This separate paper workflow submits the frozen chart with saved candle and account evidence.'),
          h('img',{id:'chart-preview',src:capture.value.image_url,alt:'Frozen chart PNG to submit for analysis'}),
          h('h4','Questions sent with this chart'),
          ...questions.value.map(q=>h('div',{class:'chart-question'},[h('strong',q.name),h('p',q.instructions),h('p',q.choices.map(c=>`${c.value}: ${c.description}`).join(' · '))])),
        ]):null,
        h('button',{disabled:busy.value||!frozen.value.snapshot.completeness.complete||(imageRequested.value&&!capture.value),onClick:analyze},busy.value?'Requesting…':capture.value?'Analyze captured chart':'Request model proposal'),
      ]):null,
      decision.value?h('div',{class:'decision-result'},[
        h('p',{id:'decision-id'},`Decision ID: ${decision.value.id}`),
        h('p',{id:'decision-provider'},`Model call: ${decision.value.model_call_kind} · ${decision.value.provider} / ${decision.value.model} · Market data: ${decision.value.market_data_kind}`),
        h('p',{id:'decision-status'},`Status: ${decision.value.status} · Validation: ${decision.value.validation_status}`),
        h('p',{id:'decision-proposal'},`Model proposal: ${decision.value.proposal||'None'}${decision.value.quantity!=null?` · Quantity ${decision.value.quantity}`:''}`),
        h('p',{id:'decision-explanation'},decision.value.explanation),
        h('button',{onClick:()=>emit('discuss',decision.value.id)},'Discuss this decision'),
        decision.value.image_analysis?h('div',{id:'chart-answers'},[
          ...Object.entries(decision.value.image_analysis.answers||{}).map(([name,a])=>h('p',{'data-answer':name},`${name}: ${a.choice}`)),
          h('p',{id:'crossover-comparison'},`Visual comparison: ${decision.value.image_analysis.comparison} · Python crossover: ${frozen.value.snapshot.indicators.crossover||'none'}`),
          h('p',decision.value.paper_order_eligible?'Passed frozen evidence checks. No order sent.':'Ineligible for automated execution.'),
          decision.value.image_analysis.image_url?h('a',{href:decision.value.image_analysis.image_url,target:'_blank'},'Open saved capture'):null,
        ]):null,
        decision.value.review?h('section',{class:'agent-review','aria-labelledby':'review-title'},[
          h('h4',{id:'review-title'},'Analyst and reviewer'),
          h('p',{id:'review-snapshot'},`Shared snapshot: ${decision.value.review.snapshot_id||'Unavailable'} · SHA-256: ${decision.value.review.snapshot_sha256||'Unavailable'}`),
          h('p',{id:'analyst-output'},`Analyst: ${decision.value.review.analyst.proposal||'No proposal'} · ${decision.value.review.analyst.status} · ${decision.value.review.analyst.provider} / ${decision.value.review.analyst.model}`),
          h('p',{id:'reviewer-output'},`Reviewer: ${decision.value.review.reviewer.verdict||'No verdict'} · ${decision.value.review.reviewer.status} · ${decision.value.review.reviewer.provider} / ${decision.value.review.reviewer.model}`),
          decision.value.review.reviewer.error_code?h('p',`Reviewer error: ${decision.value.review.reviewer.error_code}`):null,
          h('p',{id:'reviewer-explanation'},decision.value.review.reviewer.explanation||'Reviewer skipped because no validated analyst output was available.'),
          h('p',{id:'review-final'},`Final checks: ${decision.value.review.final_check.passed?'passed':'failed'} · ${decision.value.review.final_check.reasons.join(', ')||'No failed checks'}`),
          h('p',{id:'review-eligibility'},`Paper execution eligible: ${decision.value.review.final_check.paper_order_eligible?'yes':'no'} · No order submitted`),
          h('details',[
            h('summary','Inspect role instructions and answers'),
            h('h5','Analyst questions'),h('pre',JSON.stringify(decision.value.review.questions.analyst,null,2)),
            h('h5','Analyst answers'),h('pre',JSON.stringify(decision.value.review.analyst.answers,null,2)),
            h('h5','Reviewer question'),h('pre',JSON.stringify(decision.value.review.questions.reviewer,null,2)),
            h('h5','Reviewer answer'),h('pre',JSON.stringify(decision.value.review.reviewer.answer,null,2)),
            h('h5','Backend facts'),h('pre',JSON.stringify(decision.value.review.supporting_facts,null,2)),
          ]),
        ]):null,
        h('p',decision.value.image_analysis?'Python supplied the facts and rule checks. The model selected the three named answers; it did not supply a rationale. No paper order was sent.':'Facts and rule checks are supplied by Python. The model selected only the proposal; it did not supply a rationale. No paper order was sent.'),
      ]):null,
    ])
  },
}

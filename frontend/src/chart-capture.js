import {createChart,CandlestickSeries,HistogramSeries,LineSeries} from 'lightweight-charts'
import {adaptCandles} from './chart-data.js'
// Bind a chart export to its frozen SQLite snapshot, without capturing page UI.
export function captureManifest(saved) {
  const s=saved.snapshot,rows=s.chart.candles
  return {snapshot_id:s.snapshot_id,snapshot_sha256:saved.sha256,symbol:s.symbol,interval:s.interval,
    cutoff:s.decision_time,range_start:rows[0]?.timestamp??null,range_end:rows.at(-1)?.timestamp??null}
}
function crc32(bytes) {
  let crc=0xffffffff
  for(const byte of bytes){crc^=byte;for(let i=0;i<8;i++)crc=(crc>>>1)^((crc&1)?0xedb88320:0)}
  return (crc^0xffffffff)>>>0
}
export function chartPng(chart,saved) {
  const canvas=chart.takeScreenshot()
  const original=Uint8Array.from(atob(canvas.toDataURL('image/png').split(',')[1]),c=>c.charCodeAt(0))
  const data=new TextEncoder().encode('arbitrade_snapshot\0'+JSON.stringify(captureManifest(saved)))
  const chunk=new Uint8Array(data.length+12),view=new DataView(chunk.buffer)
  view.setUint32(0,data.length);chunk.set([116,69,88,116],4);chunk.set(data,8)
  view.setUint32(data.length+8,crc32(chunk.subarray(4,data.length+8)))
  const png=new Uint8Array(original.length+chunk.length)
  png.set(original.subarray(0,original.length-12));png.set(chunk,original.length-12)
  png.set(original.subarray(original.length-12),original.length-12+chunk.length)
  let binary='';for(let i=0;i<png.length;i+=8192)binary+=String.fromCharCode(...png.subarray(i,i+8192))
  return {image_url:'data:image/png;base64,'+btoa(binary),manifest:captureManifest(saved)}
}

// Shared frozen renderer for manual questions and automation; never reads live rows.
export async function renderFrozenChart(container,saved) {
  const chart=createChart(container,{autoSize:true,timeScale:{timeVisible:true},layout:{textColor:'#263648',background:{type:'solid',color:'#ffffff'}}})
  const prices=chart.addSeries(CandlestickSeries,{upColor:'#15847b',downColor:'#c9435b',borderVisible:false,wickUpColor:'#15847b',wickDownColor:'#c9435b'})
  const volume=chart.addSeries(HistogramSeries,{color:'#64748b',priceFormat:{type:'volume'}},1)
  chart.panes()[1].setHeight(80)
  const adapted=adaptCandles(saved.snapshot.chart.candles);prices.setData(adapted.prices);volume.setData(adapted.volumes)
  for(const [field,color] of [['short','#2563eb'],['long','#b45309']]){
    const line=chart.addSeries(LineSeries,{color,lineWidth:2,priceLineVisible:false})
    line.setData(saved.snapshot.indicators.series.map(row=>({time:Date.parse(row.timestamp)/1000,...(row[field]===null?{}:{value:row[field]})})))
  }
  const colors=['#7c3aed','#0e7490','#b91c1c','#4d7c0f'];let pane=2
  for(const [i,item] of (saved.snapshot.chart.indicators||[]).entries()){
    const line=chart.addSeries(LineSeries,{color:colors[i%colors.length],lineWidth:2,priceLineVisible:false},item.pane==='separate'?pane++:0)
    line.setData(item.rows.map(row=>({time:Date.parse(row.timestamp)/1000,...(row.value===null?{}:{value:row.value})})))
  }
  chart.timeScale().fitContent()
  await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)))
  return chart
}

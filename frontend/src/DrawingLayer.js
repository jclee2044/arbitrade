import { computed, h, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'

const emerald = '#047857'
const maroon = '#800020'
const ratios = [2, 3, 4]

export async function compositeDrawings(canvas, host) {
  const layer = host.parentElement.querySelector('.drawing-layer')
  if (!layer?.querySelector('[data-drawing]')) return
  const copy = layer.cloneNode(true)
  copy.querySelectorAll('[data-handle]').forEach(node => node.remove())
  const image = new Image()
  image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(new XMLSerializer().serializeToString(copy))
  await image.decode()
  const context = canvas.getContext('2d')
  const scale = canvas.width / host.clientWidth
  context.drawImage(image, 0, 0, image.naturalWidth * scale, image.naturalHeight * scale)
}

export default {
  props: { market: Object, active: Boolean },
  setup(props) {
    const m = props.market
    const svg = ref(null)
    const collections = reactive(new Map())
    const scope = computed(() => JSON.stringify([m.mode, m.symbol, m.timeframe]))
    const drawings = computed(() => collections.get(scope.value) || [])
    watch(drawings, () => m.changeChartSnapshot(), { deep: true, flush: 'sync' })
    const history = new Map()
    let gesture = null
    let lastContact = null
    function record(inverse) {
      if (!history.has(scope.value)) history.set(scope.value, [])
      history.get(scope.value).push(inverse)
    }
    function undo(event) {
      if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.altKey || event.key.toLowerCase() !== 'z') return
      if (event.defaultPrevented || event.target.isContentEditable || event.target.closest?.('input,textarea,select,[role="textbox"]')) return
      if (gesture) cancel()
      else {
        const inverse = history.get(scope.value)?.pop()
        if (!inverse) return
        inverse()
      }
      lastContact = null
      event.preventDefault()
    }
    onMounted(() => window.addEventListener('keydown', undo))
    onBeforeUnmount(() => window.removeEventListener('keydown', undo))
    function add(shape) {
      drawings.value.push(shape)
      return drawings.value.at(-1)
    }
    function end() {
      if (gesture && svg.value?.hasPointerCapture(gesture.id)) svg.value.releasePointerCapture(gesture.id)
      gesture = null
      m.drawingTool = null
    }
    function cancel() {
      gesture?.inverse?.()
      end()
      lastContact = null
    }
    watch([scope, () => props.active], cancel)
    watch(() => m.drawingTool, () => { lastContact = null })

    // Keep sub-candle offsets for smooth strokes, including in the empty right margin.
    function anchor(x, scale) {
      const time = scale.coordinateToTime(x) ?? (x < scale.timeToCoordinate(m.candles[0].time) ? m.candles[0] : m.latest).time
      return { time, offset: (x - scale.timeToCoordinate(time)) / scale.options().barSpacing }
    }
    function project(point, scale, spacing = scale.options().barSpacing) {
      const x = scale.timeToCoordinate(point.time)
      return x == null ? null : x + point.offset * spacing
    }
    function position(event) {
      const { left, top, width, height } = svg.value.getBoundingClientRect()
      return { x: Math.max(0, Math.min(width, event.clientX - left)), y: Math.max(0, Math.min(height, event.clientY - top)) }
    }
    function point(x, y, axes) {
      return { ...anchor(x, axes.scale), price: axes.prices.coordinateToPrice(y) }
    }
    // Sample the pointer path so a fast sweep can hit a narrow stroke between events.
    function erase(event) {
      const current = { x: event.clientX, y: event.clientY }
      const from = lastContact ?? current
      const dx = current.x - from.x, dy = current.y - from.y
      const steps = Math.max(1, Math.ceil(Math.hypot(dx, dy) / 4))
      const hit = new Set()
      const list = drawings.value
      for (let step = 1; step <= steps; step++) {
        for (const node of document.elementsFromPoint(from.x + dx * step / steps, from.y + dy * step / steps)) {
          const item = node.closest('[data-index]')
          if (item && svg.value.contains(item)) hit.add(list[Number(item.dataset.index)])
        }
      }
      for (const shape of hit) {
        const index = list.indexOf(shape)
        if (index < 0) continue
        list.splice(index, 1)
        record(() => list.splice(index, 0, shape))
      }
      lastContact = current
    }
    function down(event) {
      if (!props.active || !m.latest || gesture || event.button !== 0) return
      if (!collections.has(scope.value)) collections.set(scope.value, [])
      const axes = m.drawingAxes()
      const { x, y } = position(event)
      const tool = m.drawingTool
      const handle = event.target.dataset.handle || event.target.dataset.action
      if (tool === 'eraser') { erase(event); return }
      if (ratios.includes(tool)) {
        gesture = { handle: 'create', origin: { x, y }, ratio: tool }
      } else if (tool) {
        const start = point(x, y, axes)
        gesture = { shape: add({ type: tool, points: [start, start] }), handle: 'stroke' }
      } else if (handle) {
        const shape = drawings.value[Number(event.target.closest('[data-index]').dataset.index)]
        const before = { ...shape }
        gesture = { shape, handle, inverse: () => Object.assign(shape, before) }
        if (handle === 'move') {
          gesture.origin = { x, y, left: project(shape.left, axes.scale), right: project(shape.right, axes.scale),
            entry: axes.prices.priceToCoordinate(shape.entry) }
        }
      } else return
      if (gesture.handle === 'stroke' || gesture.handle === 'create') {
        const list = drawings.value
        const operation = gesture
        // A box first joins the collection when its drag has a visible area.
        gesture.inverse = () => {
          const index = list.indexOf(operation.shape)
          if (index >= 0) list.splice(index, 1)
        }
      }
      gesture.start = { x, y }
      gesture.id = event.pointerId
      svg.value.setPointerCapture(event.pointerId)
      event.preventDefault()
    }
    function move(event) {
      if (props.active && m.drawingTool === 'eraser') { erase(event); return }
      if (!gesture || gesture.id !== event.pointerId || !m.latest) return
      const { shape, handle } = gesture
      const axes = m.drawingAxes()
      const { x, y } = position(event)
      if (handle === 'create') {
        const { origin, ratio } = gesture
        if (!shape && (Math.abs(x - origin.x) < 3 || Math.abs(y - origin.y) < 3)) return
        const target = axes.prices.coordinateToPrice(Math.min(y, origin.y))
        const stop = axes.prices.coordinateToPrice(Math.max(y, origin.y))
        const risk = (target - stop) / (ratio + 1)
        const bounds = { left: anchor(Math.min(x, origin.x), axes.scale), right: anchor(Math.max(x, origin.x), axes.scale),
          risk, entry: stop + risk }
        if (shape) Object.assign(shape, bounds)
        else {
          gesture.shape = add({ type: 'box', ratio, ...bounds })
        }
      } else if (handle === 'stroke') {
        const next = point(x, y, axes)
        if (shape.type === 'line') shape.points[1] = next
        else shape.points.push(next)
      } else if (handle === 'move') {
        const origin = gesture.origin
        shape.left = anchor(origin.left + x - origin.x, axes.scale)
        shape.right = anchor(origin.right + x - origin.x, axes.scale)
        shape.entry = axes.prices.coordinateToPrice(origin.entry + y - origin.y)
      } else if (handle === 'width') {
        shape.right = anchor(Math.max(project(shape.left, axes.scale) + 12, x), axes.scale)
      } else {
        const entryY = axes.prices.priceToCoordinate(shape.entry)
        const distance = handle === 'stop' ? y - entryY : (entryY - y) / shape.ratio
        shape.risk = Math.abs(shape.entry - axes.prices.coordinateToPrice(entryY + Math.max(3, distance)))
      }
    }
    function up(event) {
      if (gesture?.id !== event.pointerId) return
      move(event)
      if (gesture.handle === 'create' && !gesture.shape) {
        if (svg.value.hasPointerCapture(event.pointerId)) svg.value.releasePointerCapture(event.pointerId)
        gesture = null
        return
      }
      const { x, y } = position(event)
      if (gesture.handle === 'create' && (Math.abs(x - gesture.start.x) < 3 || Math.abs(y - gesture.start.y) < 3)) {
        cancel()
        return
      }
      if (gesture.handle !== 'stroke' && gesture.handle !== 'create' && x === gesture.start.x && y === gesture.start.y) {
        cancel()
        return
      }
      record(gesture.inverse)
      end()
    }
    function render(shape, index, axes) {
      const { prices, scale } = axes
      if (shape.type !== 'box') {
        const spacing = scale.options().barSpacing
        const coords = shape.points.map(p => [project(p, scale, spacing), prices.priceToCoordinate(p.price)])
        if (coords.some(([x, y]) => x == null || y == null)) return null
        const points = coords.map(p => p.join(',')).join(' ')
        const stroke = h('polyline', { 'data-drawing': shape.type, points,
          fill: 'none', stroke: '#174e56', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' })
        return h('g', { 'data-index': index }, [stroke, m.drawingTool === 'eraser' ?
          h('polyline', { points, fill: 'none', stroke: 'transparent', 'stroke-width': 10, 'pointer-events': 'stroke' }) : null])
      }
      const x = project(shape.left, scale), right = project(shape.right, scale)
      if (x == null || right == null) return null
      const width = right - x
      const entry = prices.priceToCoordinate(shape.entry)
      const target = prices.priceToCoordinate(shape.entry + shape.ratio * shape.risk)
      const stop = prices.priceToCoordinate(shape.entry - shape.risk)
      function handle(name, cx, cy) {
        return h('circle', { class: 'editable', 'data-handle': name, cx, cy, r: 5, fill: '#fffaf0', stroke: '#244a40',
          style: { cursor: name === 'width' ? 'ew-resize' : 'ns-resize' } }, [h('title', 'Resize ' + name)])
      }
      const body = props.active && !m.drawingTool ? { class: 'editable', 'data-action': 'move', style: { cursor: 'move' } } : {}
      return h('g', { 'data-drawing': 'box', 'data-index': index, 'aria-label': 'Risk/reward 1:' + shape.ratio }, [
        h('rect', { ...body, x, y: target, width, height: entry - target, fill: emerald, 'fill-opacity': 0.5 }),
        h('rect', { ...body, x, y: entry, width, height: stop - entry, fill: maroon, 'fill-opacity': 0.5 }),
        h('line', { x1: x, x2: right, y1: entry, y2: entry, stroke: '#254437', 'stroke-width': 1.5 }),
        ...(props.active && !m.drawingTool ? [handle('target', x + width / 2, target),
          handle('width', right, entry), handle('stop', x + width / 2, stop)] : []),
      ])
    }
    return () => {
      // The chart invalidates primitives for price, time, pane and data changes.
      void m.drawingRevision
      const axes = m.drawingAxes()
      if (!axes || !m.latest) return null
      return h('svg', { ref: svg, class: ['drawing-layer', props.active && m.drawingTool && 'armed'],
        width: axes.size.width, height: axes.size.height, 'aria-label': 'Chart drawings',
        onPointerdown: down, onPointermove: move, onPointerup: up, onPointercancel: cancel,
        onPointerleave: () => { lastContact = null }, onLostpointercapture: e => { if (gesture?.id === e.pointerId) cancel() },
      }, drawings.value.map((shape, index) => render(shape, index, axes)))
    }
  },
}

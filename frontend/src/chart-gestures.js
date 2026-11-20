// Wheel/pinch input and its release tail share the same horizontal transform.
export function chartGestures(chart, host, volumeSeries) {
  let frame, release, lastInput = 0, priceDrag
  const clamp = (value, low, high) => Math.max(low, Math.min(high, value))
  function stop() {
    clearTimeout(release)
    cancelAnimationFrame(frame)
    lastInput = 0
    if (priceDrag && host.hasPointerCapture(priceDrag.id)) host.releasePointerCapture(priceDrag.id)
    priceDrag = null
  }
  function priceScaleAt(event, includeVolumePlot = false) {
    const rect = host.getBoundingClientRect()
    const overAxis = event.clientX - rect.left >= chart.timeScale().width()
    if (!overAxis && !includeVolumePlot) return null
    const volumePane = volumeSeries.getPane().paneIndex()
    const pane = chart.panes().find((pane, index) => {
      if (!overAxis && index !== volumePane) return false
      const bounds = pane.getHTMLElement()?.getBoundingClientRect()
      return bounds && event.clientY >= bounds.top && event.clientY < bounds.bottom
    })
    return pane ? { scale: pane.priceScale('right'), anchorZero: pane.paneIndex() === volumePane } : null
  }
  function scalePrices({ scale, anchorZero }, range, factor) {
    if (anchorZero) {
      const top = range.to * factor
      if (Number.isFinite(top) && top > 0) scale.setVisibleRange({ from: 0, to: top })
      return
    }
    const center = (range.from + range.to) / 2
    const half = (range.to - range.from) * factor / 2
    if (Number.isFinite(half) && half > 0) scale.setVisibleRange({ from: center - half, to: center + half })
  }
  function pointerDown(event) {
    stop()
    if (event.button !== 0) return
    const scale = priceScaleAt(event), range = scale?.scale.getVisibleRange()
    if (!range) return
    priceDrag = { id: event.pointerId, y: event.clientY, scale, range }
    host.setPointerCapture(event.pointerId)
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  function pointerMove(event) {
    if (!priceDrag || event.pointerId !== priceDrag.id) return
    scalePrices(priceDrag.scale, priceDrag.range, Math.exp(clamp((event.clientY - priceDrag.y) * 0.012, -4, 4)))
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  function pointerUp(event) {
    if (!priceDrag || event.pointerId !== priceDrag.id) return
    stop()
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  function resetPrices(event) {
    const scale = priceScaleAt(event)
    if (!scale) return
    stop()
    scale.scale.setAutoScale(true)
    event.preventDefault()
    event.stopImmediatePropagation()
  }
  function move(kind, amount, x) {
    const scale = chart.timeScale()
    const range = scale.getVisibleLogicalRange()
    if (!range || range.to <= range.from) return false
    const span = range.to - range.from
    let next
    if (kind === 'zoom') {
      const anchor = scale.coordinateToLogical(x)
      if (anchor == null) return false
      const width = clamp(span * Math.exp(amount), 8, scale.width() / scale.options().minBarSpacing)
      const offset = (anchor - range.from) / span
      next = { from: anchor - width * offset, to: anchor + width * (1 - offset) }
    } else {
      next = { from: range.from + amount, to: range.to + amount }
    }
    scale.setVisibleLogicalRange(next)
    // The chart applies this range on its next frame, so reading it back here
    // would still return the old range and incorrectly stop the release tail.
    return Math.abs(next.from - range.from) + Math.abs(next.to - range.to) > 0.00001
  }
  function wheel(event) {
    const volumeScroll = !event.ctrlKey && Math.abs(event.deltaY) >= Math.abs(event.deltaX)
    const priceScale = priceScaleAt(event, volumeScroll)
    if (priceScale && event.deltaY) {
      stop()
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? host.clientHeight : 1
      const range = priceScale.scale.getVisibleRange()
      if (range) scalePrices(priceScale, range, Math.exp(clamp(event.deltaY * unit * 0.012, -0.6, 0.6)))
      event.preventDefault()
      event.stopImmediatePropagation()
      return
    }
    const kind = event.ctrlKey || Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? 'zoom' : 'pan'
    const delta = kind === 'zoom' ? event.deltaY : event.deltaX
    const scale = chart.timeScale()
    const x = event.clientX - host.getBoundingClientRect().left
    if (!delta || !scale.getVisibleLogicalRange() || x < 0 || x > scale.width()) return
    const now = performance.now()
    const elapsed = lastInput && now - lastInput < 150 ? clamp(now - lastInput, 40, 120) : 40
    stop()
    lastInput = now
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scale.width() : 1
    const amount = kind === 'zoom'
      ? clamp(delta * unit * 0.0088, -0.48, 0.48)
      : delta * unit * 0.8 / scale.options().barSpacing
    event.preventDefault()
    event.stopImmediatePropagation()
    move(kind, amount, x)
    // A new event replaces this tail, including OS-generated momentum events.
    // Small trailing deltas therefore leave only a small additional release.
    let velocity = amount / elapsed * 0.30
    const decay = kind === 'zoom' ? 300 : 360
    release = setTimeout(() => {
      let previous = performance.now(), age = 0
      function coast(time) {
        const dt = Math.min(40, time - previous)
        previous = time
        age += dt
        const remaining = Math.exp(-dt / decay)
        const step = velocity * decay * (1 - remaining)
        velocity *= remaining
        if (!move(kind, step, x) || age >= 2200 || Math.abs(velocity) < (kind === 'zoom' ? 0.000005 : 0.0002)) return
        frame = requestAnimationFrame(coast)
      }
      frame = requestAnimationFrame(coast)
    }, 0)
  }
  host.addEventListener('wheel', wheel, { capture: true, passive: false })
  host.addEventListener('pointerdown', pointerDown, { capture: true })
  host.addEventListener('pointermove', pointerMove, { capture: true })
  host.addEventListener('pointerup', pointerUp, { capture: true })
  host.addEventListener('pointercancel', pointerUp, { capture: true })
  host.addEventListener('dblclick', resetPrices, { capture: true })
  window.addEventListener('blur', stop)
  document.addEventListener('visibilitychange', stop)
  return {
    stop,
    dispose() {
      stop()
      host.removeEventListener('wheel', wheel, { capture: true })
      host.removeEventListener('pointerdown', pointerDown, { capture: true })
      host.removeEventListener('pointermove', pointerMove, { capture: true })
      host.removeEventListener('pointerup', pointerUp, { capture: true })
      host.removeEventListener('pointercancel', pointerUp, { capture: true })
      host.removeEventListener('dblclick', resetPrices, { capture: true })
      window.removeEventListener('blur', stop)
      document.removeEventListener('visibilitychange', stop)
    },
  }
}

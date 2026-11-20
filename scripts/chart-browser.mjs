import assert from 'node:assert/strict'

export const market = page => page.locator('.market-column')
export const candleCount = page => market(page).evaluate(el => el.__vueParentComponent.props.market.candles.length)
export const selectedTime = page => market(page).evaluate(el => el.__vueParentComponent.props.market.selectedTime)

export async function hoverCandle(page, timestamp, { pin = false } = {}) {
  const time = timestamp == null ? null : Date.parse(timestamp) / 1000
  const chart = page.locator('.chart')
  await page.waitForFunction(time => {
    const m = document.querySelector('.market-column')?.__vueParentComponent?.props.market
    return m?.candles.some(c => time == null || c.time === time)
  }, time)
  await chart.scrollIntoViewIfNeeded()
  let point
  for (let attempt = 0; attempt < 10; attempt++) {
    point = await chart.evaluate(async (el, time) => {
      // Replay can change plot height and bar spacing as a receipt arrives.
      await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))
      const m = el.closest('.market-column').__vueParentComponent.props.market
      const { scale, size } = m.drawingAxes()
      const target = time ?? m.latest.time
      const x = scale.timeToCoordinate(target)
      if (x == null || x < 0 || x >= size.width) {
        const index = m.candles.findIndex(c => c.time === target)
        scale.setVisibleLogicalRange({ from: index - 5, to: index + 5 })
        return null
      }
      const box = el.getBoundingClientRect()
      return { x: box.left + x, y: box.top + size.height / 2, target }
    }, time)
    if (!point) continue
    await page.mouse.move(point.x, point.y + 3)
    await page.mouse.move(point.x, point.y)
    const hovered = await market(page).evaluate(el => el.__vueParentComponent.props.market.hoveredCandle?.time)
    if (hovered === point.target) break
    point = null
  }
  assert(point, 'Expected the requested candle under the chart pointer')
  const { x, y, target } = point
  const card = page.locator('.hover-card')
  await card.waitFor()
  if (pin) {
    await page.mouse.click(x, y)
    // Lightweight Charts can consume a rapid second click while checking for a double-click.
    if (await selectedTime(page) !== target) await page.mouse.click(x, y)
    assert.equal(await selectedTime(page), target)
  }
  return card
}

export const pinCandle = (page, timestamp) => hoverCandle(page, timestamp, { pin: true })

export async function hoverValues(card) {
  const labels = await card.locator('dt').allTextContents()
  const values = await card.locator('dd').allTextContents()
  return Object.fromEntries(labels.map((label, i) => [label, values[i]]))
}

import assert from 'node:assert/strict'

export async function checkDrawings(page, screenshot) {
  await page.getByRole('tab', { name: 'Drawing Tools' }).click()
  const layer = page.locator('.drawing-layer')
  const plot = await layer.boundingBox()
  const button = name => page.getByRole('button', { name, exact: true })
  let previousBottom = 0
  for (const name of ['Trend Line', 'Freehand', 'Eraser']) {
    const row = button(name)
    const bounds = await row.boundingBox()
    assert(bounds.y >= previousBottom && await row.locator('svg').isVisible())
    previousBottom = bounds.y + bounds.height
  }
  async function drag(x, y, dx, dy) {
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + dx, y + dy, { steps: 6 })
    await page.mouse.up()
  }
  for (const [label, type] of [['Trend Line', 'line'], ['Freehand', 'freehand']]) {
    await button(label).click()
    await drag(plot.x + 50, plot.y + plot.height / 2, 70, -20)
    const points = (await layer.locator('[data-drawing="' + type + '"]').getAttribute('points')).split(' ')
    assert(type === 'line' ? points.length === 2 : points.length > 2)
    assert.notEqual(points[0], points.at(-1))
  }
  for (const [i, ratio] of [2, 3, 4].entries()) {
    await button('1:' + ratio).click()
    const x = plot.x + 50 + 150 * i, y = plot.y + plot.height / 2
    await page.mouse.click(x, y)
    assert.equal(await layer.locator('[data-drawing="box"]').count(), i)
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x + 100, y + (i === 1 ? -80 : 80), { steps: 5 })
    await page.waitForFunction(r => {
      const rects = document.querySelectorAll('[aria-label="Risk/reward 1:' + r + '"] rect')
      if (rects.length !== 2) return false
      const [profit, stop] = Array.from(rects, node => node.getBBox())
      return Math.abs(profit.width - 100) < 1 && Math.abs(profit.height + stop.height - 80) < 1
    }, ratio, { timeout: 3000 })
    await page.mouse.up()
    const box = layer.locator('[aria-label="Risk/reward 1:' + ratio + '"]')
    async function dimensions() {
      const [profit, risk] = await box.locator('rect').evaluateAll(rects => rects.map(r => ({
        height: r.getBBox().height, width: r.getBBox().width, opacity: r.getAttribute('fill-opacity'), fill: r.getAttribute('fill'),
      })))
      assert(Math.abs(profit.height / risk.height - ratio) < 0.001)
      assert.equal(profit.opacity, '0.5'); assert.equal(risk.opacity, '0.5')
      assert.equal(profit.fill, '#047857'); assert.equal(risk.fill, '#800020')
      return risk
    }
    for (const [handle, dx, dy] of [['stop', 0, 8], ['target', 0, -8], ['width', 12, 0]]) {
      const before = await dimensions()
      const bounds = await box.locator('[data-handle="' + handle + '"]').boundingBox()
      await drag(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2, dx, dy)
      const after = await dimensions()
      assert(handle === 'width' ? after.width > before.width : after.height > before.height)
    }
    const region = box.locator('rect').first()
    const before = await region.boundingBox()
    await drag(before.x + 15, before.y + 15, 9, 7)
    const moved = await region.boundingBox()
    assert(Math.abs(moved.x - before.x - 9) < 1 && Math.abs(moved.y - before.y - 7) < 1)
    assert(Math.abs(moved.height - before.height) < 1 && Math.abs(moved.width - before.width) < 1)

  }
  await page.screenshot({path: screenshot})
  const last = layer.locator('[aria-label="Risk/reward 1:4"]')
  const before = await last.boundingBox()
  await button('Eraser').click()
  await page.mouse.move(before.x + 10, before.y + 10)
  assert.equal(await last.count(), 0)
  await page.keyboard.press('Meta+z')
  assert.equal(await last.count(), 1)
  await button('Eraser').click()
  await page.keyboard.press('Control+z') // move
  const restored = await last.boundingBox()
  assert(Math.abs(before.x - restored.x - 9) < 1)
  for (let i = 0; i < 4; i++) await page.keyboard.press('Control+z') // three resizes and creation
  assert.equal(await last.count(), 0)
  assert.equal(await layer.locator('[data-drawing="box"]').count(), 2)
  await button('Eraser').click()
  await page.mouse.move(plot.x + 30, plot.y + plot.height / 2 - 10)
  await page.mouse.move(plot.x + 80, plot.y + plot.height / 2 - 10)
  assert.equal(await layer.locator('polyline[data-drawing]').count(), 0)
  await page.keyboard.press('Control+z')
  await page.keyboard.press('Control+z')
  assert.equal(await layer.locator('polyline[data-drawing]').count(), 2)
}

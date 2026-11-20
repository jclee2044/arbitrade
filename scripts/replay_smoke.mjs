import { candleCount, hoverCandle, hoverValues } from './chart-browser.mjs'
import assert from 'node:assert/strict'
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs'
import { resolve } from 'node:path'
const output = process.argv[2]
const selection = JSON.parse(process.argv[3])
const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 1050 } })
const errors = []
const checks = []
page.on('pageerror', (error) => errors.push(error.message))
async function until(test) {
  for (let i = 0; i < 100; i++) {
    if (await test()) return
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Timed out waiting for replay UI')
}
async function values() {
  return hoverValues(await hoverCandle(page))
}
const usd = value => Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })
try {
  await page.goto('http://127.0.0.1:15173', { waitUntil: 'networkidle' })
  await page.locator('.feed-details summary').click()
  await page.getByText('Feed: disabled', { exact: false }).waitFor()
  checks.push('Backend started with live Yahoo feed disabled')
  await page.locator('#mode').selectOption('replay')
  await page.locator('#replay-symbol option').first().waitFor({ state: 'attached' })
  if (selection.constructed) {
    assert.equal(await page.locator('#replay-start').inputValue(), '2026-11-10T09:59:59.000000-05:00')
    assert.equal(await page.locator('#replay-end').inputValue(), '2026-11-10T10:01:02.000000-05:00')
    checks.push('Replay starts and ends at the same saved receipts with Eastern offsets and microsecond precision')
  } else {
    await page.locator('#replay-start').fill(selection.start)
    await page.locator('#replay-end').fill(selection.end)
  }
  const runs = []
  for (let run = 0; run < 2; run++) {
    await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
    await until(async () => (await page.locator('#replay-status').textContent()) === `0 / ${selection.total} receipts`)
    for (let step = 1; step <= selection.total; step++) {
      await page.getByRole('button', { name: 'Next observation', exact: true }).click()
      await until(async () => (await page.locator('#replay-status').textContent()).startsWith(`${step} /`))
      if (selection.constructed && step === 2) assert.equal((await values()).Close, '$100.00')
      if (selection.constructed && step === 3) assert.equal((await values()).Open, '$100.00')
      if (selection.constructed && step === 4) {
        assert.equal((await values()).Open, '$98.00')
        assert.match(await page.locator('#replay-time').textContent(), /10:00:10.*ET.*10:01:01.*ET/)
      }
    }
    const visible = await values()
    assert.equal(visible.Close, usd(selection.close))
    assert.equal((visible['Observed volume'] ?? visible.Volume), selection.volume === 'Unknown' ? undefined : selection.volume.replace(' shares', ''))
    runs.push(visible)
    await page.screenshot({ path: resolve(output, `replay-${run + 1}.png`), fullPage: true })
  }
  if (selection.constructed) await page.getByText('Source: Replay · CONSTRUCTED test_data=true', { exact: false }).waitFor()
  assert.deepEqual(runs[0], runs[1])
  checks.push('Two UI replays show identical OHLCV; close and volume match SQLite expectations')
  if (selection.constructed) checks.push('Late revision appears only at its receipt step; repeated payload does not change volume')
  await page.getByRole('heading', { name: 'Replay · AAPL · 1m candles', exact: true }).waitFor()
  for (const frame of ['5m','30m','1w','1mo']) {
    await page.locator('[data-frame="' + frame + '"]').click()
    await until(async () => (await page.locator('#replay-status').textContent()).startsWith('0 /'))
    await page.getByRole('button', { name: 'Play replay', exact: true }).click()
    await until(async () => (await page.locator('#replay-status').textContent()).includes('Finished'))
    assert.equal((await values()).Close, usd(selection.close))
  }
  checks.push('5-minute, 30-minute, weekly and monthly replay preserve the recorded close')
  await page.locator('#replay-start').fill('2020-01-01T00:00:00Z')
  await page.locator('#replay-end').fill('2020-01-02T00:00:00Z')
  await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
  await page.getByText('This selection has no recorded observations.', { exact: true }).waitFor()
  assert.equal(await candleCount(page), 0)
  checks.push('Empty selection visibly explains that no recorded observations exist')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify(checks))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close()
}

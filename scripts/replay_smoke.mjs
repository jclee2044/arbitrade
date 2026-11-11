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
  const keys = await page.locator('.candle-values dt').allTextContents()
  const rows = await page.locator('.candle-values dd').allTextContents()
  return Object.fromEntries(keys.map((key, i) => [key, rows[i]]))
}
try {
  await page.goto('http://127.0.0.1:15173', { waitUntil: 'networkidle' })
  await page.getByText('Feed: disabled', { exact: false }).waitFor()
  checks.push('Backend started with live Yahoo feed disabled')
  await page.locator('#mode').selectOption('replay')
  await page.locator('#replay-symbol option').first().waitFor({ state: 'attached' })
  await page.locator('#replay-start').fill(selection.start)
  await page.locator('#replay-end').fill(selection.end)
  const runs = []
  for (let run = 0; run < 2; run++) {
    await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
    await until(async () => (await page.locator('#replay-status').textContent()) === `0 / ${selection.total} receipts`)
    for (let step = 1; step <= selection.total; step++) {
      await page.getByRole('button', { name: 'Next observation', exact: true }).click()
      await until(async () => (await page.locator('#replay-status').textContent()).startsWith(`${step} /`))
      if (selection.constructed && step === 2) assert.equal((await values()).Close, '100')
      if (selection.constructed && step === 3) assert.equal((await values()).Open, '100')
      if (selection.constructed && step === 4) {
        assert.equal((await values()).Open, '98')
        assert.match(await page.locator('#replay-time').textContent(), /15:00:10.*15:01:01/)
      }
    }
    const visible = await values()
    assert.equal(visible.Close, selection.close)
    assert.equal(visible.Volume, selection.volume)
    runs.push(visible)
    await page.screenshot({ path: resolve(output, `replay-${run + 1}.png`), fullPage: true })
  }
  if (selection.constructed) await page.getByText('Source: Replay · CONSTRUCTED test_data=true', { exact: false }).waitFor()
  assert.deepEqual(runs[0], runs[1])
  checks.push('Two UI replays show identical OHLCV; close and volume match SQLite expectations')
  if (selection.constructed) checks.push('Late revision appears only at its receipt step; repeated payload does not change volume')
  await page.getByRole('heading', { name: 'Replay · AAPL · 1m candles', exact: true }).waitFor()
  // Exercise automatic playback and an alternate timeframe.
  await page.locator('#timeframe').selectOption('5m')
  await until(async () => (await page.locator('#replay-status').textContent()).startsWith('0 /'))
  await page.getByRole('button', { name: 'Play replay', exact: true }).click()
  await until(async () => (await page.locator('#replay-status').textContent()).includes('Finished'))
  assert.equal((await values()).Close, selection.close)
  checks.push('Play replay and timeframe change work')
  await page.locator('#replay-start').fill('2020-01-01T00:00:00Z')
  await page.locator('#replay-end').fill('2020-01-02T00:00:00Z')
  await page.getByRole('button', { name: 'Load / restart replay', exact: true }).click()
  await page.getByText('This selection has no recorded observations.', { exact: true }).waitFor()
  assert.equal(await page.locator('#candle-time').count(), 0)
  checks.push('Empty selection visibly explains that no recorded observations exist')
  assert.deepEqual(errors, [])
  console.log(JSON.stringify(checks))
} catch (error) {
  await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close()
}

export const periods = [10, 20, 30, 50, 100, 200]
export const timeframes = { '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1hr', '1d': 'D', '1w': 'W', '1mo': 'M' }
export const movingAverageColors = { sma: '#307492', ema: '#c87519' }
const customColors = ['#705780', '#0e7490', '#a24051', '#4d7137']

export function studyColor(item) {
  return movingAverageColors[item.type] || customColors[item.id % customColors.length]
}

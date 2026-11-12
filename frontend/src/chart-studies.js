export const periods = [10, 20, 30, 50, 100, 200]
export const timeframes = { '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1hr', '1d': 'D', '1w': 'W', '1mo': 'M' }
const periodColors = { 10: '#387457', 20: '#307492', 30: '#97691c', 50: '#705780', 100: '#52666f', 200: '#81394e' }
const customColors = ['#705780', '#0e7490', '#a24051', '#4d7137']

export function periodColor(period, fallback = '#307492') {
  return periodColors[period] || fallback
}

export function studyColor(item) {
  return item.preset ? periodColor(item.settings.window) : customColors[item.id % customColors.length]
}

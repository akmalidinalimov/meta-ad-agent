import { describe, expect, it } from 'vitest'
import {
  chartTooltipFormatter,
  formatAxisCurrency,
  formatChartCurrency,
  formatChartNumber,
} from './chartConfig'

describe('chartConfig formatters', () => {
  it('formats whole-dollar currency for labels', () => {
    expect(formatChartCurrency(1234)).toBe('$1,234')
  })

  it('formats compact currency for dense axis ticks', () => {
    expect(formatAxisCurrency(1200)).toMatch(/\$1\.2K/i)
    expect(formatAxisCurrency('not-a-number')).toBe('not-a-number')
  })

  it('formats counts with grouping separators', () => {
    expect(formatChartNumber(12345)).toBe('12,345')
  })

  it('formats monetary series as currency and counts otherwise', () => {
    expect(chartTooltipFormatter(1000, 'Spend')).toEqual(['$1,000', 'Spend'])
    expect(chartTooltipFormatter(42, 'Leads')).toEqual(['42', 'Leads'])
  })

  it('tolerates undefined and array inputs from recharts', () => {
    expect(chartTooltipFormatter(undefined, undefined)).toEqual(['0', ''])
    expect(chartTooltipFormatter([7, 9], 'Buyers')).toEqual(['7', 'Buyers'])
  })
})

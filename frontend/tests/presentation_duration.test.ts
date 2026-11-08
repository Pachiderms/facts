import { describe, expect, it } from 'vitest'
import { formatDuration } from '../src/lib/presentation'

describe('formatDuration', () => {
  it.each([
    [0, '0 s'],
    [30, '30 s'],
    [59, '59 s'],
    [60, '1 min'],
    [61, '2 min'],
    [2_520, '42 min'],
    [3_599, '60 min'],
    [3_600, '1 h'],
    [3_660, '1 h 1 min'],
    [7_200, '2 h'],
    [-5, '0 s'],
  ])('%s s -> %s', (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text)
  })
})

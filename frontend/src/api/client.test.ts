import { describe, expect, it } from 'vitest'
import { queryString } from './client'

describe('queryString', () => {
  it('omits empty values and encodes valid filters', () => {
    expect(queryString({ limit: 50, status: 'running', path: '', enabled: false, missing: undefined }))
      .toBe('?limit=50&status=running&enabled=false')
  })
})

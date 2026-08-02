import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProgressBar, SeverityBadge, StatusBadge } from './UI'

describe('shared UI', () => {
  it('formats status and severity labels', () => {
    render(<><StatusBadge status="in_progress" /><SeverityBadge severity="critical" /></>)
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('clamps progress values', () => {
    render(<ProgressBar value={150} />)
    expect(screen.getByLabelText('100% complete')).toBeInTheDocument()
  })
})

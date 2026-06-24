/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ChatMessageContent } from './ChatMessageContent'

describe('ChatMessageContent', () => {
  it('splits blank-line-separated text into separate paragraphs', () => {
    const { container } = render(<ChatMessageContent content={'First para.\n\nSecond para.'} />)
    expect(container.querySelectorAll('p')).toHaveLength(2)
  })

  it('renders bullet lines as a list, stripping -, •, and * markers', () => {
    const { container } = render(<ChatMessageContent content={'- one\n• two\n* three'} />)
    expect(container.querySelectorAll('ul')).toHaveLength(1)
    expect(container.querySelectorAll('li')).toHaveLength(3)
    expect(screen.getByText('one')).toBeInTheDocument()
    expect(screen.getByText('three')).toBeInTheDocument()
  })

  it('renders **bold** as <strong> with the markers removed', () => {
    render(<ChatMessageContent content={'CPL is **0.04** today.'} />)
    const strong = screen.getByText('0.04')
    expect(strong.tagName).toBe('STRONG')
  })

  it('preserves single newlines within a block as <br> so numbered lists stay structured', () => {
    const { container } = render(<ChatMessageContent content={'Top ad sets:\n1. Alpha\n2. Beta'} />)
    expect(container.querySelectorAll('p')).toHaveLength(1)
    expect(container.querySelectorAll('br')).toHaveLength(2)
  })

  it('leaves an unmatched asterisk as plain text without crashing', () => {
    render(<ChatMessageContent content={'scale 5 * budget'} />)
    expect(screen.getByText(/scale 5 \* budget/)).toBeInTheDocument()
  })

  it('renders nothing for empty or whitespace-only content', () => {
    const { container } = render(<ChatMessageContent content={'   '} />)
    expect(container.querySelector('.chat-rich')).toBeNull()
  })
})

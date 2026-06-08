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

  it('joins soft-wrapped lines within a paragraph into one <p>', () => {
    const { container } = render(<ChatMessageContent content={'line one\nline two'} />)
    expect(container.querySelectorAll('p')).toHaveLength(1)
    expect(container.querySelector('p')?.textContent).toBe('line one line two')
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

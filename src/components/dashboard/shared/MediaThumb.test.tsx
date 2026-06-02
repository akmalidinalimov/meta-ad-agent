/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MediaThumb } from './MediaThumb'

describe('MediaThumb', () => {
  it('renders Meta thumbnails and marks video assets even when a direct source URL is missing', () => {
    const { container } = render(<MediaThumb assetUrl="https://example.com/thumb.jpg" videoId="12345" format="video" />)

    expect(screen.getByLabelText(/video creative preview with video asset/i)).toBeInTheDocument()
    expect(container.querySelector('img')).toHaveAttribute('src', 'https://example.com/thumb.jpg')
    expect(screen.getByLabelText(/video asset available/i)).toBeInTheDocument()
  })

  it('marks directly playable videos distinctly', () => {
    render(<MediaThumb videoUrl="https://example.com/video.mp4" format="video" />)

    expect(screen.getByLabelText(/playable video/i)).toBeInTheDocument()
  })
})

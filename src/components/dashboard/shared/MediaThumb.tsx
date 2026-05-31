import { Film } from 'lucide-react'
import type { Creative } from '../../../types/marketing'

interface MediaThumbProps {
  assetUrl?: string
  videoUrl?: string
  videoId?: string
  format: Creative['format']
}

export function MediaThumb({ assetUrl, videoUrl, videoId, format }: MediaThumbProps) {
  const hasPlayableVideo = Boolean(videoUrl)

  return (
    <span className={`creative-thumb ${assetUrl ? 'has-image' : ''}`} aria-label={`${format} creative preview`}>
      {assetUrl ? <img src={assetUrl} alt="" loading="lazy" /> : <Film size={18} />}
      {hasPlayableVideo && <i aria-label="Playable video">▶</i>}
      {!hasPlayableVideo && videoId && <span title="Video ID exists, but source URL is unavailable">ID</span>}
      {!assetUrl && <small>{format}</small>}
    </span>
  )
}

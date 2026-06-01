import { Film } from 'lucide-react'
import type { Creative } from '../../../types/marketing'

interface MediaThumbProps {
  assetUrl?: string
  videoUrl?: string
  videoId?: string
  format: Creative['format']
}

export function MediaThumb({ assetUrl, videoUrl, videoId, format }: MediaThumbProps) {
  const hasVideoAsset = Boolean(videoUrl || videoId)

  return (
    <span
      className={`creative-thumb ${assetUrl ? 'has-image' : ''} ${hasVideoAsset ? 'has-video' : ''}`}
      aria-label={`${format} creative preview${hasVideoAsset ? ' with video asset' : ''}`}
    >
      {assetUrl ? <img src={assetUrl} alt="" loading="lazy" /> : <Film size={18} />}
      {hasVideoAsset && <i aria-label={videoUrl ? 'Playable video' : 'Video asset available'}>▶</i>}
      {!assetUrl && <small>{format}</small>}
    </span>
  )
}

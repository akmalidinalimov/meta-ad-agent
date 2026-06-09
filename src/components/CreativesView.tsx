import { useEffect, useState } from 'react'

type CreativePerf = {
  impressions: number
  clicks: number
  spend: number
  ctr: number
  results: number
  resultsLabel: string | null
  hasData: boolean
}

type Creative = {
  id: string
  name: string | null
  status: string | null
  thumbnailUrl: string | null
  imageUrl: string | null
  title: string | null
  body: string | null
  videoId: string | null
  objectType: string | null
  perf: CreativePerf
}

type CreativesResponse = {
  configured: boolean
  adsetId: string
  adsetName: string | null
  campaignName: string | null
  source: string
  adsManagerUrl: string | null
  creatives: Creative[]
  error: string | null
}

const money = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const int = (n: number) => n.toLocaleString()

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: '#161b22', borderRadius: 8, padding: '8px 10px', minWidth: 84 }}>
      <div style={{ fontSize: 11, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: '#e6edf3' }}>{value}</div>
    </div>
  )
}

function CreativeCard({ creative }: { creative: Creative }) {
  const { perf } = creative
  const img = creative.imageUrl || creative.thumbnailUrl
  const watchUrl = creative.videoId ? `https://www.facebook.com/watch/?v=${creative.videoId}` : null
  return (
    <div
      style={{
        background: '#0d1117',
        border: '1px solid #30363d',
        borderRadius: 12,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div style={{ position: 'relative', background: '#161b22', aspectRatio: '1 / 1', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {img ? (
          <img src={img} alt={creative.name ?? 'creative'} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <span style={{ color: '#8b949e', fontSize: 13 }}>No thumbnail</span>
        )}
        {creative.objectType === 'VIDEO' && (
          <span style={{ position: 'absolute', top: 8, right: 8, background: 'rgba(0,0,0,0.6)', color: '#fff', borderRadius: 6, padding: '2px 6px', fontSize: 11 }}>▶ Video</span>
        )}
      </div>
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'baseline' }}>
          <strong style={{ color: '#e6edf3', fontSize: 14, lineHeight: 1.3 }}>{creative.name ?? 'Creative'}</strong>
          <span style={{ color: '#8b949e', fontSize: 11, whiteSpace: 'nowrap' }}>{creative.status ?? ''}</span>
        </div>
        {creative.title && <div style={{ color: '#c9d1d9', fontSize: 13 }}>{creative.title}</div>}
        {creative.body && (
          <div style={{ color: '#8b949e', fontSize: 12, lineHeight: 1.4, maxHeight: 72, overflow: 'hidden' }}>{creative.body}</div>
        )}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {perf.hasData ? (
            <>
              <StatCard label="Spend" value={money(perf.spend)} />
              <StatCard label="Impr." value={int(perf.impressions)} />
              <StatCard label="Clicks" value={int(perf.clicks)} />
              <StatCard label="CTR" value={`${perf.ctr.toFixed(2)}%`} />
              {perf.results > 0 && <StatCard label={perf.resultsLabel ?? 'Results'} value={int(perf.results)} />}
            </>
          ) : (
            <span style={{ color: '#8b949e', fontSize: 12 }}>No delivery data yet.</span>
          )}
        </div>
        {watchUrl && (
          <a href={watchUrl} target="_blank" rel="noreferrer" style={{ color: '#58a6ff', fontSize: 12 }}>
            ▶ Watch video
          </a>
        )}
      </div>
    </div>
  )
}

export function CreativesView({ adsetId }: { adsetId: string }) {
  const [data, setData] = useState<CreativesResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    fetch(`/api/meta/adsets/${encodeURIComponent(adsetId)}/creatives`, { credentials: 'same-origin' })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return (await res.json()) as CreativesResponse
      })
      .then((json) => {
        if (mounted) {
          setData(json)
          setError(null)
        }
      })
      .catch((err) => {
        if (mounted) setError(err instanceof Error ? err.message : 'Failed to load creatives')
      })
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => {
      mounted = false
    }
  }, [adsetId])

  return (
    <main className="app-shell" style={{ padding: 16, color: '#e6edf3', maxWidth: 900, margin: '0 auto' }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, margin: '0 0 4px' }}>🖼 Creatives</h1>
        {data && (
          <div style={{ color: '#8b949e', fontSize: 13 }}>
            {data.adsetName ?? `Ad set ${adsetId}`}
            {data.campaignName ? ` · ${data.campaignName}` : ''}
            {data.source !== 'live' ? ' · (as of last sync)' : ''}
          </div>
        )}
        {data?.adsManagerUrl && (
          <a href={data.adsManagerUrl} target="_blank" rel="noreferrer" style={{ color: '#58a6ff', fontSize: 13 }}>
            Open in Ads Manager →
          </a>
        )}
      </header>

      {loading && <div className="loading-panel">Loading creatives…</div>}
      {error && !loading && <div style={{ color: '#f85149' }}>Couldn't load creatives: {error}</div>}
      {data && !loading && data.creatives.length === 0 && (
        <div style={{ color: '#8b949e' }}>No creatives found for this ad set.</div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 14,
        }}
      >
        {data?.creatives.map((c) => (
          <CreativeCard key={c.id} creative={c} />
        ))}
      </div>
    </main>
  )
}

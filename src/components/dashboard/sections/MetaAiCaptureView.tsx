import { useEffect, useMemo, useState } from 'react'
import { Sparkles, ShieldCheck } from 'lucide-react'
import { PanelHeading } from '../shared/PanelHeading'
import {
  createMetaAiCapture,
  getMetaAiCaptures,
  type MetaAiCapture,
  type MetaAiScores,
} from '../../../services/metaAiProvider'

const SCORE_LABELS: Record<keyof MetaAiScores, string> = {
  specificity: 'Specificity',
  metricAccuracy: 'Metric accuracy',
  actionability: 'Actionability',
  businessRealism: 'Business realism',
  riskAwareness: 'Risk awareness',
}

function toneForScore(value: number): 'good' | 'warning' | 'danger' {
  return value >= 70 ? 'good' : value >= 45 ? 'warning' : 'danger'
}

export function MetaAiCaptureView() {
  const [captures, setCaptures] = useState<MetaAiCapture[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sourceText, setSourceText] = useState('')
  const [campaignName, setCampaignName] = useState('')
  const [objectLevel, setObjectLevel] = useState('campaign')
  const [isSaving, setIsSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void getMetaAiCaptures()
      .then((rows) => {
        if (cancelled) return
        setCaptures(rows)
        setSelectedId((current) => current ?? rows[0]?.id ?? null)
      })
      .catch(() => {
        if (!cancelled) setMessage('Could not load saved captures. Is the backend running?')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const selected = useMemo(
    () => captures.find((capture) => capture.id === selectedId) ?? captures[0],
    [captures, selectedId],
  )

  const submit = async () => {
    if (!sourceText.trim() || isSaving) return
    setIsSaving(true)
    setMessage('Analyzing the Meta AI capture...')
    try {
      const capture = await createMetaAiCapture({
        sourceText,
        campaignName: campaignName.trim() || undefined,
        objectLevel,
      })
      setCaptures((current) => [capture, ...current.filter((row) => row.id !== capture.id)])
      setSelectedId(capture.id)
      setSourceText('')
      setMessage('Capture analyzed. Nothing was published or changed in Meta.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not analyze the capture.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <section className="detail-layout">
      <article className="panel panel-wide">
        <PanelHeading eyebrow="Meta AI Capture" title="Paste Ads Manager AI output to validate it" icon={Sparkles} />
        <p className="muted-note">
          The browser automation policy blocks adsmanager.facebook.com, so paste the Meta AI "Analyze" text (or
          screenshot-derived text) here. The Advisor summarizes it and the Strategist scores it against your 180-day
          knowledge base and business context. This never publishes or spends.
        </p>
        <div className="meta-ai-form">
          <label>
            Campaign (optional, for metric comparison)
            <input
              type="text"
              value={campaignName}
              placeholder="e.g. DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"
              onChange={(event) => setCampaignName(event.target.value)}
            />
          </label>
          <label>
            Object level
            <select value={objectLevel} onChange={(event) => setObjectLevel(event.target.value)}>
              <option value="campaign">Campaign</option>
              <option value="adset">Ad set</option>
              <option value="ad">Ad</option>
              <option value="account">Account</option>
            </select>
          </label>
          <label className="meta-ai-textarea">
            Meta AI text / screenshot text
            <textarea
              rows={7}
              value={sourceText}
              placeholder="Paste exactly what the Meta AI Analyze panel said..."
              onChange={(event) => setSourceText(event.target.value)}
            />
          </label>
          <button type="button" className="primary-button" onClick={submit} disabled={isSaving || !sourceText.trim()}>
            {isSaving ? 'Analyzing...' : 'Analyze capture'}
          </button>
          {message && <p className="meta-ai-message">{message}</p>}
        </div>

        {captures.length > 0 && (
          <div className="meta-ai-history">
            <h3>Saved captures</h3>
            {captures.map((capture) => (
              <button
                type="button"
                key={capture.id}
                className={`meta-ai-history-row ${capture.id === selected?.id ? 'active' : ''}`}
                onClick={() => setSelectedId(capture.id)}
              >
                <strong>{capture.campaignName || capture.objectLevel || 'Capture'}</strong>
                <small>{new Date(capture.createdAt).toLocaleString()}</small>
                <em className={capture.analysis.advisor.trustLevel}>{capture.analysis.advisor.trustLevel} trust</em>
              </button>
            ))}
          </div>
        )}
      </article>

      <article className="panel detail-panel">
        <PanelHeading eyebrow="Advisor + Strategist" title="Validation result" icon={ShieldCheck} />
        {selected ? <MetaAiResult capture={selected} /> : <p className="muted-note">No capture selected yet.</p>}
      </article>
    </section>
  )
}

function MetaAiResult({ capture }: { capture: MetaAiCapture }) {
  const { advisor, strategist } = capture.analysis
  return (
    <div className="meta-ai-result">
      <div className="meta-ai-overall">
        <span className={`trust-badge ${advisor.trustLevel}`}>Trust: {advisor.trustLevel}</span>
        <span className={`trust-badge ${toneForScore(strategist.overallScore)}`}>Overall {strategist.overallScore}/100</span>
        {strategist.campaign && <span className="trust-badge neutral">{strategist.campaign.name}</span>}
      </div>

      <div className="meta-ai-score-grid">
        {(Object.keys(SCORE_LABELS) as (keyof MetaAiScores)[]).map((key) => {
          const value = strategist.scores[key]
          return (
            <div className="meta-ai-score" key={key}>
              <div className="meta-ai-score-head">
                <small>{SCORE_LABELS[key]}</small>
                <strong>{value}</strong>
              </div>
              <div className="meta-ai-score-track">
                <i className={toneForScore(value)} style={{ width: `${value}%` }} />
              </div>
            </div>
          )
        })}
      </div>

      <MetaAiList title="What Meta AI recommended" items={advisor.recommendationSummary} />
      <MetaAiChips title="Evidence it used" items={advisor.evidenceUsed} empty="No delivery metrics detected." />
      <MetaAiChips title="What it missed" items={advisor.whatItMissed} tone="danger" empty="Covered the key signals." />
      <MetaAiList title="Strategist counterpoints" items={strategist.businessCounterpoints} />
      <MetaAiList title="Compared against" items={strategist.comparedAgainst} muted />
    </div>
  )
}

function MetaAiList({ title, items, muted }: { title: string; items: string[]; muted?: boolean }) {
  if (items.length === 0) return null
  return (
    <div className={`meta-ai-block ${muted ? 'muted' : ''}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function MetaAiChips({ title, items, tone, empty }: { title: string; items: string[]; tone?: string; empty: string }) {
  return (
    <div className="meta-ai-block">
      <strong>{title}</strong>
      {items.length === 0 ? (
        <p className="muted-note">{empty}</p>
      ) : (
        <div className="meta-ai-chips">
          {items.map((item) => (
            <span key={item} className={`chip ${tone ?? ''}`}>
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

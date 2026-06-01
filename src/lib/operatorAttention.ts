import type { DashboardData, Tone } from '../types/marketing'

export interface OperatorAttentionItem {
  id: string
  source: string
  title: string
  reason: string
  action: string
  tone: Tone
  priority: number
}

export function buildOperatorAttention(data: DashboardData): OperatorAttentionItem[] {
  const items: OperatorAttentionItem[] = []

  for (const alert of data.monitoringAlerts ?? []) {
    items.push({
      id: `alert-${alert.id}`,
      source: 'Monitoring',
      title: alert.title,
      reason: alert.whyItMatters || alert.metricDeltas ? 'Metric movement needs review.' : 'Monitoring rule triggered.',
      action: alert.recommendedActions[0] || 'Review this alert before changing budget.',
      tone: alert.severity === 'high' ? 'danger' : alert.severity === 'medium' ? 'warning' : 'neutral',
      priority: alert.severity === 'high' ? 100 : alert.severity === 'medium' ? 80 : 50,
    })
  }

  for (const item of data.campaignWatch ?? []) {
    items.push({
      id: `watch-${item.campaignId}`,
      source: 'Campaign Watch',
      title: item.decision,
      reason: `${item.campaignName}: ${item.reason}`,
      action: item.nextActions[0] || 'Wait for the next monitoring interval.',
      tone: item.tone,
      priority: item.tone === 'danger' ? 95 : item.tone === 'warning' ? 75 : item.tone === 'good' ? 25 : 45,
    })
  }

  for (const tracking of data.trackingHealth ?? []) {
    if (tracking.status === 'healthy') {
      continue
    }
    items.push({
      id: `tracking-${tracking.name}`,
      source: 'Tracking',
      title: `${tracking.name} is ${tracking.status}`,
      reason: tracking.note,
      action: tracking.status === 'broken' ? 'Fix this before scaling or judging traffic quality.' : 'Check event mapping and match rate.',
      tone: tracking.status === 'broken' ? 'danger' : 'warning',
      priority: tracking.status === 'broken' ? 90 : 65,
    })
  }

  for (const approval of data.approvalActions ?? []) {
    if (!['needs_review', 'ready', 'blocked'].includes(approval.status)) {
      continue
    }
    items.push({
      id: `approval-${approval.id}`,
      source: 'Approval',
      title: approval.title,
      reason: approval.impact,
      action: approval.status === 'blocked' ? 'Resolve blocker before approval.' : 'Review and approve or request changes.',
      tone: approval.risk === 'high' || approval.status === 'blocked' ? 'danger' : approval.risk === 'medium' ? 'warning' : 'neutral',
      priority: approval.risk === 'high' || approval.status === 'blocked' ? 70 : approval.risk === 'medium' ? 55 : 35,
    })
  }

  for (const insight of data.insights ?? []) {
    items.push({
      id: `insight-${insight.title}`,
      source: 'Agent Insight',
      title: insight.title,
      reason: insight.body,
      action: 'Ask the orchestrator to turn this into an experiment or approval request.',
      tone: insight.tone,
      priority: insight.tone === 'danger' ? 60 : insight.tone === 'warning' ? 45 : 15,
    })
  }

  return items
    .sort((a, b) => b.priority - a.priority)
    .slice(0, 8)
}

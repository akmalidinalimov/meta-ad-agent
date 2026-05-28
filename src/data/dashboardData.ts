import {
  audienceScores,
  adSets,
  ads,
  approvalActions,
  campaigns,
  creativeAnalyses,
  creatives,
  dailyMetrics,
  dashboardKpis,
  experiments,
  glossary,
  insights,
  trackingHealth,
} from './mockMarketingData'
import { composeDashboardData } from '../lib/analytics'

export const dashboardData = composeDashboardData({
  campaigns,
  adSets,
  ads,
  metrics: dailyMetrics,
  creatives,
  analyses: creativeAnalyses,
  kpis: dashboardKpis,
  audience: audienceScores,
  insights,
  experiments,
  trackingHealth,
  approvalActions,
  glossary,
})

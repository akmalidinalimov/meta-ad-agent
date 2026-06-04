import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Target,
  TrendingDown as TrendingDownIcon,
  TrendingUp,
  Users,
} from 'lucide-react'
import type { ComponentType } from 'react'
import type { IconName } from '../../types/marketing'

// Sourced from the --chart-* custom properties in index.css so the chart palette
// tracks the design tokens (incl. dark mode) in one place.
export const COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
]

export const iconMap: Record<IconName, ComponentType<{ size?: number }>> = {
  alert: AlertTriangle,
  bot: Bot,
  check: CheckCircle2,
  dollar: CircleDollarSign,
  target: Target,
  trendingDown: TrendingDownIcon,
  trendingUp: TrendingUp,
  users: Users,
}

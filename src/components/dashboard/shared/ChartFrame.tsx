import type { ReactNode } from 'react'
import { ResponsiveContainer } from 'recharts'

interface ChartFrameProps {
  children: ReactNode
  tall?: boolean
  /**
   * A one-line text alternative describing the chart's data, exposed to
   * assistive technology via role="img" + aria-label. Without it the chart is
   * an opaque, unlabeled region for screen-reader users.
   */
  summary?: string
}

export function ChartFrame({ children, tall = false, summary }: ChartFrameProps) {
  const initialDimension = tall ? { width: 720, height: 318 } : { width: 640, height: 268 }

  const accessibilityProps = summary ? { role: 'img' as const, 'aria-label': summary } : {}

  return (
    <div className={tall ? 'chart-box tall' : 'chart-box'} {...accessibilityProps}>
      <ResponsiveContainer
        width="100%"
        height="100%"
        minWidth={0}
        minHeight={0}
        initialDimension={initialDimension}
      >
        {children}
      </ResponsiveContainer>
    </div>
  )
}

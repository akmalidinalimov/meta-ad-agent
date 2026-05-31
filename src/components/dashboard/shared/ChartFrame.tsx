import type { ReactNode } from 'react'
import { ResponsiveContainer } from 'recharts'

interface ChartFrameProps {
  children: ReactNode
  tall?: boolean
}

export function ChartFrame({ children, tall = false }: ChartFrameProps) {
  const initialDimension = tall ? { width: 720, height: 318 } : { width: 640, height: 268 }

  return (
    <div className={tall ? 'chart-box tall' : 'chart-box'}>
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

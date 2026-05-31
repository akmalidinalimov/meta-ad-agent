import type { ComponentType } from 'react'

interface PanelHeadingProps {
  eyebrow: string
  title: string
  icon: ComponentType<{ size?: number }>
}

export function PanelHeading({ eyebrow, title, icon: Icon }: PanelHeadingProps) {
  return (
    <div className="panel-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <Icon size={20} />
    </div>
  )
}

import type { LucideIcon } from 'lucide-react'

type NavigationItem = {
    label: string
    icon: LucideIcon
}

type DashboardSidebarProps = {
    items: NavigationItem[]
    pageName: string
    activeItem: string
    onSelect: (label: string) => void
}

const DashboardSidebar = ({
    items,
    pageName,
    activeItem,
    onSelect,
}: DashboardSidebarProps) => (
    <aside className="dashboard-sidebar">
        <span className="dashboard-sidebar-title">{pageName}</span>
        <nav aria-label="Primary navigation">
            {items.map((item) => {
                const isActive = item.label === activeItem

                return (
                    <button
                        className={`nav-item${isActive ? ' is-active' : ''}`}
                        key={item.label}
                        type="button"
                        aria-current={isActive ? 'page' : undefined}
                        onClick={() => {
                            onSelect(item.label)
                        }}
                    >
                        <span className="nav-item-icon" aria-hidden="true">
                            <item.icon size={16} strokeWidth={2.25} />
                        </span>
                        <span>{item.label}</span>
                    </button>
                )
            })}
        </nav>
    </aside>
)

export type { NavigationItem }
export default DashboardSidebar
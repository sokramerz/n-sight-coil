
import { Link } from 'react-router-dom'

const DashboardHeader = () => (
	<header className="app-header">
		<div className="app-header-brand">
			<Link className="app-header-brand-name" to="/provider">
				n-sight
			</Link>
		</div>
	</header>
)

export default DashboardHeader

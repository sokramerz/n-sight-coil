import { useNavigate } from 'react-router-dom'

const App = () => {
	const navigate = useNavigate()

	return (
		<main>
			<button type="button" onClick={() => navigate('/health')}>
				Health
			</button>
		</main>
	)
}

export default App
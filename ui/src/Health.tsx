import { useHealthQuery } from './api'

const Health = () => {
	const apiTest = useHealthQuery()

	return (
		<main>
			<p>
				Status:
				{apiTest.isSuccess && apiTest.data.status}
				{apiTest.isError && apiTest.error.message}
				{apiTest.isPending && 'Waiting for a response from the backend.'}
			</p>

			{apiTest.isSuccess && (
				<p>Endpoint: /api/health</p>
			)}

			{apiTest.isError && (
				<button type="button" onClick={() => void apiTest.refetch()}>
					Retry connection
				</button>
			)}
		</main>
	)
}

export default Health
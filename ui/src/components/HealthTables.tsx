import { usePatientHealthQuery } from '../api/queries'

const TIMING: Record<string, string> = {
	discharge: 'At discharge',
	admission: 'When you arrived',
	unstated: 'From the exam in your record',
}

// Plain tables over the Health endpoint. Layout and styling belong to the frontend team.
const HealthTables = ({ patientId }: { patientId: string }) => {
	const healthQuery = usePatientHealthQuery(patientId)

	if (healthQuery.isPending) return <p>Loading health information...</p>
	if (healthQuery.isError) return <p role="alert">{healthQuery.error.message}</p>

	const health = healthQuery.data
	if (!health.available) return <p>Health reference data isn't installed on this server.</p>

	return (
		<section className="health-tables" aria-label="Health">
			<h2>Your vitals</h2>
			{health.vitals ? (
				<table>
					<caption>{TIMING[health.vitals.timing] ?? health.vitals.timing}</caption>
					<thead>
						<tr><th>Measurement</th><th>Value</th><th>What it means</th></tr>
					</thead>
					<tbody>
						{health.vitals.measurements.map((vital) => (
							<tr key={vital.name}><td>{vital.label}</td><td>{vital.value}</td><td>{vital.meaning}</td></tr>
						))}
					</tbody>
				</table>
			) : <p>No vitals could be read from this visit's record.</p>}

			<h2>Your conditions</h2>
			{health.topics.length === 0 ? <p>No matching health topics.</p> : health.topics.map((topic) => (
				<table key={topic.id}>
					<caption>{topic.title} <small>(from your diagnosis: {topic.matchedOn})</small></caption>
					<tbody>
						{topic.parts.slice(0, 1).map((part) => (
							<tr key={part.question}><th scope="row">{part.question}</th><td>{part.answer}</td></tr>
						))}
						{topic.parts.length > 1 && (
							<tr>
								<td colSpan={2}>
									<details>
										<summary>Read more ({topic.parts.length - 1} more questions)</summary>
										<table>
											<tbody>
												{topic.parts.slice(1).map((part) => (
													<tr key={part.question}><th scope="row">{part.question}</th><td>{part.answer}</td></tr>
												))}
											</tbody>
										</table>
									</details>
								</td>
							</tr>
						)}
					</tbody>
				</table>
			))}

			<h2>Your medicines</h2>
			<table>
				<thead>
					<tr><th>Medicine</th><th>Get help right away if you have</th><th>Other reported side effects</th></tr>
				</thead>
				<tbody>
					{health.medicines.map((medicine) => (
						<tr key={medicine.listedAs}>
							<td>{medicine.listedAs}</td>
							{medicine.sideEffects.total === 0 ? (
								<td colSpan={2}>No side-effect list on file for this medicine. Ask your pharmacist.</td>
							) : (
								<>
									<td>
										{medicine.sideEffects.getHelp.length === 0 ? 'None listed' : (
											<ul>{medicine.sideEffects.getHelp.map((w) => <li key={w.warning}>{w.warning}</li>)}</ul>
										)}
									</td>
									<td>
										{medicine.sideEffects.other.length === 0 ? 'None listed' : (
											<details>
												<summary>{medicine.sideEffects.other.length} more</summary>
												{medicine.sideEffects.other.join(', ')}
											</details>
										)}
									</td>
								</>
							)}
						</tr>
					))}
				</tbody>
			</table>

			<ul className="health-sources">{health.sources.map((source) => <li key={source}>{source}</li>)}</ul>
		</section>
	)
}

export default HealthTables

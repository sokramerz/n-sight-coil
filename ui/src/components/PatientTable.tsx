export type Patient = {
	id: string
	name: string
	visitType: string
	date: string
	reason: string
	flags: string[]
	action: string
}

type PatientTableProps = {
	patients: Patient[]
    heading: string
    onSelect?: (patient: Patient) => void
}

const PatientTable = ({ patients, heading, onSelect }: PatientTableProps) => (
	<section className="patient-section" aria-labelledby="patient-list-heading">
		<div className="section-heading">
            <h2 id="patient-list-heading">{heading}</h2>
		</div>
		<div className="table-shell">
			<div className="table-scroll">
				<table>
					<thead>
						<tr>
							<th scope="col">Patient</th>
							<th scope="col">Visit type</th>
							<th scope="col">Date</th>
							<th scope="col">Visit reason</th>
							<th scope="col">Flags</th>
							<th scope="col">Actions / todo</th>
						</tr>
					</thead>
					<tbody>
						{patients.length === 0 ? (
							<tr>
								<td className="table-empty" colSpan={6}>
                                    <strong>No patients to display</strong>
								</td>
							</tr>
						) : patients.map((patient) => (
							<tr key={patient.id}>
								<th scope="row">
									{onSelect ? <button type="button" onClick={() => onSelect(patient)}>{patient.name}</button> : patient.name}
								</th>
								<td>{patient.visitType}</td>
								<td>{patient.date}</td>
								<td>{patient.reason}</td>
								<td>
									<div className="flag-list">
										{patient.flags.map((flag) => (
											<span className="table-badge table-badge-flag" key={flag}>{flag}</span>
										))}
									</div>
								</td>
								<td><span className="table-badge table-badge-action">{patient.action}</span></td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</div>
	</section>
)

export default PatientTable
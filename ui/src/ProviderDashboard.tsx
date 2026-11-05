import { useEffect, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ChartNoAxesCombined, Users } from 'lucide-react'
import { patientQueryOptions, usePatientsQuery, useSpecialtiesQuery, type Patient as ApiPatient } from './api'

import DashboardHeader from './components/DashboardHeader'
import DashboardSidebar, { type NavigationItem } from './components/DashboardSidebar'
import PatientTable, { type Patient } from './components/PatientTable'
import MetricsPanel from './components/MetricsPanel'

const recentPatientsStorageKey = 'n-sight-recent-patients'
const maxRecentPatients = 5

const readRecentPatientIds = (): string[] => {
	if (typeof window === 'undefined') return []

	try {
		const storedPatients = window.localStorage.getItem(recentPatientsStorageKey)
		if (!storedPatients) return []
		const patientIds = JSON.parse(storedPatients)
		return Array.isArray(patientIds) && patientIds.every((id) => typeof id === 'string') ? patientIds.slice(0, maxRecentPatients) : []
	} 
	catch (error) {
		console.error('Unable to load recent patient IDs.', error)
		return []
	}
}

const toTablePatient = (patient: ApiPatient): Patient => {
	const latestEncounter = patient.encounters[0]
	return {
		id: patient.id,
		name: patient.name,
		visitType: latestEncounter?.service ?? 'Encounter',
		date: latestEncounter?.admission_date
			? new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date(latestEncounter.admission_date))
			: '',
		reason: latestEncounter?.reason ?? 'No reason recorded',
		flags: [],
		action: 'Open patient chart',
	}
}

const ProviderDashboard = () => {
	const patientsPerPage = 10

	const navigate = useNavigate()
	const [selectedPage, setSelectedPage] = useState<'Patients' | 'Metrics'>('Patients')
	const [search, setSearch] = useState('')
	const [specialty, setSpecialty] = useState('')
	const [searchTerm, setSearchTerm] = useState('')
	const [patientPage, setPatientPage] = useState(1)
	const [recentPatientIds, setRecentPatientIds] = useState<string[]>(readRecentPatientIds)

	// wait for a pause in typing so each keystroke isn't a request
	useEffect(() => {
		const timer = setTimeout(() => setSearchTerm(search.trim()), 300)
		return () => clearTimeout(timer)
	}, [search])
	const patientsQuery = usePatientsQuery({ search: searchTerm, specialty })
	const specialtiesQuery = useSpecialtiesQuery()

	const recentPatientQueries = useQueries({
		queries: recentPatientIds.map((patientId) => patientQueryOptions(patientId)),
	})

	const patients: Patient[] = (patientsQuery.data ?? []).map((patient) => toTablePatient({
		...patient,
		encounters: patient.latest_encounter ? [patient.latest_encounter] : [],
	}))

	// fetch recently viewed patients by id
	const recentPatients = recentPatientQueries
		.map((query) => query.data)
		.filter((patient): patient is ApiPatient => Boolean(patient))
		.map(toTablePatient)

	// tabulate total patients, 10 per page for easier display
	const totalPatientPages = Math.max(1, Math.ceil(patients.length / patientsPerPage))
	const currentPatientPage = Math.min(patientPage, totalPatientPages)
	const visiblePatients = patients.slice((currentPatientPage - 1) * patientsPerPage, currentPatientPage * patientsPerPage)
	
	const handlePatientSelect = (patient: Patient) => {
		const updatedRecentPatientIds = [patient.id, ...recentPatientIds.filter((patientId) => patientId !== patient.id)].slice(0, maxRecentPatients)
		setRecentPatientIds(updatedRecentPatientIds)
		try {
			if (typeof window !== 'undefined') {
				window.localStorage.setItem(recentPatientsStorageKey, JSON.stringify(updatedRecentPatientIds))
			}
		} catch (error) {
			console.error('Unable to save recent patient.', error)
		}
		navigate(`/patient/${patient.id}`)
	}

	const navigationItems: NavigationItem[] = [
		{ label: 'Patients', icon: Users },
		{ label: 'Metrics', icon: ChartNoAxesCombined }
	]

	return (
		<div className="dashboard-shell">
			<DashboardHeader />
			<DashboardSidebar
				items={navigationItems}
				pageName="Provider Dashboard"
				activeItem={selectedPage}
				onSelect={(label) => {
					if (label === 'Patients' || label === 'Metrics') {
						setSelectedPage(label)
					}
				}}
			/>
			<main className="dashboard-main">
				<div className="dashboard-content">
					{selectedPage === 'Metrics' ? <MetricsPanel /> : patientsQuery.isPending ? <p>Loading patients...</p> : patientsQuery.isError ? (
						<p role="alert">{patientsQuery.error.message}</p>
					) : (
                        <div>
							<div className="patient-filters">
								<label>
									Search
									<input
										type="search"
										value={search}
										placeholder="Patient ID or diagnosis"
										onChange={(event) => {
											setSearch(event.target.value)
											setPatientPage(1)
										}}
									/>
								</label>
								<label>
									Specialty
									<select
										value={specialty}
										onChange={(event) => {
											setSpecialty(event.target.value)
											setPatientPage(1)
										}}
									>
										<option value="">All</option>
										{(specialtiesQuery.data ?? []).map((option) => (
											<option key={option.key} value={option.key}>{option.label}</option>
										))}
									</select>
								</label>
							</div>
							<PatientTable
								patients={visiblePatients}
								heading="Patients"
								onSelect={handlePatientSelect}
							/>
							{patients.length > 0 && (
								<nav className="patient-pagination" aria-label="Patient pages">
									<button
										type="button"
										disabled={currentPatientPage === 1}
										onClick={() => setPatientPage((page) => page - 1)}
									>
										Previous
									</button>
									<span aria-live="polite">Page {currentPatientPage} of {totalPatientPages}</span>
									<button
										type="button"
										disabled={currentPatientPage === totalPatientPages}
										onClick={() => setPatientPage((page) => page + 1)}
									>
										Next
									</button>
								</nav>
							)}
							<PatientTable
								patients={recentPatients}
								heading="Recent Patients"
								onSelect={handlePatientSelect}
							/>
                        </div>
					)}
				</div>
			</main>
		</div>
	)
}

export default ProviderDashboard
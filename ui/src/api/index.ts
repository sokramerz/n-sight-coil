export { apiClient } from './client'
export { API_BASE_URL } from './config'
export { ApiError, normalizeApiError } from './errors'
export { getHealth } from './features/health'
export { generateDocument, type GeneratedDocument } from './features/documents'
export { compareRuns, getRuns, type RunComparison, type RunList } from './features/runs'
export { getPatientHealth, type HealthTopic, type MedicineInfo, type PatientHealth } from './features/health-info'
export {
	getEncounter,
	getPatient,
	getPatients,
	getSpecialties,
	type Encounter,
	type Patient,
	type PatientFilters,
	type PatientSummary,
	type SpecialtyOption,
} from './features/patients'
export {
	encounterQueryOptions,
	healthQueryOptions,
	patientQueryOptions,
	patientsQueryOptions,
	specialtiesQueryOptions,
	useEncounterQuery,
	useHealthQuery,
	usePatientQuery,
	usePatientsQuery,
	useGenerateDocumentMutation,
	usePatientHealthQuery,
	useRunComparisonQuery,
	useRunsQuery,
	useSpecialtiesQuery,
} from './queries'
export { queryClient } from './query-client'
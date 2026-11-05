import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getHealth } from './features/health'
import { getEncounter, getPatient, getPatients, getSpecialties, type PatientFilters } from './features/patients'
import { generateDocument } from './features/documents'
import { compareRuns, getRuns } from './features/runs'
import { getEncounterTerms, getPatientHealth, getPatientInteractions } from './features/health-info'

export const healthQueryOptions = () =>
	queryOptions({
		queryKey: ['health'],
		queryFn: getHealth,
	})

export function useHealthQuery() {
	return useQuery(healthQueryOptions())
}

export const patientsQueryOptions = (filters: PatientFilters = {}) =>
	queryOptions({
		queryKey: ['patients', 'list', filters.search ?? '', filters.specialty ?? ''],
		queryFn: () => getPatients(filters),
		placeholderData: (previous) => previous,
	})

export function usePatientsQuery(filters: PatientFilters = {}) {
	return useQuery(patientsQueryOptions(filters))
}

export const specialtiesQueryOptions = () =>
	queryOptions({
		queryKey: ['specialties'],
		queryFn: getSpecialties,
		staleTime: Infinity,
	})

export function useSpecialtiesQuery() {
	return useQuery(specialtiesQueryOptions())
}

export const patientQueryOptions = (patientId: string) =>
	queryOptions({
		queryKey: ['patients', patientId],
		queryFn: () => getPatient(patientId),
		enabled: Boolean(patientId),
	})

export function usePatientQuery(patientId: string) {
	return useQuery(patientQueryOptions(patientId))
}

export const encounterQueryOptions = (patientId: string, encounterId: string, glossary?: 'separate' | 'inline') =>
	queryOptions({
		queryKey: ['patients', patientId, 'encounters', encounterId, glossary ?? 'default'],
		queryFn: () => getEncounter(patientId, encounterId, glossary),
		// keep showing this encounter while the other glossary style loads, never a different encounter
		placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[3] === encounterId ? previous : undefined),
		enabled: Boolean(patientId && encounterId),
	})

export function useEncounterQuery(patientId: string, encounterId: string, glossary?: 'separate' | 'inline') {
	return useQuery(encounterQueryOptions(patientId, encounterId, glossary))
}

export function useGenerateDocumentMutation() {
	const queryClient = useQueryClient()
	return useMutation({
		mutationFn: (hadmId: number) => generateDocument(hadmId),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ['patients'] }),
	})
}

export const runsQueryOptions = () =>
	queryOptions({
		queryKey: ['runs'],
		queryFn: getRuns,
	})

export function useRunsQuery() {
	return useQuery(runsQueryOptions())
}

export const runComparisonQueryOptions = (tags: string[]) =>
	queryOptions({
		queryKey: ['runs', 'compare', ...tags],
		queryFn: () => compareRuns(tags),
		enabled: tags.length > 0,
	})

export function useRunComparisonQuery(tags: string[]) {
	return useQuery(runComparisonQueryOptions(tags))
}

export const patientHealthQueryOptions = (patientId: string) =>
	queryOptions({
		queryKey: ['patients', patientId, 'health'],
		queryFn: () => getPatientHealth(patientId),
		enabled: Boolean(patientId),
		staleTime: Infinity,
	})

export function usePatientHealthQuery(patientId: string) {
	return useQuery(patientHealthQueryOptions(patientId))
}

export const patientInteractionsQueryOptions = (patientId: string) =>
	queryOptions({
		queryKey: ['patients', patientId, 'interactions'],
		queryFn: () => getPatientInteractions(patientId),
		enabled: Boolean(patientId),
		staleTime: Infinity,
	})

export function usePatientInteractionsQuery(patientId: string) {
	return useQuery(patientInteractionsQueryOptions(patientId))
}

export const encounterTermsQueryOptions = (patientId: string, encounterId: string) =>
	queryOptions({
		queryKey: ['patients', patientId, 'encounters', encounterId, 'terms'],
		queryFn: () => getEncounterTerms(patientId, encounterId),
		enabled: Boolean(patientId && encounterId),
		staleTime: Infinity,
	})

export function useEncounterTermsQuery(patientId: string, encounterId: string) {
	return useQuery(encounterTermsQueryOptions(patientId, encounterId))
}

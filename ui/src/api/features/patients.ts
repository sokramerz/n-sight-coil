import { apiClient } from '../client'
import { normalizeApiError } from '../errors'
import type { components } from '../generated/schema'

export type Patient = components['schemas']['Patient']
export type PatientSummary = components['schemas']['PatientSummary']
export type Encounter = components['schemas']['Encounter']

export type SpecialtyOption = components['schemas']['SpecialtyOption']

export type PatientFilters = {
	search?: string
	specialty?: string
}

// No filters returns every patient; search takes an ID prefix or words from a diagnosis
export async function getPatients(filters: PatientFilters = {}): Promise<PatientSummary[]> {
	const { data, error, response } = await apiClient.GET('/patients', {
		params: { query: { search: filters.search || undefined, specialty: filters.specialty || undefined } },
	})
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

export async function getPatient(patientId: string): Promise<Patient> {
	const { data, error, response } = await apiClient.GET('/patients/{patient_id}', {
		params: { path: { patient_id: patientId } },
	})
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

// glossary: 'separate' puts each explanation on its own line, 'inline' keeps it in parentheses after the word
export async function getEncounter(patientId: string, encounterId: string, glossary?: 'separate' | 'inline'): Promise<Encounter> {
	const { data, error, response } = await apiClient.GET('/patients/{patient_id}/encounters/{encounter_id}', {
		params: { path: { patient_id: patientId, encounter_id: encounterId }, query: { glossary } },
	})
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

export async function getSpecialties(): Promise<SpecialtyOption[]> {
	const { data, error, response } = await apiClient.GET('/specialties')
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

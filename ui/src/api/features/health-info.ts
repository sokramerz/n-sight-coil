import { apiClient } from '../client'
import { normalizeApiError } from '../errors'
import type { components } from '../generated/schema'

export type PatientHealth = components['schemas']['PatientHealth']
export type MedicineInfo = components['schemas']['MedicineInfo']
export type HealthTopic = components['schemas']['HealthTopic']
export type VitalSigns = components['schemas']['VitalSigns']
export type PatientInteractions = components['schemas']['PatientInteractions']
export type TermLink = components['schemas']['TermLink']

function status(response: unknown) {
	return (response as Response | undefined)?.status ?? 0
}

// Vitals, condition topics and medicine side effects for the patient's most recent admission
export async function getPatientHealth(patientId: string): Promise<PatientHealth> {
	const { data, error, response } = await apiClient.GET('/patients/{patient_id}/health', {
		params: { path: { patient_id: patientId } },
	})
	if (error) throw normalizeApiError(error, status(response))
	return data
}

// Provider view only: DrugBank interactions have no severity, so they aren't shown to patients
export async function getPatientInteractions(patientId: string): Promise<PatientInteractions> {
	const { data, error, response } = await apiClient.GET('/patients/{patient_id}/interactions', {
		params: { path: { patient_id: patientId } },
	})
	if (error) throw normalizeApiError(error, status(response))
	return data
}

// Where the patient's conditions first appear in the instructions, for pop-ups
export async function getEncounterTerms(patientId: string, encounterId: string): Promise<TermLink[]> {
	const { data, error, response } = await apiClient.GET('/patients/{patient_id}/encounters/{encounter_id}/terms', {
		params: { path: { patient_id: patientId, encounter_id: encounterId } },
	})
	if (error) throw normalizeApiError(error, status(response))
	return data
}

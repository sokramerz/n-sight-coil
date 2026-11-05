import { apiClient } from '../client'
import { normalizeApiError } from '../errors'
import type { components } from '../generated/schema'

export type GeneratedDocument = components['schemas']['DocumentOut']

// Sorts the doctor's instructions and fills gaps from the record. The model only runs when the doctor wrote almost nothing
export async function generateDocument(hadmId: number): Promise<GeneratedDocument> {
	const { data, error, response } = await apiClient.POST('/admissions/{hadmId}/documents', {
		params: { path: { hadmId } },
		body: { mode: 'sectional', simplify: false, useInstructions: true, generative: false },
	})
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

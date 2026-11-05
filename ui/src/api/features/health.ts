import { apiClient } from '../client'
import { normalizeApiError } from '../errors'
import type { components } from '../generated/schema'

// Get OpenAPI auto-generated type
export type HealthResponse = components['schemas']['HealthResponse']

export async function getHealth(): Promise<HealthResponse> {
	const { data, error, response } = await apiClient.GET('/health')

	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}

	return data
}
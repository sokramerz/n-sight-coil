import { apiClient } from '../client'
import { normalizeApiError } from '../errors'
import type { components } from '../generated/schema'

export type RunList = components['schemas']['RunList']
export type RunComparison = components['schemas']['RunComparison']

export async function getRuns(): Promise<RunList> {
	const { data, error, response } = await apiClient.GET('/runs')
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

// The first tag is the baseline the others are tested against
export async function compareRuns(tags: string[]): Promise<RunComparison> {
	const { data, error, response } = await apiClient.GET('/runs/compare', {
		params: { query: { tags } },
	})
	if (error) {
		throw normalizeApiError(error, (response as Response | undefined)?.status ?? 0)
	}
	return data
}

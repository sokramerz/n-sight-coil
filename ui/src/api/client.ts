import createClient from 'openapi-fetch'
import type { paths } from './generated/schema'
import { API_BASE_URL } from './config'
import { normalizeApiError } from './errors'

// Modified fetch ontop of the client to handle errors and any custom logic we may want to handle automatically
const apiFetch: typeof fetch = async (input, init) => {
	// openapi-fetch passes a Request carrying Content-Type; keep its headers or POST bodies arrive untyped
	const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
	headers.set('Accept', 'application/json')

	/*
	// TODO: configure access/user auth, if needed
	const accessToken = getAccessToken()
	if (accessToken) {
		headers.set('Authorization', `Bearer ${accessToken}`)
	}
	*/

	try {
		return await fetch(input, { ...init, headers })
	} 
	catch (error) {
		throw normalizeApiError(error)
	}
}

export const apiClient = createClient<paths>({
	baseUrl: API_BASE_URL,
	fetch: apiFetch,
})
export type ApiErrorShape = {
	status: number
	message: string
	code?: string
	details?: unknown
}

// Basic error wrapper to normalize errors for easier frontend handling
export class ApiError extends Error {
	readonly status: number
	readonly code?: string
	readonly details?: unknown

	constructor({ status, message, code, details }: ApiErrorShape) {
		super(message)
		this.status = status
		this.code = code
		this.details = details
	}
}

export function normalizeApiError(error: unknown, status = 0): ApiError {
	if (error instanceof ApiError) {
		return error
	}

	// Loosely validate that error is actually an object to grab nested fields w/o breaking
	if (isRecord(error)) {
		// FastAPI puts the reason in `detail`
		const message = typeof error.message === 'string' ? error.message
			: typeof error.detail === 'string' ? error.detail
			: 'The request failed.'
		const code = typeof error.code === 'string' ? error.code : undefined
		const details = error.details ?? error.detail

		return new ApiError({ status, message, code, details })
	}

	return new ApiError({
		status,
		message: error instanceof Error ? error.message : 'The request failed.',
		details: error,
	})
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null
}
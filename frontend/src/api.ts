export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<TResponse>(path: string, opts: RequestInit = {}): Promise<TResponse> {
  const headers = new Headers(opts.headers)
  headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')

  const response = await fetch(path, {
    ...opts,
    credentials: 'same-origin',
    headers,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new ApiError(response.status, `API error ${response.status}: ${text}`)
  }

  return (await response.json()) as TResponse
}

export async function api<TResponse>(path: string, opts: RequestInit = {}): Promise<TResponse> {
  const headers = new Headers(opts.headers)
  headers.set('Content-Type', headers.get('Content-Type') ?? 'application/json')

  const response = await fetch(path, {
    ...opts,
    headers,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`API error ${response.status}: ${text}`)
  }

  return (await response.json()) as TResponse
}

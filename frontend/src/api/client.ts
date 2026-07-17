export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(
      `Data unavailable (${response.status})`,
      response.status,
    );
  }
  return (await response.json()) as T;
}

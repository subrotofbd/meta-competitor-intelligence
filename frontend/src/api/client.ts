/**
 * The HTTP client. One reusable helper, and deliberately no endpoints.
 *
 * ## Why there are no endpoint functions yet
 *
 * `getAds()`, `getAdDetail()` and friends are not written here. Writing them before
 * a screen needs them produces functions nobody calls, and -- worse -- freezes a
 * guessed URL and a guessed parameter shape into the client, where it looks
 * authoritative. S3.3 builds the shell first; the endpoint functions arrive with the
 * screen that actually needs them, and get their names from what the backend routes
 * are really called.
 *
 * ## `BASE_PATH` is `/api`, and the dev proxy strips it
 *
 * See `vite.config.ts`. The client always sends `/api/...`; only in development does
 * anything rewrite that to a root-relative backend path. Nothing in this file should
 * ever hardcode `http://localhost:8000` -- an absolute origin would bypass the
 * proxy, break in production, and make the browser issue a cross-origin request the
 * backend has no CORS support for.
 *
 * ## Errors are thrown, not returned
 *
 * A non-2xx response raises {@link ApiError} carrying the status and the backend's
 * `detail` when present. Callers decide what a failure means; a helper that returned
 * `{ ok: false }` would push that decision into every call site.
 *
 * ## `null` is not an error and `null` is not a default
 *
 * `AGENTS.md` section 7: a missing value is `null` and renders as an em dash. It is
 * never `0`, never `"N/A"`, never a placeholder that merely looks plausible. This
 * module therefore never substitutes a value for a missing one -- it either hands
 * back what the server sent, including `null`, or throws.
 */

/** Every request the client makes is prefixed with this. */
export const BASE_PATH = "/api";

/** A non-2xx response, with whatever the backend said about it. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string | null;

  constructor(status: number, detail: string | null) {
    super(
      detail === null
        ? `Request failed with status ${status}`
        : `Request failed with status ${status}: ${detail}`,
    );
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** A caller-supplied abort signal, or none. */
export type RequestOptions = {
  readonly signal?: AbortSignal;
};

/**
 * Pull a readable message out of a FastAPI error body.
 *
 * FastAPI's `detail` is a string for `HTTPException` and a **list of objects** for a
 * request-validation failure (422), so both shapes are handled. Anything else yields
 * `null` rather than `[object Object]` -- a client that stringifies an unknown shape
 * will display noise as if it were a server message.
 */
async function readErrorDetail(response: Response): Promise<string | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    // Not JSON. A proxy error page or an empty 502 is the usual cause, and the
    // status alone is then the honest thing to report.
    return null;
  }

  if (typeof body !== "object" || body === null) return null;
  const detail: unknown = (body as Record<string, unknown>)["detail"];
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Validation errors carry `{ loc, msg, type }` per problem.
    const messages = detail
      .map((item) => {
        if (typeof item !== "object" || item === null) return null;
        const msg: unknown = (item as Record<string, unknown>)["msg"];
        return typeof msg === "string" ? msg : null;
      })
      .filter((msg): msg is string => msg !== null);
    return messages.length > 0 ? messages.join("; ") : null;
  }
  return null;
}

/**
 * Build a `path` + `query` into a URL under {@link BASE_PATH}.
 *
 * Exported separately from {@link request} so a component that needs a link -- an
 * `href`, a CSV download -- can build the same URL the fetch would have used,
 * instead of re-deriving the prefix and risking a mismatch.
 *
 * A `null` or `undefined` query value is **omitted**, never sent as `"null"`. An
 * absent filter is not the filter "null"; the backend would reject it, and sending
 * it would suggest a filter exists when it does not.
 */
export function apiUrl(path: string, query?: Readonly<Record<string, unknown>>): string {
  const suffix = path.startsWith("/") ? path : `/${path}`;
  const search = new URLSearchParams();

  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      // Repeated keys, which is how a multi-select filter reaches the backend.
      for (const item of value) {
        if (item !== null && item !== undefined) search.append(key, String(item));
      }
      continue;
    }
    search.append(key, String(value));
  }

  const queryString = search.toString();
  return queryString === ""
    ? `${BASE_PATH}${suffix}`
    : `${BASE_PATH}${suffix}?${queryString}`;
}

/**
 * Perform one GET and return the decoded body.
 *
 * Generic purely as a hint for the caller: the return value is `unknown` until a
 * caller narrows it against `types/api.ts`. There is no runtime validation here,
 * deliberately -- the backend's schemas are `extra="forbid"`, so a field arriving
 * that no schema declares is a backend bug, and papering over it in the client would
 * hide it rather than surface it.
 *
 * `T` defaults to `unknown` so a caller cannot accidentally get a response typed as
 * something it never checked.
 */
export async function request<T = unknown>(
  path: string,
  options: RequestOptions & { query?: Readonly<Record<string, unknown>> } = {},
): Promise<T> {
  const { signal, query } = options;
  const response = await fetch(apiUrl(path, query), {
    method: "GET",
    headers: { Accept: "application/json" },
    ...(signal ? { signal } : {}),
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }

  // 204 has no body. Returning `null as T` would be a lie for most `T`, so this
  // narrows to `null` explicitly and lets the caller decide what that means.
  if (response.status === 204) return null as T;

  return (await response.json()) as T;
}
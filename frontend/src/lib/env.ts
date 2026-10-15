/**
 * Typed access to build-time configuration.
 *
 * Only `VITE_*` variables are exposed to the browser by Vite, so nothing
 * secret can leak through this module.
 */

/** Base URL of the backend API, without a trailing slash. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

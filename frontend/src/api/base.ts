/**
 * Where the API lives.
 *
 * Development: unset, so this resolves to "/api" and Vite's proxy forwards to
 * the local backend — no .env file is needed to run the app locally.
 *
 * Production: VITE_API_BASE_URL is baked in at build time and points at the
 * deployed backend origin, because the frontend and the API are served from
 * different hosts.
 *
 * VITE_ variables are compiled into the browser bundle. Only the API origin
 * belongs here; never a credential.
 */
export const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "/api";

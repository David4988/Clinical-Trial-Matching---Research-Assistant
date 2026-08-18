/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Where the API lives. Unset in development, where Vite proxies /api to the
   * local backend; set at build time in production to the deployed backend's
   * origin, e.g. https://<service>.onrender.com
   *
   * Public by definition — anything under VITE_ is compiled into the browser
   * bundle, so no secret may ever be placed here.
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

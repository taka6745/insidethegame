// Cloudflare Worker: serves the demo at a custom hostname by proxying to the Azure web app.
export interface Env { UPSTREAM: string }

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const upstream = new URL(url.pathname + url.search, env.UPSTREAM);
    return fetch(new Request(upstream, request));
  },
};

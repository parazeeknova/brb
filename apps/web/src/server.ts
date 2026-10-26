import { consumeLastCapturedError } from "./lib/error-capture";
import { renderErrorPage } from "./lib/error-page";
import { SITE_URL } from "./lib/seo";
import { SOURCE_PAGES } from "./lib/source-pages";

interface ServerEntry {
  fetch: (
    request: Request,
    env: unknown,
    ctx: unknown
  ) => Promise<Response> | Response;
}

let serverEntryPromise: Promise<ServerEntry> | undefined;

async function getServerEntry(): Promise<ServerEntry> {
  if (!serverEntryPromise) {
    serverEntryPromise = import("@tanstack/react-start/server-entry").then(
      (m) => (m.default ?? m) as ServerEntry
    );
  }
  return serverEntryPromise;
}

// h3 swallows in-handler throws into a normal 500 Response with body
// {"unhandled":true,"message":"HTTPError"} — try/catch alone never fires for those.
async function normalizeCatastrophicSsrResponse(
  response: Response
): Promise<Response> {
  if (response.status < 500) {
    return response;
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return response;
  }

  const body = await response.clone().text();
  if (!isH3SwallowedErrorBody(body)) {
    return response;
  }

  console.error(
    consumeLastCapturedError() ?? new Error(`h3 swallowed SSR error: ${body}`)
  );
  return new Response(renderErrorPage(), {
    headers: { "content-type": "text/html; charset=utf-8" },
    status: 500,
  });
}

function isH3SwallowedErrorBody(body: string): boolean {
  try {
    const payload = JSON.parse(body) as {
      unhandled?: unknown;
      message?: unknown;
    };
    return payload.unhandled === true && payload.message === "HTTPError";
  } catch {
    return false;
  }
}

export default {
  async fetch(request: Request, env: unknown, ctx: unknown) {
    const path = new URL(request.url).pathname;
    if (path === "/sitemap.xml") {
      const paths = [
        "/",
        ...SOURCE_PAGES.map((source) => `/sources/${source.slug}`),
      ];
      const xml = `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${paths.map((page) => `<url><loc>${SITE_URL}${page}</loc></url>`).join("")}</urlset>`;
      return new Response(xml, {
        headers: {
          "Cache-Control": "public, max-age=3600",
          "Content-Type": "application/xml; charset=utf-8",
        },
      });
    }
    try {
      const handler = await getServerEntry();
      const response = await handler.fetch(request, env, ctx);
      const normalized = await normalizeCatastrophicSsrResponse(response);
      if (normalized.status >= 400 || /^\/(app|profile)(\/|$)/.test(path)) {
        const headers = new Headers(normalized.headers);
        headers.set("X-Robots-Tag", "noindex, follow");
        return new Response(normalized.body, {
          headers,
          status: normalized.status,
          statusText: normalized.statusText,
        });
      }
      return normalized;
    } catch (error) {
      console.error(error);
      return new Response(renderErrorPage(), {
        headers: { "content-type": "text/html; charset=utf-8" },
        status: 500,
      });
    }
  },
};

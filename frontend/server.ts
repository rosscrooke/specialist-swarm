// Serves the page. In production Caddy sends /api to the backend before a
// request gets here; in development this forwards /api itself.
import index from "./index.html";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const server = Bun.serve({
  port: Number(process.env.PORT ?? 3000),
  development: process.env.NODE_ENV !== "production",
  // The event stream can stay quiet for 20 seconds between pings.
  idleTimeout: 255,
  routes: {
    "/api/*": (req) => {
      const url = new URL(req.url);
      return fetch(backend + url.pathname + url.search, {
        method: req.method,
        headers: req.headers,
        body: req.body,
      });
    },
    "/*": index,
  },
});

console.log(`frontend on ${server.url}`);

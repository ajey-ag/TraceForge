import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (!path.every(part => /^[a-zA-Z0-9_-]+$/.test(part))) {
    return Response.json({ detail: "Invalid API path" }, { status: 400 });
  }
  const base = process.env.TRACEFORGE_API_URL || "http://127.0.0.1:8000";
  const url = new URL(`${base}/${path.join("/")}`);
  url.search = request.nextUrl.search;
  try {
    const body = request.method === "POST" ? await request.text() : undefined;
    if (body && body.length > 1_000_000) return Response.json({ detail: "Request too large" }, { status: 413 });
    const response = await fetch(url, {
      method: request.method, body, cache: "no-store",
      headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(15000),
    });
    const headers = new Headers({ "Content-Type": response.headers.get("Content-Type") || "application/json" });
    const disposition = response.headers.get("Content-Disposition");
    if (disposition) headers.set("Content-Disposition", disposition);
    return new Response(await response.arrayBuffer(), { status: response.status, headers });
  } catch {
    return Response.json({ detail: "Backend unavailable; check API readiness and Docker services." }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;

// Test-only HTTP bridge to Wrangler's real, locally persisted R2 binding.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return new Response("ok");
    const key = url.pathname.slice(1);
    switch (request.method) {
      case "PUT":
        await env.FORM_IMAGES.put(key, request.body);
        return new Response(null, { status: 204 });
      case "GET": {
        const object = await env.FORM_IMAGES.get(key);
        return object
          ? new Response(object.body)
          : new Response(null, { status: 404 });
      }
      case "DELETE":
        await env.FORM_IMAGES.delete(key);
        return new Response(null, { status: 204 });
      default:
        return new Response(null, { status: 405 });
    }
  },
};

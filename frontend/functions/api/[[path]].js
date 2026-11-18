# MailVerify Pages Functions — API 代理到 Render.com 后端
#
# 所有 /api/* 请求转发到 Render 后端 URL
# Render 后端 URL 通过环境变量 RENDER_BACKEND_URL 注入

const RENDER_BACKEND = (globalThis.RENDER_BACKEND_URL || 'http://localhost:8765').replace(/\/$/, '');

export async function onRequest(context) {
  const { request, next } = context;
  const url = new URL(request.url);

  // 只代理 /api/* 路径
  if (!url.pathname.startsWith('/api/')) {
    return next();
  }

  // 把 /api/xxx 转发到 Render 的 /xxx
  const backendPath = url.pathname.replace(/^\/api/, '');
  const backendUrl = RENDER_BACKEND + backendPath + url.search;

  // 构造新请求
  const headers = new Headers(request.headers);
  headers.set('origin', new URL(RENDER_BACKEND).origin);
  headers.delete('host');

  const init = {
    method: request.method,
    headers,
  };

  // POST/PUT 带 body（multipart 会原样转发）
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body;
  }

  try {
    const resp = await fetch(backendUrl, init);

    // 复制响应头（允许 CORS）
    const respHeaders = new Headers(resp.headers);
    respHeaders.set('Access-Control-Allow-Origin', '*');
    respHeaders.set('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    respHeaders.set('Access-Control-Allow-Headers', 'Content-Type');
    respHeaders.delete('transfer-encoding');

    return new Response(resp.body, {
      status: resp.status,
      headers: respHeaders,
    });
  } catch (err) {
    return new Response(JSON.stringify({ error: 'backend_unreachable', detail: String(err) }), {
      status: 502,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
      },
    });
  }
}

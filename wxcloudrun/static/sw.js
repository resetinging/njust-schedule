/* 南理工课表管理 — Service Worker（PWA 离线支持）
 *
 * 策略：
 *  - /api/* 请求直连网络，绝不缓存（保证接口响应实时）
 *  - 静态资源 network-first：优先网络拿最新代码，失败时回退缓存（离线兜底）
 *  - 版本号随代码更新递增，activate 时清理旧版本缓存
 *    （旧版 cache-first 会永久卡住旧代码，导致部署后前端不更新）
 */
const CACHE = "njust-schedule-v2";
const ASSETS = [
    "/",
    "/static/css/style.css",
    "/static/js/main.js",
    "/static/js/schedule.js",
    "/static/js/exams.js",
    "/static/js/evaluations.js",
    "/static/js/grades.js",
    "/static/js/gallery.js",
    "/static/js/settings.js",
    "/static/manifest.json",
    "/static/icon-192.png",
    "/static/icon-512.png",
];

self.addEventListener("install", (e) => {
    e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
    self.skipWaiting();
});

self.addEventListener("activate", (e) => {
    // 清理旧版本缓存
    e.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (e) => {
    const url = new URL(e.request.url);

    // API 请求不缓存
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/proxy/")) {
        e.respondWith(fetch(e.request));
        return;
    }
    // 只处理 GET
    if (e.request.method !== "GET") {
        e.respondWith(fetch(e.request));
        return;
    }

    // 静态资源: network-first, 失败回退缓存
    e.respondWith(
        fetch(e.request)
            .then((resp) => {
                const copy = resp.clone();
                caches.open(CACHE).then((c) => c.put(e.request, copy));
                return resp;
            })
            .catch(() => caches.match(e.request))
    );
});

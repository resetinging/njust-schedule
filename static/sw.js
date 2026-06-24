/* 南理工课表管理 — Service Worker（PWA 离线支持） */
const CACHE = "njust-schedule-v1";
const ASSETS = [
    "/",
    "/static/css/style.css",
    "/static/js/main.js",
    "/static/js/schedule.js",
    "/static/js/exams.js",
    "/static/js/settings.js",
    "/static/manifest.json",
    "/static/icon-192.png",
    "/static/icon-512.png",
];

self.addEventListener("install", (e) => {
    e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)));
});

self.addEventListener("fetch", (e) => {
    e.respondWith(
        caches.match(e.request).then((r) => r || fetch(e.request))
    );
});

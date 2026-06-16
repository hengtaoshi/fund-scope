/**
 * 基金范围 — Service Worker
 * 版本: 1.0.0
 * 
 * 缓存策略：
 * - 静态资源（HTML/CSS/JS/字体/图标）：安装时预缓存，优先从缓存加载
 * - API 请求：网络优先，缓存兜底
 * - 离线时至少显示上次缓存的首页
 */

const CACHE_NAME = 'fund-cockpit-v2';

// 安装时预缓存的静态资源（带版本号的 JS/CSS 不在 SW 中缓存，由 HTML 控制）
const PRECACHE_URLS = [
  '/',
  '/login',
  '/css/fontawesome.min.css',
  '/js/chart.umd.min.js',
  '/js/marked.min.js',
  '/js/dompurify.min.js',
  '/manifest.json',
  '/icon-192.svg',
  '/icon-512.svg',
];

// 安装：预缓存关键静态资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_URLS);
    })
  );
  // 强制新 SW 立即激活
  self.skipWaiting();
});

// 激活：清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      );
    })
  );
  // 立即控制所有已打开的页面
  self.clients.claim();
});

// 拦截请求：网络优先，缓存兜底
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API 请求：网络优先
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // 缓存成功的 API 响应
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, clone);
            });
          }
          return response;
        })
        .catch(() => {
          // 网络失败 → 从缓存返回
          return caches.match(event.request);
        })
    );
    return;
  }

  // 静态资源：优先从缓存，网络更新
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        // 后台更新缓存
        fetch(event.request).then((response) => {
          if (response.ok) {
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, response);
            });
          }
        }).catch(() => {});
        return cached;
      }
      return fetch(event.request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, clone);
          });
        }
        return response;
      });
    })
  );
});

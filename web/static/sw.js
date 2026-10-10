// Service Worker: zeigt Benachrichtigungen vom News-Bot an – auch wenn die Seite geschlossen ist.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { d = {}; }
  const titel = String(d.titel || "News-Bot").slice(0, 200);
  e.waitUntil(self.registration.showNotification(titel, {
    body: String(d.text || "").slice(0, 300),
    tag: typeof d.tag === "string" ? d.tag : undefined,
    data: { url: d.url },
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  let ziel = "/";
  try {
    const u = new URL(e.notification.data && e.notification.data.url);
    if (u.protocol === "https:" || u.protocol === "http:") ziel = u.href;  // nur echte Weblinks öffnen
  } catch { /* kein gültiger Link → Dashboard öffnen */ }
  e.waitUntil(self.clients.openWindow(ziel));
});

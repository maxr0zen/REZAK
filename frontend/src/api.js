export async function api(path, method = "GET", body, signal) {
  const r = await fetch("/api" + path, {
    method,
    headers: {
      "X-Rezak-Client": "1",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data),
    );
  return data;
}
export const bytes = (n) => {
  if (!n) return "0 Б";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"],
    i = Math.min(4, Math.floor(Math.log(n) / Math.log(1024)));
  return (
    (n / 1024 ** i).toLocaleString("ru-RU", {
      maximumFractionDigits: i > 1 ? 1 : 0,
    }) +
    " " +
    u[i]
  );
};
export const duration = (ms) => {
  const s = Math.max(0, Math.floor((ms || 0) / 1000));
  return (
    (s >= 3600
      ? Math.floor(s / 3600) +
        ":" +
        String(Math.floor(s / 60) % 60).padStart(2, "0")
      : Math.floor(s / 60)) +
    ":" +
    String(s % 60).padStart(2, "0")
  );
};
export const timeOf = (ts) => new Date(ts * 1000).toLocaleTimeString("ru-RU");
export const names = {
  overview: "Обзор",
  twitch: "Twitch-стримеры",
  queue: "Очередь обработки",
  clips: "Готовые нарезки",
  settings: "Настройки",
};
export const statusName = (j) =>
  ({
    queued: "В очереди",
    running: "В обработке",
    recording: "Идёт запись",
    done: "Готово",
    error: "Ошибка",
    cancelled: "Отменено",
    interrupted: "Прервано",
  })[j.status] || j.status;

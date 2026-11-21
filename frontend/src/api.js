const TIMEOUT_MS = 60000;
const DETAIL_LIMIT = 300;

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function shorten(text, limit = DETAIL_LIMIT) {
  const value = String(text || "")
    .replace(/\s+/g, " ")
    .trim();
  return value.length > limit ? value.slice(0, limit) + "…" : value;
}

function makeTimeout() {
  if (typeof AbortSignal.timeout === "function")
    return { signal: AbortSignal.timeout(TIMEOUT_MS), cancel: () => {} };
  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException("Timeout", "TimeoutError")),
    TIMEOUT_MS,
  );
  return { signal: controller.signal, cancel: () => clearTimeout(timer) };
}

function requestSignal(external, timeout) {
  if (!external) return timeout.signal;
  if (typeof AbortSignal.any === "function")
    return AbortSignal.any([external, timeout.signal]);
  const controller = new AbortController();
  const relay = (source) => {
    const onAbort = () => {
      if (!controller.signal.aborted) controller.abort(source.reason);
    };
    source.addEventListener("abort", onAbort, { once: true });
    controller.signal.addEventListener(
      "abort",
      () => source.removeEventListener("abort", onAbort),
      { once: true },
    );
  };
  relay(external);
  relay(timeout.signal);
  return controller.signal;
}

export async function api(path, method = "GET", body, signal) {
  const hasBody = body !== undefined && body !== null;
  const timeout = makeTimeout();
  let r;
  try {
    r = await fetch("/api" + path, {
      method,
      headers: {
        "X-Rezak-Client": "1",
        ...(hasBody ? { "Content-Type": "application/json" } : {}),
      },
      body: hasBody ? JSON.stringify(body) : undefined,
      signal: requestSignal(signal, timeout),
    });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    if (e?.name === "TimeoutError")
      throw new ApiError(
        "Сервер не ответил вовремя (" + TIMEOUT_MS / 1000 + " с)",
        0,
        null,
      );
    throw new ApiError(
      "Сервис недоступен: " + (e?.message || "неизвестная ошибка"),
      0,
      null,
    );
  } finally {
    timeout.cancel();
  }
  let raw = "";
  try {
    raw = await r.text();
  } catch (e) {
    throw new ApiError(
      "Ответ сервера оборвался: " + (e?.message || "неизвестная ошибка"),
      r.status,
      null,
    );
  }
  let data = null,
    parsed = false;
  if (raw.trim()) {
    try {
      data = JSON.parse(raw);
      parsed = true;
    } catch {
      parsed = false;
    }
  }
  if (!r.ok) {
    if (parsed) {
      const detail = data?.detail ?? data;
      const message =
        typeof detail === "string" && detail.trim()
          ? detail
          : JSON.stringify(data.detail || data);
      throw new ApiError(message, r.status, detail);
    }
    const snippet = shorten(raw);
    throw new ApiError(
      "Сервер вернул " +
        r.status +
        (r.statusText ? " " + r.statusText : "") +
        (snippet ? ": " + snippet : ""),
      r.status,
      snippet || null,
    );
  }
  if (!parsed)
    throw new ApiError(
      "Сервер вернул некорректный ответ" +
        (r.status ? " (HTTP " + r.status + ")" : "") +
        (raw.trim() ? ": " + shorten(raw) : " (пустой ответ)"),
      r.status,
      shorten(raw) || null,
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
  games: "Тиктоки по играм",
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

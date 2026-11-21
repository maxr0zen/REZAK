import React, { useEffect, useState } from "react";
import { api, bytes } from "./api";
import { Icon } from "./icons";
import { Button, Heading, Empty, Modal } from "./components";
import { AccountManager, ChannelAccounts } from "./Publishing";

export function Twitch({ data, onAction, onJob }) {
  const [adding, setAdding] = useState(false),
    [accountsOpen, setAccountsOpen] = useState(false),
    [channelAccounts, setChannelAccounts] = useState(null),
    [removing, setRemoving] = useState(null),
    [removeBusy, setRemoveBusy] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState({}),
    [local, setLocal] = useState({});
  async function add(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const f = new FormData(e.currentTarget);
    try {
      await onAction("/streamers", "POST", {
        login: f.get("login"),
        quality: f.get("quality"),
        auto_record: f.has("auto_record"),
        auto_clip: f.has("auto_clip"),
        live_clip: f.has("live_clip"),
        adhd_mode: f.has("adhd_mode"),
      });
      setAdding(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const toggle = async (s, key) => {
    const id = s.id + ":" + key;
    if (pending[id]) return;
    const current = local[s.id]?.[key] ?? s[key];
    setPending((p) => ({ ...p, [id]: true }));
    setLocal((l) => ({
      ...l,
      [s.id]: { ...(l[s.id] || {}), [key]: !current },
    }));
    try {
      await onAction("/streamers/" + s.id, "PATCH", { [key]: !current });
    } catch (e) {
      setLocal((l) => ({
        ...l,
        [s.id]: { ...(l[s.id] || {}), [key]: current },
      }));
      setError(e.message);
    } finally {
      setPending((p) => {
        const copy = { ...p };
        delete copy[id];
        return copy;
      });
    }
  };
  // Drop optimistic values that the server has already applied
  useEffect(() => {
    setLocal((prev) => {
      const next = {};
      let changed = false;
      for (const [id, fields] of Object.entries(prev)) {
        const streamer = data.streamers.find((s) => s.id === id);
        if (!streamer) {
          changed = true;
          continue;
        }
        const kept = {};
        for (const [key, value] of Object.entries(fields)) {
          if (streamer[key] === value) continue;
          kept[key] = value;
        }
        if (Object.keys(kept).length !== Object.keys(fields).length)
          changed = true;
        if (Object.keys(kept).length) next[id] = kept;
      }
      return changed ? next : prev;
    });
  }, [data.streamers]);
  return (
    <>
      <Heading
        title="Twitch-стримеры"
        subtitle="Запись эфиров, LIVE TikTok и обработка сохранённых частей"
      >
        <Button onClick={() => setAccountsOpen(true)}>Аккаунты площадок</Button>
        <Button
          icon="refresh"
          disabled={Boolean(pending.refresh)}
          onClick={() => {
            if (pending.refresh) return;
            setPending((p) => ({ ...p, refresh: true }));
            onAction("/twitch/refresh")
              .catch((e) => setError(e.message))
              .finally(() =>
                setPending((p) => {
                  const copy = { ...p };
                  delete copy.refresh;
                  return copy;
                }),
              );
          }}
        >
          Проверить эфиры
        </Button>
        <Button
          kind="primary"
          icon="plus"
          onClick={() => {
            setError("");
            setAdding(true);
          }}
        >
          Добавить стримера
        </Button>
      </Heading>
      {!data.twitch.configured && (
        <div className="notice">
          <Icon name="info" />
          <span>
            Для автоматического обнаружения эфиров подключите Twitch API в
            настройках. Для ручного подключения включите LIVE TikTok и нажмите
            LIVE.
          </span>
          <a className="button ghost small" href="#settings">
            Настройки
          </a>
        </div>
      )}
      {(error || data.twitch.error) && !adding && (
        <p className="form-error" role="alert">
          {error || data.twitch.error}
        </p>
      )}
      {data.streamers.length ? (
        <div className="table-wrap">
          <table className="streamer-table">
            <thead>
              <tr>
                {[
                  "Отслеживать / канал",
                  "Состояние",
                  "Автозапись",
                  "Нарезки",
                  "LIVE TikTok",
                  "СДВГ-режим",
                  "Качество",
                  "",
                ].map((s, i) => (
                  <th key={i}>{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.streamers.map((s) => {
                const capture = data.jobs.find(
                  (j) =>
                    j.kind === "capture" &&
                    j.status === "recording" &&
                    j.metadata.streamer_id === s.id,
                );
                const control = (field, label) => {
                  const id = s.id + ":" + field;
                  const value = local[s.id]?.[field] ?? s[field];
                  return (
                    <button
                      role="switch"
                      aria-checked={value}
                      className={"switch " + (value ? "on" : "")}
                      aria-label={`${label} для ${s.login}`}
                      disabled={Boolean(pending[id])}
                      onClick={() => toggle(s, field)}
                    >
                      <span />
                    </button>
                  );
                };
                return (
                  <tr key={s.id}>
                    <td>
                      <div className="identity-cell">
                        {control("enabled", "Отслеживать")}
                        <div className="avatar">
                          {s.display_name[0].toUpperCase()}
                        </div>
                        <div>
                          <strong>{s.display_name}</strong>
                          <small>{s.title || "twitch.tv/" + s.login}</small>
                          <button
                            className="subtle-link"
                            onClick={() => setChannelAccounts(s)}
                          >
                            Аккаунты стримера ·{" "}
                            {
                              (data.publishing?.routes || []).filter(
                                (r) => r.streamer_id === s.id,
                              ).length
                            }
                          </button>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span
                        className={
                          "badge " +
                          (capture
                            ? "running"
                            : s.status === "live"
                              ? "success"
                              : "")
                        }
                      >
                        {capture
                          ? "Идёт запись"
                          : {
                              live: "В эфире",
                              offline: "Не в эфире",
                              waiting: "Не подключён",
                              not_found: "Не найден",
                            }[s.status] || s.status}
                      </span>
                      {s.viewers != null && (
                        <small>
                          {s.viewers.toLocaleString("ru-RU")} зрителей
                        </small>
                      )}
                    </td>
                    <td>{control("auto_record", "Автозапись")}</td>
                    <td>{control("auto_clip", "Автонарезка")}</td>
                    <td>
                      {control("live_clip", "LIVE TikTok во время эфира")}
                    </td>
                    <td>{control("adhd_mode", "СДВГ-режим")}</td>
                    <td>
                      <select
                        className="quality-select"
                        aria-label={"Качество записи для " + s.login}
                        value={s.quality}
                        onChange={(e) =>
                          onAction("/streamers/" + s.id, "PATCH", {
                            quality: e.target.value,
                          }).catch((e) => setError(e.message))
                        }
                      >
                        {["720p", "1080p", "best"].map((v) => (
                          <option key={v} value={v}>
                            {v === "best" ? "Лучшее" : v}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <div className="react-inline">
                        {capture ? (
                          <Button
                            small
                            icon="stop"
                            disabled={Boolean(pending["stop:" + capture.id])}
                            onClick={async () => {
                              const id = "stop:" + capture.id;
                              if (pending[id]) return;
                              setPending((p) => ({ ...p, [id]: true }));
                              try {
                                await onAction(
                                  "/jobs/" + capture.id + "/cancel",
                                );
                              } catch (e) {
                                setError(e.message);
                              } finally {
                                setPending((p) => {
                                  const copy = { ...p };
                                  delete copy[id];
                                  return copy;
                                });
                              }
                            }}
                          >
                            Стоп
                          </Button>
                        ) : (
                          (s.live_clip || s.status === "live") && (
                            <Button
                              small
                              kind="primary"
                              icon="record"
                              disabled={
                                !s.enabled ||
                                !s.auto_record ||
                                Boolean(pending["record:" + s.id])
                              }
                              onClick={async () => {
                                const id = "record:" + s.id;
                                if (pending[id]) return;
                                setPending((p) => ({ ...p, [id]: true }));
                                try {
                                  const j = await onAction(
                                    "/streamers/" + s.id + "/record",
                                  );
                                  onJob(j.id);
                                } catch (e) {
                                  setError(e.message);
                                } finally {
                                  setPending((p) => {
                                    const copy = { ...p };
                                    delete copy[id];
                                    return copy;
                                  });
                                }
                              }}
                            >
                              {s.live_clip ? "LIVE" : "Записать"}
                            </Button>
                          )
                        )}
                        <a
                          className="icon-button"
                          href={"https://www.twitch.tv/" + s.login}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={"Открыть канал " + s.login}
                        >
                          <Icon name="external" />
                        </a>
                        <button
                          className="icon-button"
                          aria-label={"Удалить стримера " + s.login}
                          onClick={() => {
                            setError("");
                            setRemoving(s);
                          }}
                        >
                          <Icon name="trash" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <section className="panel">
          <Empty title="Кого будем записывать?">
            Добавьте канал Twitch для записи или LIVE TikTok.
          </Empty>
        </section>
      )}
      <p className="side-note">
        Обычная запись — части по 15 минут. LIVE — непрерывная запись, сегменты
        около 2 минут и перекрывающиеся окна до 8 минут. Последние 2 минуты ждут
        развязки. LIVE требует автозапись; переключение LIVE — после остановки.
        СДВГ-режим добавляет фоновое видео без звука и применяется к следующим
        частям или LIVE-окнам. Уже поставленные в очередь ролики не меняются.
      </p>
      {accountsOpen && (
        <AccountManager
          data={data}
          onClose={() => setAccountsOpen(false)}
          onRefresh={() => onAction("/publishing", "GET")}
        />
      )}
      {channelAccounts && (
        <ChannelAccounts
          data={data}
          streamer={channelAccounts}
          onClose={() => setChannelAccounts(null)}
          onRefresh={() => onAction("/publishing", "GET")}
        />
      )}
      {adding && (
        <Modal title="Добавить стримера" onClose={() => setAdding(false)}>
          <form onSubmit={add}>
            <label className="field">
              Канал Twitch
              <input
                name="login"
                placeholder="twitch.tv/channel или логин"
                autoFocus
                required
                maxLength="100"
              />
            </label>
            <label className="field">
              Качество записи
              <select name="quality" defaultValue="720p">
                <option>720p</option>
                <option>1080p</option>
                <option value="best">Лучшее</option>
              </select>
            </label>
            {[
              ["auto_record", "Автоматически записывать эфиры", true],
              ["auto_clip", "Делать нарезки из записей", true],
              ["live_clip", "LIVE TikTok во время эфира", false],
              ["adhd_mode", "СДВГ-режим: фоновое видео снизу", false],
            ].map(([name, label, checked]) => (
              <label key={name} className="check-row">
                <input type="checkbox" name={name} defaultChecked={checked} />
                <span>{label}</span>
              </label>
            ))}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="dialog-actions">
              <Button type="button" onClick={() => setAdding(false)}>
                Отмена
              </Button>
              <Button kind="primary" type="submit" disabled={busy}>
                Добавить стримера
              </Button>
            </div>
          </form>
        </Modal>
      )}
      {removing && (
        <Modal
          title={"Удалить стримера " + removing.display_name + "?"}
          onClose={() => !removeBusy && setRemoving(null)}
        >
          <p>Будут удалены:</p>
          <ul>
            <li>автозапись эфиров и LIVE-настройки канала {removing.login};</li>
            <li>привязка аккаунтов публикации этого стримера.</li>
          </ul>
          <p className="side-note">
            Записанные файлы и готовые ролики на диске останутся.
          </p>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <Button disabled={removeBusy} onClick={() => setRemoving(null)}>
              Отмена
            </Button>
            <Button
              kind="danger"
              disabled={removeBusy}
              onClick={async () => {
                setRemoveBusy(true);
                try {
                  await onAction("/streamers/" + removing.id, "DELETE");
                  setRemoving(null);
                } catch (e) {
                  setError(e.message);
                } finally {
                  setRemoveBusy(false);
                }
              }}
            >
              Удалить
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

export function Settings({ data, onSaved, onShutdown }) {
  const [settings, setSettings] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [success, setSuccess] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    api("/settings", "GET", undefined, c.signal)
      .then(setSettings)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, []);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSuccess(false);
    const form = e.currentTarget,
      f = new FormData(form);
    try {
      await api("/settings", "POST", {
        client_id: f.get("client_id"),
        client_secret: f.get("client_secret"),
        poll_interval: Number(f.get("poll_interval")),
        verify: true,
      });
      form.elements.client_secret.value = "";
      setSuccess(true);
      onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Heading
        title="Настройки"
        subtitle="Подключение Twitch и локального движка"
      />
      <div className="settings-grid">
        <section className="panel">
          <div className="panel-header">
            <h2>Twitch API</h2>
            <span className="badge">
              {data.twitch.configured ? "Ключи сохранены" : "Не подключён"}
            </span>
          </div>
          {settings ? (
            <form className="settings-form" onSubmit={save}>
              <p>
                Создайте приложение в{" "}
                <a
                  href="https://dev.twitch.tv/console/apps"
                  target="_blank"
                  rel="noreferrer"
                >
                  консоли разработчика Twitch
                </a>
                . Ключи нужны для определения начала эфиров.
              </p>
              <label className="field">
                Client ID
                <input
                  name="client_id"
                  required
                  autoComplete="off"
                  defaultValue={settings.client_id}
                />
              </label>
              <label className="field">
                Client Secret
                <input
                  name="client_secret"
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    settings.secret_saved
                      ? "Сохранён · оставьте пустым, чтобы не менять"
                      : "Client Secret приложения Twitch"
                  }
                />
                <small>
                  Секрет шифруется Windows DPAPI и не передаётся обратно в
                  интерфейс.
                </small>
              </label>
              <label className="field">
                Проверять эфиры
                <select
                  name="poll_interval"
                  defaultValue={settings.poll_interval}
                >
                  {[30, 60, 120, 300].map((n) => (
                    <option key={n} value={n}>
                      {n} секунд
                    </option>
                  ))}
                </select>
              </label>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              {success && (
                <p className="form-success" role="status">
                  Подключение проверено. Настройки сохранены.
                </p>
              )}
              <Button type="submit" kind="primary" disabled={busy}>
                {busy ? "Проверка…" : "Сохранить и проверить"}
              </Button>
            </form>
          ) : (
            <div className="panel-body">{error || "Загрузка настроек…"}</div>
          )}
        </section>
        <div className="settings-stack">
          <section className="panel">
            <div className="panel-header">
              <h2>Локальный движок</h2>
              <span className="badge">
                {data.system.docker ? "Docker доступен" : "Docker недоступен"}
              </span>
            </div>
            <div className="panel-body">
              <p>Whisper → {data.llm?.provider ?? "Bonsai2"} → FFmpeg</p>
              <p>Свободно: {bytes(data.system.free_bytes)}</p>
              <p className="side-note">{settings?.data_directory}</p>
            </div>
          </section>
          <section className="panel">
            <div className="panel-header">
              <h2>Работа студии</h2>
            </div>
            <div className="panel-body">
              <Button kind="danger" onClick={onShutdown}>
                Завершить работу студии
              </Button>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

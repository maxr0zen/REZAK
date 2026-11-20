import React, { useEffect, useState } from "react";
import { api } from "./api";
import { Button, Modal, Empty } from "./components";

const platforms = { youtube: "YouTube", tiktok: "TikTok" };
const statuses = {
  queued: "В очереди",
  uploading: "Загрузка",
  uploaded: "Загружено на YouTube",
  inbox: "Передано в TikTok — завершите публикацию в приложении",
  processing: "TikTok обрабатывает загрузку",
  failed: "Ошибка подключения / подготовки",
  attention: "Нужно проверить аккаунт",
  cancelled: "Отменено",
  cancel_requested: "Останавливается",
};

export function AccountManager({ data, onClose, onRefresh }) {
  const [config, setConfig] = useState(null),
    [error, setError] = useState(""),
    [link, setLink] = useState(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    api("/publishing/applications", "GET", undefined, c.signal)
      .then(setConfig)
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => c.abort();
  }, []);
  async function save(e, p) {
    e.preventDefault();
    const form = e.currentTarget,
      f = new FormData(form);
    setBusy(true);
    setError("");
    try {
      await api("/publishing/applications/" + p, "POST", {
        client_id: f.get("client_id"),
        client_secret: f.get("client_secret"),
      });
      form.elements.client_secret.value = "";
      setConfig(await api("/publishing/applications"));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Аккаунты для публикации"
      onClose={onClose}
      className="publishing-dialog"
    >
      <p>
        Подключите каждый свой канал отдельно, затем закрепите его за стримером.
        Пароль площадки вводится только на её сайте.
      </p>
      <p className="side-note">
        TikTok отправляется для проверки и завершения публикации в приложении.
        YouTube получает выбранные настройки доступа; ограничения API площадки
        сохраняются.
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {config &&
        Object.entries(platforms).map(([p, label]) => (
          <section className="publishing-platform" key={p}>
            <h3>{label}</h3>
            <details>
              <summary>
                OAuth-приложение {label} ·{" "}
                {config[p].secret_saved ? "настроено" : "нужно настроить"}
              </summary>
              <form onSubmit={(e) => save(e, p)}>
                <label className="field">
                  {p === "youtube" ? "Client ID" : "Client key"}
                  <input
                    name="client_id"
                    required
                    autoComplete="off"
                    defaultValue={config[p].client_id}
                  />
                </label>
                <label className="field">
                  Client Secret
                  <input
                    name="client_secret"
                    type="password"
                    autoComplete="new-password"
                    placeholder={
                      config[p].secret_saved
                        ? "Сохранён · пустое поле сохраняет секрет"
                        : "Client Secret"
                    }
                  />
                </label>
                <p className="side-note">
                  Callback:{" "}
                  <code>
                    {location.origin}/api/publishing/oauth/{p}/callback
                  </code>
                  . Для TikTok выберите Login Kit for Desktop и разрешения
                  user.info.basic, video.upload. Для YouTube включите YouTube
                  Data API.
                </p>
                <Button type="submit" disabled={busy}>
                  Сохранить приложение
                </Button>
              </form>
            </details>
            <div className="publishing-accounts">
              {(data.publishing?.accounts || [])
                .filter((a) => a.platform === p)
                .map((a) => (
                  <div className="publishing-account" key={a.id}>
                    <div>
                      <strong>{a.name}</strong>
                      <small>
                        {a.remote_id} · {a.connected ? "Подключён" : "Отключён"}
                      </small>
                    </div>
                    {Boolean(a.connected) && (
                      <Button
                        small
                        onClick={async () => {
                          try {
                            await api(
                              "/publishing/accounts/" + a.id + "/disconnect",
                              "POST",
                            );
                            onRefresh();
                          } catch (e) {
                            setError(e.message);
                          }
                        }}
                      >
                        Отключить локально
                      </Button>
                    )}
                  </div>
                ))}
            </div>
            <Button
              disabled={busy || !config[p].secret_saved}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  setLink({
                    platform: label,
                    ...(await api("/publishing/oauth/" + p, "POST")),
                  });
                } catch (e) {
                  setError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Подключить ещё один {label}-аккаунт
            </Button>
          </section>
        ))}
      {link && (
        <div className="notice">
          <a
            className="button primary"
            href={link.url}
            target="_blank"
            rel="noreferrer"
          >
            Перейти на {link.platform} и разрешить доступ
          </a>
          <span>
            После подключения вернитесь сюда. Статус обновится автоматически.
          </span>
        </div>
      )}
      <p className="side-note">
        Токены и Client Secret хранятся через Windows DPAPI. «Отключить
        локально» удаляет доступ из Rezak; разрешение на сайте площадки
        отзывается отдельно.
      </p>
    </Modal>
  );
}

export function ChannelAccounts({ streamer, data, onClose, onRefresh }) {
  const [saved, setSaved] = useState("");
  const [tags, setTags] = useState(null);
  const routes = data.publishing?.routes || [];
  const [values, setValues] = useState(() =>
      Object.fromEntries(
        Object.keys(platforms).map((p) => [
          p,
          routes.find((r) => r.streamer_id === streamer.id && r.platform === p)
            ?.account_id || "",
        ]),
      ),
    ),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const tagsPath = "/publishing/streamers/" + streamer.id + "/tags";
  useEffect(() => {
    const controller = new AbortController();
    api(tagsPath, "GET", undefined, controller.signal)
      .then((result) => setTags(result.tags.join(", ")))
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [tagsPath]);
  return (
    <Modal title={"Аккаунты · " + streamer.display_name} onClose={onClose}>
      <p>
        Ролики этого стримера можно отправлять только в закреплённые аккаунты.
        Один аккаунт закрепляется за одним стримером.
      </p>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {Object.entries(platforms).map(([p, label]) => (
        <form
          className="publishing-route"
          key={p}
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(p);
            setError("");
            setSaved("");
            try {
              await api("/publishing/routes/" + streamer.id + "/" + p, "PUT", {
                account_id: values[p] || null,
              });
              await onRefresh();
              setSaved(label + ": привязка сохранена");
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy("");
            }
          }}
        >
          <label className="field">
            {label}
            <select
              aria-label={label + " для " + streamer.login}
              value={values[p]}
              onChange={(e) =>
                setValues((v) => ({ ...v, [p]: e.target.value }))
              }
            >
              <option value="">Не отправлять</option>
              {(data.publishing?.accounts || [])
                .filter((a) => a.platform === p && a.connected)
                .map((a) => {
                  const other = routes.find(
                    (r) =>
                      r.account_id === a.id && r.streamer_id !== streamer.id,
                  );
                  return (
                    <option key={a.id} value={a.id} disabled={Boolean(other)}>
                      {a.name}
                      {other ? " · занят другим стримером" : ""}
                    </option>
                  );
                })}
            </select>
          </label>
          <Button type="submit" disabled={Boolean(busy)}>
            {busy === p ? "Сохранение…" : "Сохранить " + label}
          </Button>
        </form>
      ))}
      {tags !== null && (
        <form
          className="publishing-route"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy("tags");
            setError("");
            setSaved("");
            try {
              const result = await api(tagsPath, "PUT", {
                tags: tags.split(","),
              });
              setTags(result.tags.join(", "));
              setSaved("Теги стримера сохранены");
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy("");
            }
          }}
        >
          <label className="field">
            Постоянные теги стримера через запятую
            <input
              value={tags}
              maxLength={500}
              onChange={(e) => setTags(e.target.value)}
            />
          </label>
          <Button type="submit" disabled={Boolean(busy)}>
            Сохранить теги
          </Button>
        </form>
      )}
      {saved && (
        <p className="form-success" role="status">
          {saved}
        </p>
      )}
      <p className="side-note">
        Если список пуст, сначала используйте «Аккаунты площадок» в разделе
        Twitch. Готовые отправки сохраняют исходный аккаунт назначения; смена
        привязки останавливает несовместимые задания.
      </p>
    </Modal>
  );
}

export function PublishClip({ clip, data, onClose, onRefresh }) {
  const [owner, setOwner] = useState(null),
    [loading, setLoading] = useState(true),
    [manual, setManual] = useState(""),
    [selection, setSelection] = useState(null),
    [history, setHistory] = useState(null),
    [repeatUploads, setRepeatUploads] = useState({}),
    [title, setTitle] = useState((clip.title || "").slice(0, 100)),
    [description, setDescription] = useState(""),
    [tags, setTags] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    api(
      "/publishing/clips/" + clip.filename + "/draft",
      "GET",
      undefined,
      c.signal,
    )
      .then((draft) => {
        setOwner(draft.streamer_id);
        setTitle(draft.title);
        setDescription(draft.description);
        setTags(draft.tags.join(", "));
        setHistory(draft.previous_uploads ?? null);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [clip.filename]);
  const previousUploads =
    history ??
    Object.fromEntries(
      (data.publishing?.jobs || [])
        .filter((job) => job.filename === clip.filename)
        .slice()
        .reverse()
        .map((job) => [job.account_id, job]),
    );
  const routes = (data.publishing?.routes || []).filter(
      (r) => r.streamer_id === owner,
    ),
    short = clip.width <= clip.height || clip.width * 3 === clip.height * 4,
    accounts = (data.publishing?.accounts || []).filter(
      (a) =>
        a.connected &&
        routes.some((r) => r.account_id === a.id) &&
        (a.platform === "youtube"
          ? !short || clip.duration_ms <= 180000
          : short && clip.duration_ms <= 600000 && clip.bytes <= 4 * 1024 ** 3),
    ),
    canSend = (id) =>
      !previousUploads[id] ||
      (history !== null &&
        ["uploaded", "inbox"].includes(previousUploads[id].status)),
    selected = accounts
      .map((a) => a.id)
      .filter(
        (id) => canSend(id) && (selection === null || selection.includes(id)),
      ),
    repeated = selected.filter((id) => previousUploads[id]),
    needsConfirmation = repeated.some(
      (id) => repeatUploads[id] !== previousUploads[id].id,
    ),
    youtube = selected.some(
      (id) => accounts.find((a) => a.id === id)?.platform === "youtube",
    );
  return (
    <Modal
      title="Отправить ролик"
      onClose={onClose}
      className="publishing-dialog publish-clip-dialog"
    >
      <h3>{clip.title}</h3>
      {loading ? (
        <p>Определяем стримера…</p>
      ) : !owner ? (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api(
                "/publishing/clips/" + clip.filename + "/owner",
                "PUT",
                { streamer_id: manual },
              );
              const draft = await api(
                "/publishing/clips/" + clip.filename + "/draft",
              );
              setTitle(draft.title);
              setDescription(draft.description);
              setTags(draft.tags.join(", "));
              setHistory(draft.previous_uploads ?? null);
              setOwner(manual);
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            У этой записи нет подтверждённой связи с Twitch-каналом. Укажите её
            вручную — по названию ролика аккаунт не угадывается.
          </p>
          <label className="field">
            Стример
            <select
              required
              value={manual}
              onChange={(e) => setManual(e.target.value)}
            >
              <option value="">Выберите стримера</option>
              {data.streamers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.display_name}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={busy || !manual}>
            Подтвердить принадлежность
          </Button>
        </form>
      ) : (
        <form
          className="publish-clip-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (needsConfirmation || !selected.length || busy) return;
            setBusy(true);
            setError("");
            try {
              await api("/publishing/jobs", "POST", {
                filename: clip.filename,
                account_ids: selected,
                ...(repeated.length && {
                  repeat_uploads: Object.fromEntries(
                    repeated.map((id) => [id, repeatUploads[id]]),
                  ),
                }),
                title,
                description,
                tags: tags
                  .split(",")
                  .map((tag) => tag.trim())
                  .filter(Boolean),
              });
              await onRefresh();
              onClose();
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p>
            Стример:{" "}
            <strong>
              {data.streamers.find((s) => s.id === owner)?.display_name}
            </strong>
          </p>
          <fieldset>
            <legend>
              {short ? "YouTube Shorts и TikTok" : "Обычное видео YouTube"}
            </legend>
            {accounts.length ? (
              accounts.map((a) => (
                <label className="check-row" key={a.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(a.id)}
                    disabled={!canSend(a.id)}
                    onChange={(e) =>
                      setSelection(
                        e.target.checked
                          ? [...selected, a.id]
                          : selected.filter((id) => id !== a.id),
                      )
                    }
                  />
                  <span>
                    {platforms[a.platform]} · {a.name}
                    {!canSend(a.id) &&
                      (history === null
                        ? " · повтор будет доступен после перезапуска Rezak"
                        : " · проверьте предыдущую отправку в очереди")}
                  </span>
                </label>
              ))
            ) : (
              <p>
                Нет доступных аккаунтов для этого формата и длительности.
                Проверьте привязки в разделе «Аккаунты стримера».
              </p>
            )}
          </fieldset>
          {repeated.map((id) => (
            <label className="check-row" key={id}>
              <input
                type="checkbox"
                checked={repeatUploads[id] === previousUploads[id].id}
                onChange={(event) => {
                  const confirmed = event.target.checked;
                  setRepeatUploads((previous) => ({
                    ...previous,
                    [id]: confirmed ? previousUploads[id].id : undefined,
                  }));
                }}
              />
              <span>
                Я понимаю, что ролик уже отправляли, и хочу выложить его ещё раз
                на {accounts.find((account) => account.id === id)?.name}.
              </span>
            </label>
          ))}
          <label className="field">
            Название
            <input
              value={title}
              maxLength="100"
              required
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="field">
            Описание
            <textarea
              rows="4"
              value={description}
              maxLength="5000"
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
          <label className="field">
            Теги через запятую
            <input
              value={tags}
              maxLength={500}
              onChange={(e) => setTags(e.target.value)}
            />
          </label>
          {youtube && (
            <p className="side-note">
              YouTube · открытый доступ · ролик не предназначен для детей.
            </p>
          )}
          {selected.some(
            (id) =>
              accounts.find((account) => account.id === id)?.platform ===
              "tiktok",
          ) && (
            <p className="side-note">
              TikTok получит черновик. Подпись можно скопировать из очереди
              отправки.
            </p>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <Button type="button" onClick={onClose}>
              Отмена
            </Button>
            <Button
              kind="primary"
              type="submit"
              disabled={busy || !selected.length || needsConfirmation}
            >
              {busy
                ? "Добавление…"
                : repeated.length
                  ? "Отправить повторно"
                  : "Отправить"}
            </Button>
          </div>
        </form>
      )}
      {error && !owner && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Modal>
  );
}

export function PublishingQueue({ data, onRefresh }) {
  const [error, setError] = useState("");
  const [review, setReview] = useState(null),
    [confirmed, setConfirmed] = useState(false);
  const jobs = data.publishing?.jobs || [];
  async function action(id, verb) {
    try {
      await api("/publishing/jobs/" + id + "/" + verb, "POST");
      await onRefresh();
    } catch (e) {
      setError(e.message);
    }
  }
  if (!jobs.length) return null;
  return (
    <section className="panel publishing-queue">
      <div className="panel-header">
        <h2>Отправка на площадки</h2>
        <span className="side-note">Отдельно от монтажа</span>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {jobs.map((j) => (
        <article className="publishing-job" key={j.id}>
          <div>
            <strong>{j.title}</strong>
            <p>
              Стример:{" "}
              {data.streamers.find((s) => s.id === j.streamer_id)
                ?.display_name || "Канал удалён"}
            </p>
            <p>
              {platforms[j.platform]} → {j.account_name}
            </p>
            <p>{statuses[j.status]}</p>
            <small>
              {j.sent.toLocaleString("ru-RU")} /{" "}
              {j.total.toLocaleString("ru-RU")} байт
            </small>
            {["uploading", "queued", "cancel_requested"].includes(j.status) && (
              <progress
                aria-label={"Отправка " + j.title}
                value={j.sent}
                max={j.total}
              />
            )}
            {j.error && <p className="side-note">{j.error}</p>}
          </div>
          <div className="react-inline">
            {j.result_url && (
              <a
                className="button ghost small"
                href={j.result_url}
                target="_blank"
                rel="noreferrer"
              >
                Открыть ролик
              </a>
            )}
            {j.platform === "tiktok" && (
              <Button
                small
                onClick={() =>
                  navigator.clipboard
                    .writeText(
                      [...new Set([j.title, ...j.description.split("\n\n")])]
                        .concat(
                          (j.tags || [])
                            .map((tag) => tag.replace(/[^\p{L}\p{N}_]/gu, ""))
                            .filter((tag) => tag && tag.length <= 40)
                            .slice(0, 4)
                            .map((tag) => "#" + tag)
                            .join(" "),
                        )
                        .filter(Boolean)
                        .join("\n\n"),
                    )
                    .catch(() => setError("Не удалось скопировать текст"))
                }
              >
                Копировать текст
              </Button>
            )}
            {["queued", "uploading"].includes(j.status) && (
              <Button small onClick={() => action(j.id, "cancel")}>
                Отменить
              </Button>
            )}
            {["failed", "cancelled"].includes(j.status) && (
              <Button small onClick={() => action(j.id, "retry")}>
                Повторить
              </Button>
            )}
            {j.status === "attention" && (
              <Button
                small
                onClick={() => {
                  setConfirmed(false);
                  setReview(j);
                }}
              >
                Проверить перед повтором
              </Button>
            )}
          </div>
        </article>
      ))}
      {review && (
        <Modal
          title="Проверка перед повторной отправкой"
          onClose={() => setReview(null)}
        >
          <p>
            {review.title} → {review.account_name}
          </p>
          <p>
            Откройте этот аккаунт на площадке и проверьте, появился ли ролик.
            Повторная отправка может создать дубль, если предыдущая успела
            завершиться.
          </p>
          <label className="check-row">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>Я проверил аккаунт — этого ролика там нет</span>
          </label>
          <div className="dialog-actions">
            <Button onClick={() => setReview(null)}>Вернуться</Button>
            <Button
              disabled={!confirmed}
              onClick={async () => {
                try {
                  await api(
                    "/publishing/jobs/" + review.id + "/review-retry",
                    "POST",
                    { confirmed_not_sent: true },
                  );
                  setReview(null);
                  await onRefresh();
                } catch (e) {
                  setError(e.message);
                }
              }}
            >
              Разрешить повтор
            </Button>
          </div>
        </Modal>
      )}
    </section>
  );
}

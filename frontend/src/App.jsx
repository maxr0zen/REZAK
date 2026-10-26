import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, bytes, duration, names } from "./api";
import { Icon } from "./icons";
import {
  Button,
  Heading,
  Empty,
  Modal,
  JobDetails,
  JobRow,
  Journal,
} from "./components";
import { Twitch, Settings } from "./TwitchSettings";
import Editor from "./Editor";
import { PublishClip, PublishingQueue } from "./Publishing";

function Clips({
  clips,
  onUpload,
  onEdit,
  onPublish,
  onPlay,
  onDelete,
  selected,
  setSelected,
  query,
  setQuery,
  filter,
  setFilter,
}) {
  const visible = clips.filter(
    (c) =>
      (filter === "all" || c.profile === filter) &&
      (c.title || c.source_id).toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <Heading
        title="Готовые нарезки"
        subtitle={`${clips.length} актуальных экспортов · исходные записи сохранены`}
      >
        <Button
          icon="folder"
          onClick={() => api("/open-exports", "POST").catch(onDelete.error)}
        >
          Папка результатов
        </Button>
        <Button icon="upload" kind="primary" onClick={onUpload}>
          Добавить видео
        </Button>
      </Heading>
      <div className="tabs-row">
        <div className="tabs">
          {[
            ["all", "Все форматы"],
            ["vertical", "Вертикальные 9:16"],
            ["horizontal", "Подборки 16:9"],
          ].map(([v, l]) => (
            <button
              key={v}
              className={"tab " + (filter === v ? "active" : "")}
              onClick={() => setFilter(v)}
            >
              {l}
            </button>
          ))}
        </div>
        <input
          className="search"
          aria-label="Поиск нарезок"
          placeholder="Поиск нарезок"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="clip-selection" role="group" aria-label="Выбор роликов">
        <Button
          small
          onClick={() =>
            setSelected(
              (old) => new Set([...old, ...visible.map((c) => c.filename)]),
            )
          }
        >
          Выбрать видимые ({visible.length})
        </Button>
        <span aria-live="polite">Выбрано: {selected.size}</span>
        <Button
          small
          disabled={!selected.size}
          onClick={() => setSelected(new Set())}
        >
          Снять выбор
        </Button>
        <Button
          kind="danger"
          small
          disabled={!selected.size}
          onClick={() =>
            onDelete(clips.filter((c) => selected.has(c.filename)))
          }
        >
          Удалить выбранные
        </Button>
      </div>
      {visible.length ? (
        <div className="clip-grid">
          {visible.map((c) => (
            <article
              className={
                "clip-card " + (selected.has(c.filename) ? "is-selected" : "")
              }
              key={c.filename}
            >
              <label className="clip-select">
                <input
                  type="checkbox"
                  aria-label={"Выбрать " + c.title}
                  checked={selected.has(c.filename)}
                  onChange={(e) =>
                    setSelected((old) => {
                      const next = new Set(old);
                      e.target.checked
                        ? next.add(c.filename)
                        : next.delete(c.filename);
                      return next;
                    })
                  }
                />
                <span>Выбрать</span>
              </label>
              <button
                className="clip-preview"
                aria-label={"Смотреть " + c.title}
                onClick={() => onPlay(c)}
              >
                <img
                  src={"/api/covers/" + c.filename}
                  loading="lazy"
                  alt={"Кадр из " + c.title}
                />
                <span className="clip-play">
                  <Icon name="play" />
                </span>
                <span className="clip-labels">
                  <span>{c.profile === "vertical" ? "9:16" : "16:9"}</span>
                  <span>{duration(c.duration_ms)}</span>
                </span>
              </button>
              <div className="clip-card-body">
                <h2 className="clip-card-title">{c.title || c.source_id}</h2>
                <div className="clip-card-meta">
                  <span>
                    {c.width} × {c.height} · {bytes(c.bytes)}
                  </span>
                  <a
                    className="icon-button"
                    aria-label={"Скачать " + c.title}
                    href={"/api/clips/" + c.filename + "?download=true"}
                  >
                    <Icon name="download" />
                  </a>
                </div>
                <div className="clip-actions">
                  <Button small icon="settings" onClick={() => onEdit(c)}>
                    Редактировать
                  </Button>
                  <Button small icon="upload" onClick={() => onPublish(c)}>
                    Отправить
                  </Button>
                  <button
                    className="icon-button delete-clip"
                    aria-label={"Удалить " + c.title}
                    onClick={() => onDelete([c])}
                  >
                    <Icon name="trash" />
                  </button>
                </div>
                {c.test_fixture && (
                  <span className="test-label">
                    Синтетическая тестовая запись
                  </span>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <section className="panel">
          <Empty title="Пока нет роликов">
            {query
              ? "Попробуйте другое название."
              : "После обработки здесь появятся готовые нарезки."}
          </Empty>
        </section>
      )}
    </>
  );
}

export default function App() {
  const [view, setView] = useState(
      names[location.hash.slice(1)] ? location.hash.slice(1) : "overview",
    ),
    [data, setData] = useState(null),
    [connection, setConnection] = useState("Подключение"),
    [selectedJob, setSelectedJob] = useState(null),
    [queueFilter, setQueueFilter] = useState("all"),
    [clipFilter, setClipFilter] = useState("all"),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState(new Set()),
    [profile, setProfile] = useState("both"),
    [upload, setUpload] = useState(null),
    [toast, setToast] = useState(null),
    [playing, setPlaying] = useState(null),
    [editing, setEditing] = useState(null),
    [publishingClip, setPublishingClip] = useState(null),
    [deleting, setDeleting] = useState(null),
    [deleteError, setDeleteError] = useState(""),
    [deleteBusy, setDeleteBusy] = useState(false),
    [trash, setTrash] = useState(null),
    [shutdown, setShutdown] = useState(false);
  const input = useRef(null),
    xhr = useRef(null),
    uploadBusy = useRef(false),
    cancelUpload = useRef(false),
    toastTimer = useRef(null),
    alive = useRef(true),
    statusSequence = useRef(0);
  const notify = useCallback((message, error = false) => {
    clearTimeout(toastTimer.current);
    setToast({ message, error });
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);
  const refresh = useCallback(async () => {
    const seq = ++statusSequence.current;
    try {
      const result = await api("/status");
      if (!alive.current || seq !== statusSequence.current) return;
      setData(result);
      setConnection("Служба работает");
      setSelectedJob(
        (old) =>
          old ||
          result.jobs.find((j) => ["running", "recording"].includes(j.status))
            ?.id ||
          result.jobs[0]?.id ||
          null,
      );
      setSelected(
        (old) =>
          new Set(
            [...old].filter((name) =>
              result.clips.some((c) => c.filename === name),
            ),
          ),
      );
    } catch (e) {
      if (alive.current) setConnection("Нет связи: " + e.message);
    }
  }, []);
  useEffect(() => {
    alive.current = true;
    let timer,
      stopped = false;
    async function poll() {
      await refresh();
      if (!stopped) timer = setTimeout(poll, 1800);
    }
    poll();
    return () => {
      stopped = true;
      alive.current = false;
      clearTimeout(timer);
      clearTimeout(toastTimer.current);
    };
  }, [refresh]);
  useEffect(() => {
    const changed = () =>
      setView(
        names[location.hash.slice(1)] ? location.hash.slice(1) : "overview",
      );
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    document.body.dataset.view = view;
  }, [view]);
  const navigate = (v) => {
    location.hash = v;
    setView(v);
  };
  const action = useCallback(
    async (path, method = "POST", body) => {
      const result = await api(path, method, body);
      await refresh();
      return result;
    },
    [refresh],
  );
  const safeAction = (...args) =>
    action(...args).catch((e) => notify(e.message, true));
  const pickJob = (id) => {
    setSelectedJob(id);
    navigate("queue");
  };
  async function uploadFiles(files) {
    if (uploadBusy.current) {
      notify("Дождитесь завершения текущей загрузки", true);
      return;
    }
    const list = Array.from(files || []);
    if (!list.length) return;
    uploadBusy.current = true;
    cancelUpload.current = false;
    try {
      for (let i = 0; i < list.length; i++) {
        if (cancelUpload.current) break;
        const file = list[i];
        if (file.size > 20 * 1024 ** 3) {
          notify(file.name + " превышает 20 ГБ", true);
          continue;
        }
        setUpload({
          name: file.name,
          index: i + 1,
          total: list.length,
          progress: 0,
        });
        try {
          const job = await new Promise((resolve, reject) => {
            const request = new XMLHttpRequest();
            xhr.current = request;
            request.open("POST", "/api/uploads");
            request.setRequestHeader("X-Rezak-Client", "1");
            request.upload.onprogress = (e) => {
              if (e.lengthComputable)
                setUpload((old) =>
                  old ? { ...old, progress: (e.loaded / e.total) * 100 } : old,
                );
            };
            request.onload = () => {
              try {
                const result = JSON.parse(request.responseText);
                request.status < 300
                  ? resolve(result)
                  : reject(new Error(result.detail || "Ошибка загрузки"));
              } catch {
                reject(new Error("Некорректный ответ сервера"));
              }
            };
            request.onerror = () => reject(new Error("Соединение прервалось"));
            request.onabort = () => reject(new Error("Загрузка отменена"));
            const f = new FormData();
            f.append("file", file);
            f.append("profile", profile);
            request.send(f);
          });
          setSelectedJob(job.id);
          notify("Видео добавлено в очередь");
          await refresh();
          navigate("queue");
        } catch (e) {
          notify(e.message, true);
          if (cancelUpload.current) break;
        }
      }
    } finally {
      uploadBusy.current = false;
      xhr.current = null;
      setUpload(null);
      if (input.current) input.current.value = "";
    }
  }
  const uploadButton = (
    <Button kind="primary" icon="upload" onClick={() => input.current.click()}>
      Добавить видео
    </Button>
  );
  const job = data?.jobs.find((j) => j.id === selectedJob) || null,
    gpu = data?.system.gpu;
  let page;
  if (!data)
    page = (
      <>
        <Heading title="Открываем студию…" subtitle={connection} />
        <section className="panel">
          <Empty title="Подключение к локальному движку">
            Если служба не запущена, используйте scripts/start-studio.ps1.
          </Empty>
        </section>
      </>
    );
  else if (view === "clips")
    page = (
      <>
        <Clips
          clips={data.clips}
          onUpload={() => input.current.click()}
          onEdit={setEditing}
          onPublish={setPublishingClip}
          onPlay={setPlaying}
          selected={selected}
          setSelected={setSelected}
          query={query}
          setQuery={setQuery}
          filter={clipFilter}
          setFilter={setClipFilter}
          onDelete={Object.assign(
            (clips) => {
              setDeleting(clips);
              setDeleteError("");
            },
            { error: (e) => notify(e.message, true) },
          )}
        />
        <PublishingQueue data={data} onRefresh={refresh} />
      </>
    );
  else if (view === "twitch")
    page = <Twitch data={data} onAction={action} onJob={pickJob} />;
  else if (view === "settings")
    page = (
      <Settings
        data={data}
        onSaved={refresh}
        onShutdown={() => setShutdown(true)}
      />
    );
  else if (view === "queue") {
    const jobs = data.jobs.filter(
      (j) =>
        queueFilter === "all" ||
        (queueFilter === "active" &&
          ["running", "recording", "queued"].includes(j.status)) ||
        (queueFilter === "done" && j.status === "done") ||
        (queueFilter === "error" &&
          ["error", "interrupted", "cancelled"].includes(j.status)),
    );
    page = (
      <>
        <Heading
          title="Очередь обработки"
          subtitle={
            data.queue_paused
              ? "На паузе · текущая задача продолжает работу"
              : "Запись Twitch работает независимо от очереди"
          }
        >
          <Button
            icon={data.queue_paused ? "play" : "pause"}
            onClick={() =>
              safeAction("/queue", "POST", { paused: !data.queue_paused })
            }
          >
            {data.queue_paused ? "Продолжить очередь" : "Пауза очереди"}
          </Button>
          {uploadButton}
        </Heading>
        <div className="tabs-row">
          <div className="tabs">
            {[
              ["all", "Все"],
              ["active", "Активные"],
              ["done", "Готовые"],
              ["error", "Требуют внимания"],
            ].map(([v, l]) => (
              <button
                key={v}
                className={"tab " + (queueFilter === v ? "active" : "")}
                onClick={() => setQueueFilter(v)}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
        <div className="queue-layout">
          <section className="panel queue-list">
            {jobs.length ? (
              jobs.map((j) => (
                <JobRow
                  key={j.id}
                  job={j}
                  selected={j.id === selectedJob}
                  onSelect={setSelectedJob}
                />
              ))
            ) : (
              <Empty title="Очередь пуста">
                Добавьте видео или запустите запись.
              </Empty>
            )}
          </section>
          <div className="queue-details">
            <JobDetails job={job} stages={data.stages} onAction={safeAction} />
            <Journal job={job} />
          </div>
        </div>
      </>
    );
  } else
    page = (
      <>
        <Heading
          title="Локальная студия"
          subtitle="Запись, отбор моментов и монтаж на этом компьютере"
        >
          {uploadButton}
        </Heading>
        <div className="overview-grid">
          <div className="work-column">
            <section className="source-tray">
              <div
                className="dropzone"
                role="button"
                tabIndex="0"
                aria-label="Добавить видео для обработки"
                onClick={() => input.current.click()}
                onKeyDown={(e) => {
                  if (["Enter", " "].includes(e.key)) {
                    e.preventDefault();
                    input.current.click();
                  }
                }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  uploadFiles(e.dataTransfer.files);
                }}
              >
                <div className="drop-symbol">
                  <Icon name="upload" />
                </div>
                <div>
                  <h2>Добавить запись стрима</h2>
                  <p>Перетащите видео сюда · до 20 ГБ</p>
                </div>
                <Icon name="plus" />
              </div>
              <label className="upload-format">
                Экспорт
                <select
                  aria-label="Формат экспорта"
                  value={profile}
                  onChange={(e) => setProfile(e.target.value)}
                >
                  <option value="both">9:16 + 16:9</option>
                  <option value="vertical">9:16</option>
                  <option value="horizontal">16:9</option>
                </select>
              </label>
            </section>
            <JobDetails job={job} stages={data.stages} onAction={safeAction} />
            <Journal job={job} />
          </div>
          <aside className="side-column">
            <section className="panel">
              <div className="panel-header">
                <h2>Twitch · {data.streamers.length}</h2>
                <a className="subtle-link" href="#twitch">
                  Все каналы
                </a>
              </div>
              {data.streamers.length ? (
                data.streamers.slice(0, 4).map((s) => (
                  <div className="watcher-row" key={s.id}>
                    <div className="avatar">
                      {s.display_name[0].toUpperCase()}
                    </div>
                    <div className="watcher-name">
                      <strong>{s.display_name}</strong>
                      <small>
                        {s.live_clip
                          ? "LIVE TikTok"
                          : s.auto_record
                            ? "Автозапись включена"
                            : "Отслеживание"}
                      </small>
                    </div>
                    <span className="badge">
                      {s.status === "live"
                        ? "В эфире"
                        : s.status === "offline"
                          ? "Не в эфире"
                          : "Не подключён"}
                    </span>
                  </div>
                ))
              ) : (
                <Empty title="Ваши стримеры — здесь">
                  Добавьте канал в разделе Twitch.
                </Empty>
              )}
            </section>
            <section className="panel">
              <div className="panel-header">
                <h2>Последние результаты</h2>
                <a className="subtle-link" href="#clips">
                  Все ролики
                </a>
              </div>
              {data.clips.slice(0, 3).map((c) => (
                <button
                  className="react-result-row"
                  key={c.filename}
                  onClick={() => setPlaying(c)}
                >
                  <img src={"/api/covers/" + c.filename} alt="" />
                  <span>
                    {c.title}
                    <small>{duration(c.duration_ms)}</small>
                  </span>
                  <Icon name="play" />
                </button>
              ))}
              {!data.clips.length && (
                <Empty title="Пока нет роликов">
                  Готовые результаты появятся здесь.
                </Empty>
              )}
            </section>
          </aside>
        </div>
      </>
    );
  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        К содержимому
      </a>
      <aside className="sidebar">
        <a className="brand" href="#overview" aria-label="Rezak — обзор">
          <img src="/static/mark.svg" alt="" width="29" height="32" />
          <span>
            REZAK<span className="brand-dot">.</span>
          </span>
        </a>
        <div className="workspace-label">
          <span className="tiny-dot" /> Локальная студия
        </div>
        <nav aria-label="Основная навигация">
          {["overview", "twitch", "queue", "clips"].map((v) => (
            <a
              key={v}
              className={"nav-item " + (view === v ? "active" : "")}
              href={"#" + v}
              aria-current={view === v ? "page" : undefined}
              title={names[v]}
            >
              <Icon name={v} />
              <span className="nav-label">{names[v]}</span>
              {data && v !== "overview" && (
                <span className="nav-count">
                  {v === "twitch"
                    ? data.streamers.length
                    : v === "clips"
                      ? data.clips.length
                      : data.jobs.filter((j) =>
                          ["queued", "running", "recording"].includes(j.status),
                        ).length}
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="gpu-summary">
            <div className="gpu-title">
              <Icon name="chip" />
              <span>{gpu?.name || "GPU · проверка"}</span>
            </div>
            {gpu && (
              <>
                <progress
                  value={gpu.used_mib}
                  max={gpu.total_mib}
                  aria-label="Использование видеопамяти"
                />
                <span>
                  {(gpu.used_mib / 1024).toFixed(1)} /{" "}
                  {(gpu.total_mib / 1024).toFixed(1)} ГБ VRAM
                </span>
              </>
            )}
          </div>
          <a
            href="#settings"
            aria-current={view === "settings" ? "page" : undefined}
            className={"nav-item " + (view === "settings" ? "active" : "")}
          >
            <Icon name="settings" />
            <span className="nav-label">Настройки</span>
          </a>
          <div className="version-row">
            <span>Rezak Studio</span>
            <span>React</span>
          </div>
        </div>
      </aside>
      <div className="application">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Студия</span>
            <span className="breadcrumb-slash">/</span>
            <span>{names[view]}</span>
          </div>
          <div className="topbar-right">
            <span
              className={
                "connection " +
                (connection === "Служба работает" ? "ready" : "error")
              }
            >
              <span className="tiny-dot" />
              {connection}
            </span>
            <span className="local-badge">На этом компьютере</span>
          </div>
        </header>
        <main id="main" tabIndex="-1">
          {page}
        </main>
        <footer className="statusbar">
          <span>
            {data?.system.docker === false
              ? "Docker не запущен · откройте Docker Desktop"
              : data
                ? `${data.queue_paused ? "Очередь на паузе" : "Локальная очередь активна"} · свободно ${bytes(data.system.free_bytes)}`
                : connection}
          </span>
          <span>ASR → Bonsai2 → FFmpeg · React / FastAPI</span>
        </footer>
      </div>
      <input
        ref={input}
        type="file"
        accept=".mp4,.mkv,.mov,.webm,.ts,.m4v"
        multiple
        hidden
        aria-label="Файлы для обработки"
        onChange={(e) => uploadFiles(e.target.files)}
      />
      {upload && (
        <div className="upload-status">
          <div className="upload-status-top">
            <span>
              Добавление видео · {upload.index}/{upload.total}
            </span>
            <button
              className="icon-button"
              aria-label="Отменить загрузку"
              onClick={() => {
                cancelUpload.current = true;
                xhr.current?.abort();
              }}
            >
              <Icon name="close" />
            </button>
          </div>
          <progress
            value={upload.progress}
            max="100"
            aria-label="Загрузка файла"
          />
          <p>{upload.name}</p>
        </div>
      )}
      {toast && (
        <div id="toast" role="status" className={toast.error ? "error" : ""}>
          {toast.message}
        </div>
      )}
      {playing && (
        <Modal
          title={playing.title}
          onClose={() => setPlaying(null)}
          className="player-dialog"
        >
          <video
            src={"/api/clips/" + playing.filename}
            controls
            playsInline
            autoPlay
            aria-label="Просмотр нарезки"
          />
          <div className="player-footer">
            <span>
              {playing.width} × {playing.height} ·{" "}
              {duration(playing.duration_ms)}
            </span>
            <a
              className="button primary"
              href={"/api/clips/" + playing.filename + "?download=true"}
              download
            >
              Скачать ролик
            </a>
          </div>
        </Modal>
      )}
      {editing && (
        <Editor
          clip={editing}
          onClose={() => setEditing(null)}
          onSaved={(id) => {
            refresh();
            if (id) pickJob(id);
            notify(
              id ? "Новая копия добавлена в очередь" : "Название сохранено",
            );
          }}
        />
      )}
      {publishingClip && (
        <PublishClip
          clip={publishingClip}
          data={data}
          onClose={() => setPublishingClip(null)}
          onRefresh={refresh}
        />
      )}
      {deleting && (
        <Modal
          title={`Удалить ролики (${deleting.length})?`}
          onClose={() => !deleteBusy && setDeleting(null)}
        >
          <p>{deleting.map((c) => c.title).join("; ")}</p>
          <p className="side-note">
            Ролики и одинаковые повторные экспорты будут перемещены во
            внутреннюю корзину. Исходники останутся.
          </p>
          {deleteError && (
            <p className="form-error" role="alert">
              {deleteError}
            </p>
          )}
          <div className="dialog-actions">
            <Button disabled={deleteBusy} onClick={() => setDeleting(null)}>
              Отмена
            </Button>
            <Button
              kind="danger"
              disabled={deleteBusy}
              onClick={async () => {
                setDeleteBusy(true);
                try {
                  const result = await action("/clips/delete-many", "POST", {
                    filenames: deleting.map((c) => c.filename),
                  });
                  setTrash(result.token);
                  setSelected(
                    (old) =>
                      new Set(
                        [...old].filter(
                          (n) => !deleting.some((c) => c.filename === n),
                        ),
                      ),
                  );
                  setDeleting(null);
                  notify("Ролики перемещены в корзину");
                } catch (e) {
                  setDeleteError(e.message);
                } finally {
                  setDeleteBusy(false);
                }
              }}
            >
              Удалить
            </Button>
          </div>
        </Modal>
      )}
      {trash && (
        <div className="clip-undo" role="status">
          <span>Ролики в корзине</span>
          <Button
            small
            onClick={async () => {
              try {
                await action("/trash/" + trash + "/restore");
                setTrash(null);
                notify("Нарезки восстановлены");
              } catch (e) {
                notify(e.message, true);
              }
            }}
          >
            Восстановить
          </Button>
          <button
            className="icon-button"
            aria-label="Скрыть уведомление"
            onClick={() => setTrash(null)}
          >
            <Icon name="close" />
          </button>
        </div>
      )}
      {shutdown && (
        <Modal
          title="Завершить работу студии?"
          onClose={() => setShutdown(false)}
        >
          <p>
            Текущая запись и обработка остановятся. Сохранённые видео и история
            останутся на диске.
          </p>
          <div className="dialog-actions">
            <Button onClick={() => setShutdown(false)}>
              Продолжить работу
            </Button>
            <Button kind="danger" onClick={() => safeAction("/shutdown")}>
              Завершить
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

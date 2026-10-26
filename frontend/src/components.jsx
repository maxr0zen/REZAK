import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, bytes, duration, timeOf, statusName } from "./api";
import { Icon } from "./icons";

export function Button({
  icon,
  children,
  kind = "ghost",
  small = false,
  ...props
}) {
  return (
    <button className={`button ${kind} ${small ? "small" : ""}`} {...props}>
      {icon && <Icon name={icon} />}
      {children}
    </button>
  );
}
export function Heading({ title, subtitle, children }) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="heading-actions">{children}</div>
    </div>
  );
}
export function Empty({ title, children }) {
  return (
    <div className="empty-state">
      <div className="empty-symbol">
        <Icon name="file" />
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Badge({ job }) {
  return (
    <span
      className={`badge ${["running", "recording"].includes(job.status) ? "running" : job.status === "done" ? "success" : job.status === "error" ? "error" : ""}`}
    >
      {statusName(job)}
    </span>
  );
}
export function Modal({ title, children, onClose, className = "" }) {
  const ref = useRef(null),
    close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const node = ref.current;
    node.showModal();
    return () => {
      node.querySelectorAll("video").forEach((v) => v.pause());
      node.close();
    };
  }, []);
  return (
    <dialog
      className={className}
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        close.current();
      }}
      aria-labelledby="modal-title"
    >
      <div className="dialog-heading">
        <h2 id="modal-title">{title}</h2>
        <button className="icon-button" aria-label="Закрыть" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function JobRow({ job, selected, onSelect }) {
  return (
    <button
      className={`task-row ${selected ? "selected" : ""}`}
      onClick={() => onSelect(job.id)}
    >
      <span className="file-symbol">
        <Icon name={job.kind === "capture" ? "record" : "file"} />
      </span>
      <span className="task-row-main">
        <span className="task-title">{job.title}</span>
        <span className="task-meta">
          <Badge job={job} />
          <span>
            {job.metadata.live_mode || job.metadata.operation === "live"
              ? "LIVE"
              : job.kind === "capture"
                ? "Twitch"
                : job.profile === "both"
                  ? "9:16 + 16:9"
                  : job.profile === "vertical"
                    ? "9:16"
                    : "16:9"}
          </span>
          <span>
            {job.metadata.duration_ms
              ? duration(job.metadata.duration_ms)
              : bytes(job.metadata.bytes)}
          </span>
        </span>
        {job.status === "running" && (
          <progress
            value={job.progress}
            max="100"
            aria-label="Прогресс задачи"
          />
        )}
      </span>
      <span className="task-fraction">
        {job.status === "running" ? (
          Math.floor(job.progress) + "%"
        ) : (
          <Icon name="chevron" />
        )}
      </span>
    </button>
  );
}
export function JobDetails({ job, stages, onAction }) {
  if (!job)
    return (
      <section className="panel">
        <Empty title="Очередь пуста">
          Добавьте видео или подключите Twitch.
        </Empty>
      </section>
    );
  const active = ["running", "recording", "queued"].includes(job.status),
    phase = job.stages?.[job.stage] || {},
    recording = job.status === "recording";
  return (
    <section className="panel job-detail">
      <div className="active-job">
        <div className="active-job-top">
          <div className="active-job-title">
            <span className="file-symbol">
              <Icon name={job.kind === "capture" ? "record" : "file"} />
            </span>
            <div>
              <h3>{job.title}</h3>
              <p>
                {job.metadata.live_mode
                  ? "LIVE TikTok"
                  : job.kind === "capture"
                    ? "Запись Twitch"
                    : "Обработка записи"}{" "}
                · {job.id.slice(0, 8)}
              </p>
            </div>
          </div>
          {active ? (
            <Button
              icon="stop"
              small
              aria-label="Остановить задачу"
              onClick={() => onAction("/jobs/" + job.id + "/cancel")}
            >
              Стоп
            </Button>
          ) : ["error", "cancelled", "interrupted"].includes(job.status) &&
            job.kind !== "capture" ? (
            <Button
              small
              icon="refresh"
              onClick={() => onAction("/jobs/" + job.id + "/retry")}
            >
              Повторить
            </Button>
          ) : null}
        </div>
        <div className="progress-heading">
          <span>{recording ? "Запись эфира" : statusName(job)}</span>
          <span className="progress-number">
            {recording
              ? bytes(job.metadata.bytes)
              : Math.floor(job.progress) + "%"}
          </span>
        </div>
        <progress
          value={recording ? undefined : job.progress}
          max="100"
          aria-label="Общий прогресс обработки"
        />
        <div className="active-detail">{job.detail || "Ожидает обработки"}</div>
        <div className="detail-measures">
          <span>
            <strong>
              {duration(
                ((job.finished || Date.now() / 1000) -
                  (job.started || job.created)) *
                  1000,
              )}
            </strong>
            Прошло времени
          </span>
          {phase.processed_ms !== undefined && (
            <span>
              <strong>
                {duration(phase.processed_ms)} / {duration(phase.total_ms)}
              </strong>
              Обработано медиа
            </span>
          )}
          {phase.windows_total && (
            <span>
              <strong>
                {phase.windows_done} / {phase.windows_total}
              </strong>
              Смысловых окон
            </span>
          )}
          <span>
            <strong>
              {job.metadata.duration_ms || job.metadata.captured_ms
                ? duration(job.metadata.duration_ms || job.metadata.captured_ms)
                : "—"}
            </strong>
            Исходник
          </span>
          {job.metadata.live_mode && (
            <>
              <span>
                <strong>{duration(job.metadata.processed_ms)}</strong>LIVE
                обработано
              </span>
              <span>
                <strong>{duration(job.metadata.lag_ms)}</strong>Отставание
                обработки
              </span>
              <span>
                <strong>{job.metadata.pending_windows ?? 0}</strong>Окон в
                очереди
              </span>
            </>
          )}
        </div>
      </div>
      {job.kind !== "capture" && (
        <div className="pipeline-stages">
          {stages.map((s) => (
            <div
              key={s.id}
              className={`pipeline-stage ${job.stages?.[s.id]?.status || ""}`}
            >
              <span>
                {s.label} ·{" "}
                {(job.kind === "clip_edit" && ["asr", "llm"].includes(s.id)) ||
                (job.kind === "clip_refine" && s.id === "asr")
                  ? "Не требуется"
                  : job.stages?.[s.id]
                    ? Math.floor(job.stages[s.id].progress * 100) + "%"
                    : "Ожидание"}
              </span>
              <progress
                value={(job.stages?.[s.id]?.progress || 0) * 100}
                max="100"
              />
            </div>
          ))}
        </div>
      )}
      {job.error && (
        <div className="job-error" role="alert">
          {job.error}
        </div>
      )}
      {job.kind === "capture" && !active && (
        <div className="panel-body">
          <Button
            small
            icon="refresh"
            onClick={() => onAction("/jobs/" + job.id + "/recover")}
          >
            Обработать сохранённые части
          </Button>
        </div>
      )}
    </section>
  );
}
export function Journal({ job }) {
  const [rows, setRows] = useState([]),
    [filter, setFilter] = useState("all"),
    [follow, setFollow] = useState(true),
    ref = useRef(null),
    followRef = useRef(true),
    jobId = job?.id || null;
  useEffect(() => {
    setRows([]);
    setFollow(true);
    followRef.current = true;
    let alive = true,
      timer,
      after = 0;
    const controller = new AbortController();
    async function poll() {
      try {
        const result = await api(
          "/logs?" +
            new URLSearchParams({ ...(jobId ? { job_id: jobId } : {}), after }),
          "GET",
          undefined,
          controller.signal,
        );
        if (!alive) return;
        if (result.length) {
          after = result.at(-1).id;
          setRows((old) => {
            const ids = new Set(old.map((r) => r.id));
            const merged = [...old, ...result.filter((r) => !ids.has(r.id))];
            return !followRef.current ||
              ref.current?.contains(window.getSelection()?.anchorNode)
              ? merged
              : merged.slice(-5000);
          });
        }
      } catch (e) {
        if (e.name !== "AbortError") console.warn("Journal:", e.message);
      }
      if (alive) timer = setTimeout(poll, 1600);
    }
    poll();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [jobId]);
  useEffect(() => {
    const selected = () => {
      if (
        ref.current?.contains(window.getSelection()?.anchorNode) &&
        !window.getSelection()?.isCollapsed
      ) {
        followRef.current = false;
        setFollow(false);
      }
    };
    document.addEventListener("selectionchange", selected);
    return () => document.removeEventListener("selectionchange", selected);
  }, []);
  useLayoutEffect(() => {
    if (followRef.current && ref.current)
      ref.current.scrollTop = ref.current.scrollHeight;
  }, [rows, filter]);
  const shown =
    filter === "all"
      ? rows
      : rows.filter((r) => ["error", "warning"].includes(r.level));
  const resume = () => {
    followRef.current = !follow;
    setFollow(!follow);
    if (!follow && ref.current)
      ref.current.scrollTop = ref.current.scrollHeight;
  };
  return (
    <section className="console">
      <div className="console-header">
        <div className="console-title">
          <Icon name="terminal" />
          <span>{job ? "Журнал обработки" : "Системный журнал"}</span>
        </div>
        <div className="console-actions">
          <select
            aria-label="Уровень журнала"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">Все события</option>
            <option value="error">Ошибки и предупреждения</option>
          </select>
          {job && (
            <a
              href={"/api/jobs/" + job.id + "/log"}
              className="icon-button"
              aria-label="Скачать журнал"
            >
              <Icon name="download" />
            </a>
          )}
          <button
            className="follow-button"
            aria-label="Автопрокрутка журнала"
            aria-pressed={follow}
            onClick={resume}
          >
            <Icon name={follow ? "pause" : "arrow"} />
            <span>{follow ? "В реальном времени" : "К новым событиям"}</span>
          </button>
        </div>
      </div>
      <div
        ref={ref}
        id="log-content"
        className="log-content"
        role="log"
        aria-live="off"
        tabIndex="0"
        aria-label="Журнал событий"
        onScroll={(e) => {
          const n = e.currentTarget;
          const bottom = n.scrollHeight - n.scrollTop - n.clientHeight < 24;
          followRef.current = bottom;
          setFollow(bottom);
        }}
      >
        {shown.length ? (
          shown.map((r) => (
            <div
              className={"log-line " + r.level}
              data-log-id={r.id}
              key={r.id}
            >
              <span className="log-time">{timeOf(r.at)}</span>
              <span className="log-level">
                {
                  {
                    info: "INFO",
                    warning: "WARN",
                    error: "ERROR",
                    success: "OK",
                  }[r.level]
                }
              </span>
              <span className="log-message">{r.message}</span>
            </div>
          ))
        ) : (
          <p className="log-empty">
            {filter === "error"
              ? "Ошибок и предупреждений нет."
              : "Здесь появятся события обработки."}
          </p>
        )}
      </div>
      <div className="console-footer">
        <span>События от движка</span>
        <span>{job ? "Задача " + job.id.slice(0, 8) : "Локальная служба"}</span>
      </div>
    </section>
  );
}

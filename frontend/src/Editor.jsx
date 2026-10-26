import React, { useEffect, useRef, useState } from "react";
import { api, duration } from "./api";
import { Button, Modal } from "./components";

const full = { x: 0, y: 0, w: 1, h: 1 };
export default function Editor({ clip, onClose, onSaved }) {
  const [title, setTitle] = useState(clip.title || clip.source_id),
    [instruction, setInstruction] = useState(""),
    [start, setStart] = useState(0),
    [end, setEnd] = useState(
      (clip.editable_duration_ms || clip.duration_ms) / 1000,
    ),
    [mode, setMode] = useState("keep"),
    [focus, setFocus] = useState("speaker"),
    [regions, setRegions] = useState({ primary: full, secondary: full }),
    [target, setTarget] = useState("primary"),
    [note, setNote] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    video = useRef(null),
    drag = useRef(null),
    previewing = useRef(false);
  const total = clip.editable_duration_ms || clip.duration_ms;
  useEffect(() => {
    if (clip.profile !== "vertical") return;
    const controller = new AbortController();
    api(
      "/clips/" + clip.filename + "/framing",
      "GET",
      undefined,
      controller.signal,
    )
      .then((plan) => {
        const s = plan.segments[0];
        setRegions({
          primary: s.region || full,
          secondary: s.secondary_region || full,
        });
        setNote(s.framing_note || "");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setNote(e.message);
      });
    return () => controller.abort();
  }, [clip.filename, clip.profile]);
  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const root = "/clips/" + clip.filename;
      let result,
        queued = true;
      if (mode !== "keep") {
        if (instruction.trim())
          throw new Error(
            "Сохраните кадрирование отдельно от задания по речи.",
          );
        result = await api(root + "/framing", "POST", {
          title,
          mode,
          focus,
          region: ["crop", "split"].includes(mode) ? regions.primary : null,
          secondary_region: mode === "split" ? regions.secondary : null,
        });
      } else if (instruction.trim())
        result = await api(root + "/refine", "POST", {
          title,
          instruction: instruction.trim(),
        });
      else {
        const a = Math.round(Number(start) * 1000),
          b = Math.round(Number(end) * 1000);
        if (
          !Number.isFinite(a) ||
          !Number.isFinite(b) ||
          a < 0 ||
          b > total ||
          b - a < 250
        )
          throw new Error("Выберите интервал от 0,25 с в пределах ролика.");
        if (a === 0 && b === total) {
          await api(root, "PATCH", { title });
          queued = false;
        } else
          result = await api(root + "/trim", "POST", {
            title,
            start_ms: a,
            end_ms: b,
          });
      }
      onSaved(queued ? result.id : null);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function point(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  }
  return (
    <Modal
      title="Редактировать нарезку"
      onClose={onClose}
      className="clip-edit-dialog"
    >
      <video
        ref={video}
        src={"/api/clips/" + clip.filename}
        controls
        playsInline
        preload="metadata"
        aria-label="Предпросмотр редактируемой нарезки"
        onTimeUpdate={() => {
          if (previewing.current && video.current.currentTime >= Number(end)) {
            video.current.pause();
            previewing.current = false;
          }
        }}
      />
      <form onSubmit={submit}>
        <label className="field">
          Название нарезки
          <input
            required
            maxLength="240"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label className="field">
          Задание для нейросети
          <textarea
            rows="3"
            maxLength="1500"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="Убери вступление, оставь объяснение и продли конец до завершения мысли"
          />
          <small>
            Результат сохранится новой копией. Исходная запись останется.
          </small>
        </label>
        <details className="clip-manual-edit">
          <summary>Точная обрезка вручную</summary>
          <div className="clip-time-fields">
            <label className="field">
              Начало, с
              <input
                type="number"
                min="0"
                step="0.001"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label className="field">
              Конец, с
              <input
                type="number"
                min="0.25"
                step="0.001"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
          <div className="clip-range-actions">
            <Button
              type="button"
              small
              onClick={() => setStart(video.current.currentTime.toFixed(3))}
            >
              Начало по курсору
            </Button>
            <Button
              type="button"
              small
              onClick={() => setEnd(video.current.currentTime.toFixed(3))}
            >
              Конец по курсору
            </Button>
            <Button
              type="button"
              small
              onClick={() => {
                video.current.currentTime = Number(start);
                previewing.current = true;
                video.current.play().catch((e) => setError(e.message));
              }}
            >
              Просмотреть интервал
            </Button>
          </div>
          <p>
            {duration((Number(end) - Number(start)) * 1000)} / {duration(total)}
          </p>
        </details>
        {clip.profile === "vertical" && (
          <details id="clip-framing">
            <summary>Кадрирование TikTok</summary>
            <label className="field">
              Композиция
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {[
                  ["keep", "Сохранить текущую"],
                  ["auto", "Автоматически найти области"],
                  ["crop", "Крупный план области"],
                  ["split", "Реакция сверху + контент снизу"],
                  ["fit", "Полный исходный кадр"],
                ].map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Что важно для автоматического монтажа
              <select value={focus} onChange={(e) => setFocus(e.target.value)}>
                <option value="speaker">Говорящий</option>
                <option value="screen">Событие / текст на экране</option>
                <option value="reaction">Контент и реакция</option>
              </select>
            </label>
            <p>{note}</p>
            <label className="field">
              Область для выделения
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              >
                <option value="primary">Главная / верхняя</option>
                <option value="secondary">Нижняя</option>
              </select>
            </label>
            <div
              className="source-framing"
              onPointerDown={(e) => {
                if (e.button !== 0) return;
                drag.current = { ...point(e), target };
                e.currentTarget.setPointerCapture(e.pointerId);
                e.preventDefault();
              }}
              onPointerMove={(e) => {
                if (!drag.current) return;
                const p = point(e),
                  d = drag.current;
                setRegions((old) => ({
                  ...old,
                  [d.target]: {
                    x: Math.min(p.x, d.x),
                    y: Math.min(p.y, d.y),
                    w: Math.abs(p.x - d.x),
                    h: Math.abs(p.y - d.y),
                  },
                }));
                if (mode === "keep") setMode("crop");
              }}
              onPointerUp={() => (drag.current = null)}
              onPointerCancel={() => (drag.current = null)}
            >
              <img
                src={"/api/clips/" + clip.filename + "/source-frame"}
                alt="Исходный кадр: выделите нужную область"
              />
              {Object.entries(regions).map(([name, r]) => (
                <div
                  key={name}
                  className={
                    "region-box " + (name === "secondary" ? "secondary" : "")
                  }
                  hidden={name === "secondary" && mode !== "split"}
                  style={{
                    left: r.x * 100 + "%",
                    top: r.y * 100 + "%",
                    width: r.w * 100 + "%",
                    height: r.h * 100 + "%",
                  }}
                />
              ))}
            </div>
            {Object.entries(regions).map(([name, r]) => (
              <fieldset key={name} className="region-fields">
                <legend>
                  {name === "primary" ? "Главная область" : "Нижняя область"}
                </legend>
                {[
                  ["x", "Слева"],
                  ["y", "Сверху"],
                  ["w", "Ширина"],
                  ["h", "Высота"],
                ].map(([k, l]) => (
                  <label key={k}>
                    {l}, %
                    <input
                      aria-label={`${name === "primary" ? "Главная" : "Нижняя"} область: ${l}, %`}
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={Number((r[k] * 100).toFixed(2))}
                      onChange={(e) =>
                        setRegions((old) => ({
                          ...old,
                          [name]: {
                            ...old[name],
                            [k]: Number(e.target.value) / 100,
                          },
                        }))
                      }
                    />
                  </label>
                ))}
              </fieldset>
            ))}
            <small>Проверьте автоматические области перед публикацией.</small>
          </details>
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
          <Button kind="primary" disabled={busy} type="submit">
            {busy ? "Сохранение…" : "Сохранить изменения"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

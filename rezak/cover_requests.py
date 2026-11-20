"""Write a local handoff for designing a cover from real footage."""
import json
from pathlib import Path


def write_cover_request(video: Path, plan, root: Path) -> Path:
    directory = video.parent / 'cover-requests'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (video.stem + '.md')
    source = root / 'sources' / (plan.source_id + '.mp4')
    context = json.dumps({'export': video.name, 'source': source.name, 'title': plan.title}, ensure_ascii=False)
    draft = f'''# Обложка для полноценной нарезки Rezak

Сделай кликабельную обложку к этому ролику по композиционным приёмам канала [Лига Кубизма](https://www.youtube.com/@LigaKubizma/videos).

Посмотри нарезку и найди её главный сюжет. Подтверди, кто ведёт стрим, и выбери выразительный кадр с этим человеком. Если в кадре гость или ведущий просматриваемого видео, используй его только как второй план. Укажи таймкоды выбранных кадров.

Собери коллаж из реальной вебки, реального кадра из обсуждаемого видео или игрового момента. Для реакции поставь крупное лицо рядом с объектом реакции. Для игры выдели событие из геймплея. Используй обрезку, маску, цветокоррекцию и типографику. Не генерируй лица, эмоции, игровой кадр и предметы, которых нет в ролике. Стрелки и плашки добавляй только если они помогают прочитать сюжет.

Напиши короткую конкретную фразу на основе эпизода. Пример композиции: небольшая белая плашка с контекстом и более крупная жёлтая фраза под ней. Проверь читаемость в 320 × 180 и не закрывай глаза текстом. Итоговый JPEG 1280 × 720, до 2 МБ. После проверки замени файл `.cover.jpg` рядом с локальным экспортом.

Файлы находятся в `data/exports` и `data/sources` проекта Rezak. Метаданные ниже описывают ролик.

```json
{context}
```
'''
    temporary = path.with_suffix('.tmp')
    temporary.write_text(draft, encoding='utf-8')
    temporary.replace(path)
    return path

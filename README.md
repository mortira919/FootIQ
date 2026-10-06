<p align="center">
  <img src="assets/mark.svg" width="88" alt="FootIQ">
</p>

<h1 align="center">FootIQ</h1>

<p align="center">
  Тактический тренажёр. Выбрал амплуа, решил сцену, получил рейтинг.
</p>

Стенд открывает поле, отправляет действие игрока на сервер и показывает ответ рядом. Исход сцены и рейтинг считает сервер.

## Запуск

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Стенд: [http://127.0.0.1:8000/stand](http://127.0.0.1:8000/stand). На `/` лежит сайт: лендинг, `/privacy`, `/terms`, `/delete`, `/l/<код>`.

На стенде вход по имени. То же имя возвращает того же игрока.

## Проверка

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests
```

## Состав

| Путь | Что там |
| --- | --- |
| `backend/app` | API, геометрия сцены, Glicko-2 |
| `backend/puzzles` | десять сцен, по одной на роль |
| `backend/puzzles_video` | видеоразбор |
| `backend/app/static` | стенд |
| `backend/tests` | тесты |

Роли в сценах: `gk`, `cb`, `rb/lb`, `dm`, `cm`, `am`, `lm/rm`, `lw/rw`, `st`, `ss`.

Поле в метрах: 68 по ширине, 105 по длине. Атака идёт к меньшему `y`.

## Render

| | |
| --- | --- |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT` |

На бесплатном плане сервис засыпает без запросов. Файл базы при новом запуске начинается заново.

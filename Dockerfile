# Этап 1: Сборщик
FROM python:3.11-slim as builder

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

# Копируем только файл с зависимостями
COPY requirements.txt .

# Устанавливаем зависимости в домашнюю директорию пользователя root
RUN pip install --no-cache-dir --user -r requirements.txt

# Этап 2: Финальный образ
FROM python:3.11-slim

WORKDIR /app

# Создаем пользователя без прав root для безопасности
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

# Копируем установленные зависимости из этапа сборки в домашнюю директорию пользователя app
COPY --from=builder /root/.local /home/app/.local

# Обновляем PATH, чтобы пользователь app мог найти установленные пакеты
ENV PATH="/home/app/.local/bin:$PATH"

# Копируем код приложения и документы
COPY --chown=app:app bot.py database.py document_processor.py ./
COPY --chown=app:app .env ./
RUN mkdir -p documents

# Команда для запуска бота
CMD ["python", "bot.py"]
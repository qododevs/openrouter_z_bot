# Этап 1: Сборщик
# Используем официальный образ Python для установки зависимостей
FROM python:3.11-slim as builder

WORKDIR /app

# Устанавливаем системные зависимости, необходимые для сборки некоторых Python-пакетов
RUN apt-get update && apt-get install -y build-essential git && rm -rf /var/lib/apt/lists/*

# Копируем только файл с зависимостями, чтобы кэшировать этот слой Docker
COPY requirements.txt .

# Устанавливаем зависимости в виртуальное окружение
RUN pip install --no-cache-dir --user -r requirements.txt

# Этап 2: Финальный образ
# Используем более легкий образ для запуска приложения
FROM python:3.11-slim

WORKDIR /app

# Копируем установленные зависимости из этапа сборки
COPY --from=builder /root/.local /root/.local

# Создаем пользователя без прав root для безопасности
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

# Обновляем PATH, чтобы использовать локальные пакеты
ENV PATH=/root/.local/bin:$PATH

# Копируем код приложения и документы
COPY --chown=app:app bot.py database.py document_processor.py ./
COPY --chown=app:app .env ./
RUN mkdir -p documents

# Команда для запуска бота
CMD ["python", "bot.py"]
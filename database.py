import psycopg2
from psycopg2.extras import RealDictCursor
from langchain.docstore.document import Document
import os
from dotenv import load_dotenv
import json
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

load_dotenv()


# Класс для локальных эмбеддингов
class LocalEmbeddings:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        print(f"Загрузка модели эмбеддингов: {model_name}...")
        self.model = SentenceTransformer(model_name)
        print("Модель эмбеддингов успешно загружена.")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


# Класс-обертка для совместимости с ChromaDB
class ChromaEmbeddingFunction:
    def __init__(self, local_embeddings):
        self._local_embeddings = local_embeddings

    def __call__(self, input: list[str]) -> list[list[float]]:
        return self._local_embeddings.embed_documents(input)


class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.embeddings = LocalEmbeddings()

        # === ИНИЦИАЛИЗАЦИЯ CHROMADB ===
        self.chroma_client = chromadb.PersistentClient(path="./chroma_db")
        self.embedding_function = ChromaEmbeddingFunction(self.embeddings)

        self.collection = self.chroma_client.get_or_create_collection(
            name="cosmetic_docs",
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"}
        )
        print("ChromaDB успешно инициализирована.")
        # === КОНЕЦ ИНИЦИАЛИЗАЦИИ CHROMADB ===

        self.init_postgres_db()

    def init_postgres_db(self):
        """Инициализация PostgreSQL для контекста и мета-информации о файлах"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()

            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS documents
                           (
                               id
                               SERIAL
                               PRIMARY
                               KEY,
                               filename
                               VARCHAR
                           (
                               255
                           ) NOT NULL,
                               file_hash VARCHAR
                           (
                               64
                           ) NOT NULL UNIQUE,
                               processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                               )
                           """)

            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS user_context
                           (
                               id
                               SERIAL
                               PRIMARY
                               KEY,
                               user_id
                               BIGINT
                               NOT
                               NULL,
                               context
                               JSONB,
                               updated_at
                               TIMESTAMP
                               DEFAULT
                               CURRENT_TIMESTAMP,
                               UNIQUE
                           (
                               user_id
                           )
                               )
                           """)

            conn.commit()
            cursor.close()
            conn.close()
            print("PostgreSQL для мета-данных успешно инициализирована")
        except Exception as e:
            print(f"Ошибка при инициализации PostgreSQL: {e}")

    def is_file_processed(self, file_hash):
        """Проверка, был ли файл уже обработан"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM documents WHERE file_hash = %s", (file_hash,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            return result is not None
        except Exception as e:
            print(f"Ошибка при проверке файла: {e}")
            return False

    def save_document(self, filename, file_hash):
        """Сохранение информации о документе в PostgreSQL"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO documents (filename, file_hash) VALUES (%s, %s) RETURNING id",
                (filename, file_hash)
            )
            doc_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            conn.close()
            return doc_id
        except Exception as e:
            print(f"Ошибка при сохранении документа: {e}")
            return None

    def add_to_vector_store(self, chunks):
        """Добавление чанков в ChromaDB"""
        try:
            if not chunks:
                return

            ids = [f"{chunk.metadata['source']}_{chunk.metadata['file_hash']}_{i}" for i, chunk in enumerate(chunks)]
            documents = [chunk.page_content for chunk in chunks]
            metadatas = [chunk.metadata for chunk in chunks]

            self.collection.add(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            print(f"Добавлено {len(chunks)} чанков в ChromaDB")
        except Exception as e:
            print(f"Ошибка при добавлении в ChromaDB: {e}")

    def search_similar(self, query, k=5):
        """Поиск похожих документов в ChromaDB"""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=k
            )

            docs = []
            if results['documents'] and results['documents'][0]:
                for i in range(len(results['documents'][0])):
                    docs.append(Document(
                        page_content=results['documents'][0][i],
                        metadata=results['metadatas'][0][i]
                    ))
            return docs
        except Exception as e:
            print(f"Ошибка при поиске в ChromaDB: {e}")
            return []

    def get_user_context(self, user_id):
        """Получение контекста пользователя из PostgreSQL"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT context FROM user_context WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result:
                return json.loads(result["context"])
            return []
        except Exception as e:
            print(f"Ошибка при получении контекста пользователя: {e}")
            return []

    def update_user_context(self, user_id, context):
        """Обновление контекста пользователя в PostgreSQL"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO user_context (user_id, context)
                VALUES (%s, %s) ON CONFLICT (user_id) 
                DO
                UPDATE SET context = %s, updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, json.dumps(context), json.dumps(context))
            )

            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Ошибка при обновлении контекста пользователя: {e}")

    def clear_user_context(self, user_id):
        """Очистка контекста пользователя в PostgreSQL"""
        try:
            conn = psycopg2.connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_context WHERE user_id = %s", (user_id,))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Ошибка при очистке контекста пользователя: {e}")
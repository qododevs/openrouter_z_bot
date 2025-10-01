import os
import hashlib
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.document_loaders import PyPDFLoader, TextLoader
from langchain.docstore.document import Document
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import threading


class DocumentProcessor:
    def __init__(self, documents_folder="documents", db_manager=None):
        self.documents_folder = documents_folder
        self.db_manager = db_manager
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

        if not os.path.exists(self.documents_folder):
            os.makedirs(self.documents_folder)
            print(f"Создана папка для документов: {self.documents_folder}")

        self.observer = Observer()
        self.event_handler = DocumentChangeHandler(self)
        self.observer.schedule(self.event_handler, self.documents_folder, recursive=False)
        self.observer.start()
        print(f"Наблюдатель за папкой {self.documents_folder} запущен")

    def process_all_documents(self):
        """Обработка всех документов в папке"""
        print("Начинаю обработку всех документов...")
        processed_count = 0

        for filename in os.listdir(self.documents_folder):
            file_path = os.path.join(self.documents_folder, filename)
            if os.path.isfile(file_path):
                if self.process_document(file_path):
                    processed_count += 1

        print(f"Обработано документов: {processed_count}")
        return processed_count

    def process_document(self, file_path):
        """Обработка одного документа"""
        try:
            filename = os.path.basename(file_path)
            file_hash = self.calculate_file_hash(file_path)

            if self.db_manager and self.db_manager.is_file_processed(file_hash):
                print(f"Файл {filename} уже был обработан")
                return False

            print(f"Обрабатываю файл: {filename}")

            if filename.lower().endswith('.pdf'):
                loader = PyPDFLoader(file_path)
                documents = loader.load()
            elif filename.lower().endswith('.txt'):
                loader = TextLoader(file_path)
                documents = loader.load()
            else:
                print(f"Неподдерживаемый формат файла: {filename}")
                return False

            chunks = self.text_splitter.split_documents(documents)

            for chunk in chunks:
                chunk.metadata.update({
                    "source": filename,
                    "file_hash": file_hash
                })

            if self.db_manager:
                doc_id = self.db_manager.save_document(filename, file_hash)
                if doc_id:
                    self.db_manager.add_to_vector_store(chunks)

            print(f"Файл {filename} успешно обработан")
            return True
        except Exception as e:
            print(f"Ошибка при обработке файла {file_path}: {e}")
            return False

    def calculate_file_hash(self, file_path):
        """Вычисление хеша файла для проверки изменений"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def stop(self):
        """Остановка наблюдателя"""
        self.observer.stop()
        self.observer.join()


class DocumentChangeHandler(FileSystemEventHandler):
    def __init__(self, processor):
        self.processor = processor
        self.debounce_time = 5
        self.pending_files = {}

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule_processing(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule_processing(event.src_path)

    def _schedule_processing(self, file_path):
        if file_path in self.pending_files:
            self.pending_files[file_path].cancel()

        timer = threading.Timer(self.debounce_time, self.process_file, args=[file_path])
        self.pending_files[file_path] = timer
        timer.start()

    def process_file(self, file_path):
        try:
            self.processor.process_document(file_path)
            if file_path in self.pending_files:
                del self.pending_files[file_path]
        except Exception as e:
            print(f"Ошибка при обработке файла {file_path}: {e}")
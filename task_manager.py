#!/usr/bin/env python3
"""
task_manager.py - Moduł zarządzania zadaniami w projekcie gRPC
==============================================================

Ten moduł obsługuje zarządzanie zadaniami zdefiniowanymi w pliku grpc-project.yaml.
Umożliwia śledzenie zadań manualnych i automatycznych, powiadamianie o zmianach
oraz integrację z zewnętrznymi systemami.
"""

import os
import json
import yaml
import sqlite3
import logging
import datetime
import subprocess
import time
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import threading
import schedule

# Konfiguracja logowania
logger = logging.getLogger("task_manager")

# Stałe statusów zadań
class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"

# Stałe priorytetów zadań
class TaskPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class TaskManager:
    """Klasa zarządzająca zadaniami projektu."""
    
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any]):
        """
        Inicjalizuje menedżera zadań.
        
        Args:
            config: Konfiguracja zadań z pliku grpc-project.yaml
            global_config: Globalna konfiguracja projektu
        """
        self.config = config
        self.global_config = global_config
        
        # Pobierz konfigurację menedżera zadań
        task_manager_config = global_config.get("task_manager", {})
        self.enabled = task_manager_config.get("enabled", True)
        self.storage_path = task_manager_config.get("storage", "./tasks.db")
        self.notify_assignees = task_manager_config.get("notify_assignees", True)
        self.auto_update_status = task_manager_config.get("auto_update_status", True)
        
        # Konfiguracja integracji zewnętrznych
        self.integrations = task_manager_config.get("integrations", {})
        
        # Inicjalizacja bazy danych SQLite
        self._init_database()
        
        # Inicjalizacja modułu komunikacji
        self.communication_config = global_config.get("communication", {})
        
        # Zaplanowane zadania
        self.scheduler_thread = None
        
        if not self.enabled:
            logger.info("Menedżer zadań jest wyłączony.")
            return
        
        # Synchronizuj zadania z pliku konfiguracyjnego
        self.sync_tasks_from_config()
        
        # Uruchom harmonogram zadań automatycznych
        if self.auto_update_status:
            self._start_scheduler()
    
    def _init_database(self):
        """Inicjalizuje bazę danych SQLite do przechowywania zadań."""
        self.conn = sqlite3.connect(self.storage_path)
        cursor = self.conn.cursor()
        
        # Tworzenie tabeli zadań
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            assignee TEXT,
            executor TEXT,
            due_date TEXT,
            status TEXT NOT NULL,
            priority TEXT NOT NULL,
            tags TEXT,
            prerequisites TEXT,
            type TEXT NOT NULL,
            schedule TEXT,
            trigger TEXT,
            script TEXT,
            parameters TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        ''')
        
        # Tworzenie tabeli historii zadań
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            changed_by TEXT,
            timestamp TEXT NOT NULL,
            comment TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )
        ''')
        
        self.conn.commit()
    
    def sync_tasks_from_config(self):
        """Synchronizuje zadania z pliku konfiguracyjnego."""
        if not self.enabled:
            return
        
        logger.info("Synchronizacja zadań z pliku konfiguracyjnego...")
        
        # Pobierz zadania manualne
        manual_tasks = self.config.get("manual", [])
        for task in manual_tasks:
            self.add_or_update_task(
                task_id=task.get("id"),
                title=task.get("title"),
                description=task.get("description"),
                assignee=task.get("assignee"),
                due_date=task.get("due_date"),
                status=task.get("status", "pending"),
                priority=task.get("priority", "medium"),
                tags=task.get("tags", []),
                prerequisites=task.get("prerequisites", []),
                task_type="manual"
            )
        
        # Pobierz zadania automatyczne
        automated_tasks = self.config.get("automated", [])
        for task in automated_tasks:
            self.add_or_update_task(
                task_id=task.get("id"),
                title=task.get("title"),
                description=task.get("description"),
                executor=task.get("executor"),
                status=task.get("status", "pending"),
                priority=task.get("priority", "medium"),
                tags=task.get("tags", []),
                task_type="automated",
                schedule=task.get("schedule"),
                trigger=task.get("trigger"),
                script=task.get("script"),
                parameters=task.get("parameters", {})
            )
        
        logger.info("Synchronizacja zadań zakończona.")
    
    def add_or_update_task(self, task_id: str, title: str, 
                          description: Optional[str] = None,
                          assignee: Optional[str] = None,
                          executor: Optional[str] = None,
                          due_date: Optional[str] = None,
                          status: str = "pending",
                          priority: str = "medium",
                          tags: List[str] = None,
                          prerequisites: List[str] = None,
                          task_type: str = "manual",
                          schedule: Optional[str] = None,
                          trigger: Optional[str] = None,
                          script: Optional[str] = None,
                          parameters: Dict[str, Any] = None) -> bool:
        """
        Dodaje lub aktualizuje zadanie w bazie danych.
        
        Args:
            task_id: Unikalny identyfikator zadania
            title: Tytuł zadania
            description: Opis zadania
            assignee: Osoba przypisana do zadania (dla manualnych)
            executor: System wykonujący zadanie (dla automatycznych)
            due_date: Termin wykonania zadania
            status: Status zadania
            priority: Priorytet zadania
            tags: Tagi zadania
            prerequisites: Lista ID zadań, które muszą być ukończone przed tym zadaniem
            task_type: Typ zadania ('manual' lub 'automated')
            schedule: Harmonogram wykonania zadania (format cron)
            trigger: Wyzwalacz zadania (on_deploy, on_commit, scheduled)
            script: Ścieżka do skryptu wykonującego zadanie
            parameters: Parametry zadania
            
        Returns:
            True jeśli operacja się powiodła, False w przeciwnym przypadku
        """
        try:
            cursor = self.conn.cursor()
            
            # Sprawdź, czy zadanie już istnieje
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            existing_task = cursor.fetchone()
            
            # Przygotuj dane zadania
            current_time = datetime.datetime.now().isoformat()
            
            # Serializuj listy i słowniki do JSONa
            tags_json = json.dumps(tags or [])
            prerequisites_json = json.dumps(prerequisites or [])
            parameters_json = json.dumps(parameters or {})
            
            if existing_task:
                # Pobierz aktualny status zadania
                old_status = existing_task[6]  # Indeks kolumny 'status'
                
                # Aktualizuj istniejące zadanie
                cursor.execute('''
                UPDATE tasks
                SET title = ?, description = ?, assignee = ?, executor = ?,
                    due_date = ?, status = ?, priority = ?, tags = ?,
                    prerequisites = ?, type = ?, schedule = ?, trigger = ?,
                    script = ?, parameters = ?, updated_at = ?
                WHERE id = ?
                ''', (
                    title, description, assignee, executor,
                    due_date, status, priority, tags_json,
                    prerequisites_json, task_type, schedule, trigger,
                    script, parameters_json, current_time, task_id
                ))
                
                # Jeśli status się zmienił, zapisz historię
                if old_status != status:
                    self._add_task_history(task_id, old_status, status, "system", "Status zaktualizowany podczas synchronizacji")
                    
                    # Powiadom o zmianie statusu
                    self._notify_status_change(task_id, title, old_status, status)
            else:
                # Dodaj nowe zadanie
                cursor.execute('''
                INSERT INTO tasks (
                    id, title, description, assignee, executor,
                    due_date, status, priority, tags,
                    prerequisites, type, schedule, trigger,
                    script, parameters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    task_id, title, description, assignee, executor,
                    due_date, status, priority, tags_json,
                    prerequisites_json, task_type, schedule, trigger,
                    script, parameters_json, current_time, current_time
                ))
                
                # Dodaj historię utworzenia
                self._add_task_history(task_id, None, status, "system", "Zadanie utworzone")
                
                # Powiadom o utworzeniu zadania
                self._notify_task_created(task_id, title, assignee)
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Błąd podczas dodawania/aktualizacji zadania {task_id}: {e}")
            self.conn.rollback()
            return False
    
    def update_task_status(self, task_id: str, new_status: str, 
                          changed_by: str = "system", comment: Optional[str] = None) -> bool:
        """
        Aktualizuje status zadania.
        
        Args:
            task_id: ID zadania
            new_status: Nowy status zadania
            changed_by: Osoba/system zmieniający status
            comment: Komentarz do zmiany statusu
            
        Returns:
            True jeśli aktualizacja się powiodła, False w przeciwnym przypadku
        """
        try:
            cursor = self.conn.cursor()
            
            # Pobierz aktualne dane zadania
            cursor.execute("SELECT status, title, assignee FROM tasks WHERE id = ?", (task_id,))
            result = cursor.fetchone()
            
            if not result:
                logger.warning(f"Nie znaleziono zadania o ID {task_id}")
                return False
            
            old_status, title, assignee = result
            
            # Jeśli status się nie zmienił, nie ma potrzeby aktualizacji
            if old_status == new_status:
                return True
            
            # Aktualizuj status i datę aktualizacji
            current_time = datetime.datetime.now().isoformat()
            cursor.execute('''
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE id = ?
            ''', (new_status, current_time, task_id))
            
            # Dodaj historię zmiany statusu
            self._add_task_history(task_id, old_status, new_status, changed_by, comment)
            
            # Powiadom o zmianie statusu
            self._notify_status_change(task_id, title, old_status, new_status)
            
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Błąd podczas aktualizacji statusu zadania {task_id}: {e}")
            self.conn.rollback()
            return False
    
    def _add_task_history(self, task_id: str, old_status: Optional[str], 
                        new_status: str, changed_by: str, comment: Optional[str]) -> bool:
        """
        Dodaje wpis do historii zadania.
        
        Args:
            task_id: ID zadania
            old_status: Stary status zadania
            new_status: Nowy status zadania
            changed_by: Osoba/system zmieniający status
            comment: Komentarz do zmiany statusu
            
        Returns:
            True jeśli operacja się powiodła, False w przeciwnym przypadku
        """
        try:
            cursor = self.conn.cursor()
            
            # Dodaj wpis do historii
            current_time = datetime.datetime.now().isoformat()
            cursor.execute('''
            INSERT INTO task_history (
                task_id, old_status, new_status, changed_by, timestamp, comment
            ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (task_id, old_status, new_status, changed_by, current_time, comment))
            
            return True
        except Exception as e:
            logger.error(f"Błąd podczas dodawania historii zadania {task_id}: {e}")
            return False
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Pobiera informacje o zadaniu.
        
        Args:
            task_id: ID zadania
            
        Returns:
            Słownik z danymi zadania lub None, jeśli nie znaleziono
        """
        try:
            cursor = self.conn.cursor()
            
            # Pobierz dane zadania
            cursor.execute('''
            SELECT id, title, description, assignee, executor,
                  due_date, status, priority, tags,
                  prerequisites, type, schedule, trigger,
                  script, parameters, created_at, updated_at
            FROM tasks
            WHERE id = ?
            ''', (task_id,))
            
            result = cursor.fetchone()
            
            if not result:
                return None
            
            # Pobierz historię zadania
            cursor.execute('''
            SELECT old_status, new_status, changed_by, timestamp, comment
            FROM task_history
            WHERE task_id = ?
            ORDER BY timestamp DESC
            ''', (task_id,))
            
            history = []
            for h_row in cursor.fetchall():
                history.append({
                    "old_status": h_row[0],
                    "new_status": h_row[1],
                    "changed_by": h_row[2],
                    "timestamp": h_row[3],
                    "comment": h_row[4]
                })
            
            # Zbuduj słownik z danymi zadania
            task = {
                "id": result[0],
                "title": result[1],
                "description": result[2],
                "assignee": result[3],
                "executor": result[4],
                "due_date": result[5],
                "status": result[6],
                "priority": result[7],
                "tags": json.loads(result[8]),
                "prerequisites": json.loads(result[9]),
                "type": result[10],
                "schedule": result[11],
                "trigger": result[12],
                "script": result[13],
                "parameters": json.loads(result[14]),
                "created_at": result[15],
                "updated_at": result[16],
                "history": history
            }
            
            return task
        except Exception as e:
            logger.error(f"Błąd podczas pobierania zadania {task_id}: {e}")
            return None
    
    def list_tasks(self, status: Optional[str] = None, 
                 task_type: Optional[str] = None,
                 assignee: Optional[str] = None,
                 priority: Optional[str] = None,
                 tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Pobiera listę zadań z opcjonalnym filtrowaniem.
        
        Args:
            status: Filtrowanie po statusie
            task_type: Filtrowanie po typie zadania
            assignee: Filtrowanie po osobie przypisanej
            priority: Filtrowanie po priorytecie
            tags: Filtrowanie po tagach
            
        Returns:
            Lista zadań spełniających kryteria
        """
        try:
            cursor = self.conn.cursor()
            
            # Buduj zapytanie SQL z filtrowaniem
            query = '''
            SELECT id, title, description, assignee, executor,
                  due_date, status, priority, tags,
                  prerequisites, type, schedule, trigger,
                  script, parameters, created_at, updated_at
            FROM tasks
            WHERE 1=1
            '''
            
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if task_type:
                query += " AND type = ?"
                params.append(task_type)
            
            if assignee:
                query += " AND assignee = ?"
                params.append(assignee)
            
            if priority:
                query += " AND priority = ?"
                params.append(priority)
            
            # Wykonaj zapytanie
            cursor.execute(query, params)
            
            tasks = []
            for row in cursor.fetchall():
                task = {
                    "id": row[0],
                    "title": row[1],
                    "description": row[2],
                    "assignee": row[3],
                    "executor": row[4],
                    "due_date": row[5],
                    "status": row[6],
                    "priority": row[7],
                    "tags": json.loads(row[8]),
                    "prerequisites": json.loads(row[9]),
                    "type": row[10],
                    "schedule": row[11],
                    "trigger": row[12],
                    "script": row[13],
                    "parameters": json.loads(row[14]),
                    "created_at": row[15],
                    "updated_at": row[16]
                }
                
                # Filtrowanie po tagach (jeśli podano)
                if tags:
                    if not set(tags).issubset(set(task["tags"])):
                        continue
                
                tasks.append(task)
            
            return tasks
        except Exception as e:
            logger.error(f"Błąd podczas pobierania listy zadań: {e}")
            return []
    
    def execute_automated_task(self, task_id: str) -> bool:
        """
        Wykonuje zadanie automatyczne.
        
        Args:
            task_id: ID zadania
            
        Returns:
            True jeśli wykonanie się powiodło, False w przeciwnym przypadku
        """
        try:
            # Pobierz dane zadania
            task = self.get_task(task_id)
            
            if not task:
                logger.warning(f"Nie znaleziono zadania o ID {task_id}")
                return False
            
            if task["type"] != "automated":
                logger.warning(f"Zadanie {task_id} nie jest zadaniem automatycznym")
                return False
            
            # Aktualizuj status na "in_progress"
            self.update_task_status(task_id, TaskStatus.IN_PROGRESS.value, "system", "Rozpoczęcie wykonywania zadania automatycznego")
            
            # Pobierz ścieżkę do skryptu i parametry
            script_path = task["script"]
            parameters = task["parameters"]
            
            if not script_path or not os.path.exists(script_path):
                logger.error(f"Nie znaleziono skryptu {script_path} dla zadania {task_id}")
                self.update_task_status(task_id, TaskStatus.FAILED.value, "system", f"Nie znaleziono skryptu {script_path}")
                return False
            
            # Przygotuj parametry dla skryptu
            params_str = ""
            if parameters:
                for key, value in parameters.items():
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value)
                    params_str += f" --{key}={value}"
            
            # Wykonaj skrypt
            logger.info(f"Wykonywanie skryptu {script_path} dla zadania {task_id}")
            
            # Wybierz odpowiedni interpreter na podstawie rozszerzenia pliku
            if script_path.endswith(".py"):
                cmd = f"python {script_path}{params_str}"
            elif script_path.endswith(".sh"):
                cmd = f"bash {script_path}{params_str}"
            elif script_path.endswith(".js"):
                cmd = f"node {script_path}{params_str}"
            else:
                cmd = f"{script_path}{params_str}"
            
            # Uruchom proces
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Pobierz wyniki
            stdout, stderr = process.communicate()
            
            # Sprawdź, czy wykonanie się powiodło
            if process.returncode == 0:
                logger.info(f"Zadanie {task_id} wykonane pomyślnie")
                self.update_task_status(task_id, TaskStatus.COMPLETED.value, "system", f"Zadanie wykonane pomyślnie: {stdout[:200]}")
                return True
            else:
                logger.error(f"Błąd podczas wykonywania zadania {task_id}: {stderr}")
                self.update_task_status(task_id, TaskStatus.FAILED.value, "system", f"Błąd: {stderr[:200]}")
                return False
        except Exception as e:
            logger.error(f"Błąd podczas wykonywania zadania {task_id}: {e}")
            self.update_task_status(task_id, TaskStatus.FAILED.value, "system", f"Wyjątek: {str(e)}")
            return False
    
    def _start_scheduler(self):
        """Uruchamia harmonogram zadań automatycznych."""
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            logger.warning("Harmonogram zadań już działa")
            return
        
        def run_scheduler():
            logger.info("Uruchomiono harmonogram zadań automatycznych")
            
            # Funkcja wykonująca zadania według harmonogramu
            def check_and_execute_scheduled_tasks():
                automated_tasks = self.list_tasks(task_type="automated")
                current_time = datetime.datetime.now()
                
                for task in automated_tasks:
                    # Wykonuj tylko zadania w stanie oczekiwania
                    if task["status"] != TaskStatus.PENDING.value:
                        continue
                    
                    # Sprawdź, czy zadanie ma ustawiony harmonogram
                    if task["schedule"]:
                        # Tutaj powinna być logika sprawdzająca, czy harmonogram (w formacie cron)
                        # pasuje do bieżącego czasu. Dla uproszczenia przykładu zakładamy, że tak.
                        self.execute_automated_task(task["id"])
            
            # Dodaj do harmonogramu sprawdzanie zadań co minutę
            schedule.every(1).minutes.do(check_and_execute_scheduled_tasks)
            
            # Pętla wykonująca harmonogram
            while True:
                try:
                    schedule.run_pending()
                    time.sleep(1)
                except Exception as e:
                    logger.error(f"Błąd w harmonogramie zadań: {e}")
                    time.sleep(60)  # Poczekaj minutę przed ponowną próbą
        
        # Uruchom wątek harmonogramu
        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()
    
    def _notify_task_created(self, task_id: str, title: str, assignee: Optional[str]):
        """
        Powiadamia o utworzeniu zadania.
        
        Args:
            task_id: ID zadania
            title: Tytuł zadania
            assignee: Osoba przypisana do zadania
        """
        if not self.notify_assignees:
            return
        
        # Przygotuj dane do powiadomienia
        notification_data = {
            "event": "task.created",
            "task_id": task_id,
            "title": title,
            "assignee": assignee,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Wyślij powiadomienia przez skonfigurowane webhooks
        self._send_webhook_notifications("task.created", notification_data)
    
    def _notify_status_change(self, task_id: str, title: str, old_status: str, new_status: str):
        """
        Powiadamia o zmianie statusu zadania.
        
        Args:
            task_id: ID zadania
            title: Tytuł zadania
            old_status: Stary status
            new_status: Nowy status
        """
        if not self.notify_assignees:
            return
        
        # Przygotuj dane do powiadomienia
        notification_data = {
            "event": "task.status_changed",
            "task_id": task_id,
            "title": title,
            "old_status": old_status,
            "new_status": new_status,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Wyślij powiadomienia przez skonfigurowane webhooks
        self._send_webhook_notifications("task.status_changed", notification_data)
    
    def _send_webhook_notifications(self, event_type: str, data: Dict[str, Any]):
        """
        Wysyła powiadomienia przez webhooks.
        
        Args:
            event_type: Typ zdarzenia
            data: Dane do wysłania
        """
        # Pobierz konfigurację webhooków
        webhooks = self.communication_config.get("webhooks", [])
        
        for webhook in webhooks:
            # Sprawdź, czy webhook jest skonfigurowany dla tego typu zdarzenia
            if event_type not in webhook.get("events", []):
                continue
            
            url = webhook.get("url")
            if not url:
                continue
            
            # Przygotuj headers
            headers = webhook.get("headers", {})
            
            # Zastąp zmienne środowiskowe w headerach
            for key, value in headers.items():
                if isinstance(value, str) and "${" in value:
                    # Zastąp zmienne środowiskowe w formie ${VAR_NAME}
                    for env_var in set(re.findall(r'\${([^}]+)}', value)):
                        env_value = os.environ.get(env_var, '')
                        headers[key] = value.replace(f"${{{env_var}}}", env_value)
            
            # Wyślij powiadomienie
            try:
                response = requests.post(url, json=data, headers=headers)
                if response.status_code >= 400:
                    logger.warning(f"Błąd podczas wysyłania powiadomienia do {url}: {response.status_code} {response.text}")
            except Exception as e:
                logger.error(f"Błąd podczas wysyłania powiadomienia do {url}: {e}")
    
    def close(self):
        """Zamyka połączenie z bazą danych."""
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()

# Funkcja pomocnicza do tworzenia menedżera zadań
def create_task_manager(config: Dict[str, Any], global_config: Dict[str, Any]) -> Optional[TaskManager]:
    """
    Tworzy obiekt menedżera zadań na podstawie konfiguracji.
    
    Args:
        config: Konfiguracja zadań z pliku grpc-project.yaml
        global_config: Globalna konfiguracja projektu
        
    Returns:
        Obiekt menedżera zadań lub None, jeśli nie skonfigurowano
    """
    # Sprawdź, czy menedżer zadań jest włączony
    if not global_config.get("task_manager", {}).get("enabled", True):
        return None
    
    try:
        return TaskManager(config, global_config)
    except Exception as e:
        logger.error(f"Błąd podczas inicjalizacji menedżera zadań: {e}")
        return None
            self.update_task_status(task_id,
#!/usr/bin/env python3
"""
gRPC Project CLI z integracją LLM i zarządzaniem zadaniami
==========================================================

To narzędzie umożliwia tworzenie i zarządzanie projektem gRPC na podstawie pliku konfiguracyjnego.
Obsługuje pobieranie plików z różnych źródeł, generowanie usług gRPC, zarządzanie zadaniami
i komunikację z zewnętrznymi systemami.

Użycie:
    python microfunc.py init [nazwa-projektu]
    python microfunc.py llm-generate [--force]
    python microfunc.py sync
    python microfunc.py build
    python microfunc.py up
    python microfunc.py down
    python microfunc.py status
    python microfunc.py tasks [lista|pokaż|aktualizuj|wykonaj]
    python microfunc.py communicate [webhook|api]
"""

import os
import sys
import argparse
import yaml
import json
import subprocess
import git
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

# Import modułów
try:
    from llm_integration import create_llm_integration
except ImportError:
    # Jeśli moduł nie jest dostępny, użyj zaślepki
    def create_llm_integration(config, global_config):
        return None

try:
    from task_manager import create_task_manager
except ImportError:
    # Jeśli moduł nie jest dostępny, użyj zaślepki
    def create_task_manager(config, global_config):
        return None

try:
    from communication_manager import create_communication_manager
except ImportError:
    # Jeśli moduł nie jest dostępny, użyj zaślepki
    def create_communication_manager(config, global_config):
        return None

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("microfunc")

class GrpcProject:
    """Klasa zarządzająca projektem gRPC z integracjami."""
    
    def __init__(self, config_file: str = "microfunc.yaml"):
        """
        Inicjalizuje projekt gRPC.
        
        Args:
            config_file: Ścieżka do pliku konfiguracyjnego
        """
        self.config_file = config_file
        self.config = None
        
        # Załaduj konfigurację, jeśli plik istnieje
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                self.config = yaml.safe_load(f)
                
            # Inicjalizuj integrację LLM (jeśli jest skonfigurowana)
            if 'sources' in self.config and 'llm' in self.config['sources']:
                self.llm_integration = create_llm_integration(
                    self.config['sources']['llm'],
                    self.config.get('global', {})
                )
            else:
                self.llm_integration = None
                
            # Inicjalizuj menedżera zadań (jeśli jest skonfigurowany)
            if 'tasks' in self.config:
                self.task_manager = create_task_manager(
                    self.config['tasks'],
                    self.config.get('global', {})
                )
            else:
                self.task_manager = None
                
            # Inicjalizuj menedżera komunikacji (jeśli jest skonfigurowany)
            if 'communication' in self.config:
                self.communication_manager = create_communication_manager(
                    self.config['communication'],
                    self.config.get('global', {})
                )
            else:
                self.communication_manager = None
        else:
            self.llm_integration = None
            self.task_manager = None
            self.communication_manager = None
    
    def init_project(self, project_name: str):
        """
        Inicjalizuje nowy projekt gRPC.
        
        Args:
            project_name: Nazwa projektu
        """
        logger.info(f"Inicjalizacja projektu: {project_name}")
        
        # Utwórz katalogi projektu
        os.makedirs(project_name, exist_ok=True)
        os.chdir(project_name)
        
        # Utwórz strukturę katalogów
        directories = [
            "config",
            "functions",
            "certs",
            "generated",
            "logs",
            ".registry",
            "llm_generated/functions",
            "llm_generated/config",
            "llm_generated/proto",
            ".llm_cache",
            "scripts"
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        
        # Utwórz przykładowy plik konfiguracyjny z integracją LLM i zadaniami
        example_config = {
            "version": "1.2",
            "sources": {
                "local": {
                    "config_files": {
                        "path": "./config",
                        "files": ["app_config.json", "logging.yaml"]
                    },
                    "functions": {
                        "path": "./functions",
                        "files": ["example_service.py"]
                    }
                },
                "git": {},
                "llm": {
                    "provider": "openai",
                    "model": "gpt-4",
                    "api_key_env": "OPENAI_API_KEY",
                    "generated_functions": {
                        "path": "./llm_generated/functions",
                        "prompts": {
                            "example_generated": {
                                "output_file": "example_generated.py",
                                "prompt": "Stwórz prostą funkcję o nazwie 'hello_generated', która przyjmuje parametr name i zwraca powitanie.",
                                "parameters": {
                                    "temperature": 0.2,
                                    "max_tokens": 500
                                }
                            }
                        }
                    }
                }
            },
            "certificates": {
                "main": {
                    "cert_file": "./certs/server.crt",
                    "key_file": "./certs/server.key"
                },
                "auto_generated": {
                    "domain": "api.example.com",
                    "email": "admin@example.com",
                    "provider": "self-signed",
                    "output_dir": "./certs/generated"
                }
            },
            "tasks": {
                "manual": [
                    {
                        "id": "setup-environment",
                        "title": "Konfiguracja środowiska",
                        "description": "Skonfiguruj środowisko deweloperskie i zależności.",
                        "assignee": "dev@example.com",
                        "due_date": "2025-03-15",
                        "status": "pending",
                        "priority": "high",
                        "tags": ["setup", "environment"]
                    }
                ],
                "automated": [
                    {
                        "id": "run-tests",
                        "title": "Uruchomienie testów",
                        "description": "Automatyczne uruchomienie testów po zbudowaniu usług.",
                        "executor": "ci-system",
                        "trigger": "on_deploy",
                        "status": "pending",
                        "priority": "medium",
                        "tags": ["testing"],
                        "script": "./scripts/run_tests.sh"
                    }
                ]
            },
            "communication": {
                "webhooks": [
                    {
                        "id": "slack-notifications",
                        "url": "https://hooks.slack.com/services/EXAMPLE",
                        "events": ["service.start", "service.stop", "error"],
                        "format": "json",
                        "headers": {
                            "Content-Type": "application/json"
                        }
                    }
                ],
                "apis": [
                    {
                        "id": "example-api",
                        "type": "rest",
                        "base_url": "https://api.example.com",
                        "auth_type": "api_key",
                        "auth_config": {
                            "api_key": "${EXAMPLE_API_KEY}",
                            "header_name": "X-API-Key"
                        },
                        "endpoints": [
                            {
                                "path": "/data",
                                "method": "GET",
                                "description": "Pobieranie danych"
                            }
                        ]
                    }
                ]
            },
            "services": {
                "example-service": {
                    "function": {
                        "source": "local.functions",
                        "name": "example_service.py"
                    },
                    "grpc": {
                        "port": 50051,
                        "service_name": "ExampleService",
                        "proto_package": "example",
                        "tls": {
                            "enabled": True,
                            "cert": "main"
                        }
                    },
                    "http": {
                        "enabled": True,
                        "port": 8080,
                        "tls": {
                            "enabled": True,
                            "cert": "main"
                        }
                    },
                    "environment": {
                        "DEBUG": "true"
                    },
                    "depends_on": []
                },
                "generated-service": {
                    "function": {
                        "source": "llm.generated_functions",
                        "name": "example_generated.py"
                    },
                    "grpc": {
                        "port": 50052,
                        "service_name": "GeneratedService",
                        "proto_package": "generated",
                        "tls": {
                            "enabled": True,
                            "cert": "main"
                        }
                    },
                    "http": {
                        "enabled": True,
                        "port": 8081,
                        "tls": {
                            "enabled": True,
                            "cert": "main"
                        }
                    },
                    "environment": {
                        "DEBUG": "true"
                    },
                    "depends_on": []
                }
            },
            "global": {
                "project_name": project_name,
                "output_dir": "./generated",
                "logging": {
                    "level": "INFO",
                    "path": "./logs"
                },
                "registry": {
                    "path": "./.registry"
                },
                "discovery": {
                    "enabled": True,
                    "port": 50050
                },
                "llm_integration": {
                    "cache_dir": "./.llm_cache",
                    "cache_ttl": 86400,
                    "refresh_on_build": True,
                    "fallback_mode": "use_cached"
                },
                "task_manager": {
                    "enabled": True,
                    "storage": "./tasks.db",
                    "notify_assignees": True
                }
            }
        }
        
        with open("microfunc.yaml", 'w') as f:
            yaml.dump(example_config, f, default_flow_style=False, sort_keys=False)
        
        # Utwórz przykładowy plik funkcji
        example_function = """#!/usr/bin/env python3
\"\"\"
Przykładowa funkcja usługi gRPC
\"\"\"

from typing import Dict, Any

def example_service(name: str = "World") -> Dict[str, Any]:
    \"\"\"
    Przykładowa funkcja usługi.
    
    Args:
        name: Nazwa do powitania
    
    Returns:
        Słownik z odpowiedzią
    \"\"\"
    return {
        "message": f"Hello, {name}!",
        "timestamp": "2025-03-06T12:34:56Z"
    }
"""
        
        with open("functions/example_service.py", 'w') as f:
            f.write(example_function)
        
        # Utwórz przykładowy skrypt testów
        example_test_script = """#!/bin/bash
# Przykładowy skrypt testów

echo "Uruchamianie testów dla usług gRPC..."
echo "Test 1: Sprawdzanie połączenia z usługami..."
echo "Wszystkie testy zakończone pomyślnie!"
exit 0
"""
        
        with open("scripts/run_tests.sh", 'w') as f:
            f.write(example_test_script)
        
        # Ustaw uprawnienia wykonywania dla skryptu
        os.chmod("scripts/run_tests.sh", 0o755)
        
        # Utwórz przykładowy plik konfiguracyjny
        example_app_config = {
            "name": project_name,
            "environment": "development",
            "settings": {
                "timeout": 30,
                "max_retries": 3
            }
        }
        
        with open("config/app_config.json", 'w') as f:
            json.dump(example_app_config, f, indent=2)
        
        # Utwórz przykładową konfigurację logowania
        example_logging_config = """
# Konfiguracja logowania
version: 1
formatters:
  standard:
    format: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: standard
    stream: ext://sys.stdout
  file:
    class: logging.FileHandler
    level: DEBUG
    formatter: standard
    filename: logs/app.log
loggers:
  '':
    level: INFO
    handlers: [console, file]
    propagate: no
"""
        
        with open("config/logging.yaml", 'w') as f:
            f.write(example_logging_config)
            
        # Utwórz pliki modułów integracyjnych
        self._create_integration_modules()
        
        logger.info(f"Projekt '{project_name}' został zainicjalizowany")
        logger.info(f"Przejdź do katalogu '{project_name}' i dostosuj plik microfunc.yaml")
        logger.info("Aby wygenerować pliki LLM, użyj komendy:")
        logger.info("  python microfunc.py llm-generate")
        logger.info("Aby zarządzać zadaniami, użyj komendy:")
        logger.info("  python microfunc.py tasks list")
    
    def _create_integration_modules(self):
        """
        Tworzy pliki modułów integracyjnych.
        """
        # Tworzy moduł integracji LLM (llm_integration.py)
        self._create_llm_module()
        
        # Tworzy moduł zarządzania zadaniami (task_manager.py)
        self._create_task_manager_module()
        
        # Tworzy moduł komunikacji (communication_manager.py)
        self._create_communication_manager_module()
    
    def _create_llm_module(self):
        """
        Tworzy plik modułu integracji z LLM.
        """
        # ... (Implementacja podobna do obecnej) ...
        pass
    
    def _create_task_manager_module(self):
        """
        Tworzy plik modułu zarządzania zadaniami.
        """
        # ... (Implementacja podobna do obecnej) ...
        pass
    
    def _create_communication_manager_module(self):
        """
        Tworzy plik modułu komunikacji.
        """
        # ... (Implementacja podobna do obecnej) ...
        pass
    
    def llm_generate(self, force_refresh: bool = False):
        """
        Generuje pliki za pomocą LLM.
        
        Args:
            force_refresh: Czy wymusić odświeżenie wszystkich plików, ignorując cache
        """
        # ... (Implementacja podobna do obecnej) ...
        pass
    
    def task_list(self, status: Optional[str] = None, task_type: Optional[str] = None):
        """
        Wyświetla listę zadań.
        
        Args:
            status: Filtrowanie po statusie
            task_type: Filtrowanie po typie zadania
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.task_manager:
            logger.error("Menedżer zadań nie jest skonfigurowany.")
            return
        
        tasks = self.task_manager.list_tasks(status=status, task_type=task_type)
        
        print("\nLista zadań:")
        print(f"{'ID':<20} {'TYTUŁ':<30} {'STATUS':<15} {'PRIORYTET':<10} {'PRZYPISANY':<20}")
        print("-" * 100)
        
        for task in tasks:
            assignee = task.get("assignee") or task.get("executor") or "-"
            print(f"{task['id']:<20} {task['title']:<30} {task['status']:<15} {task['priority']:<10} {assignee:<20}")
    
    def task_show(self, task_id: str):
        """
        Wyświetla szczegóły zadania.
        
        Args:
            task_id: ID zadania
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.task_manager:
            logger.error("Menedżer zadań nie jest skonfigurowany.")
            return
        
        task = self.task_manager.get_task(task_id)
        
        if not task:
            logger.error(f"Nie znaleziono zadania o ID {task_id}")
            return
        
        print(f"\nSzczegóły zadania {task_id}:")
        print(f"Tytuł: {task['title']}")
        print(f"Opis: {task['description']}")
        print(f"Status: {task['status']}")
        print(f"Priorytet: {task['priority']}")
        
        if task['type'] == 'manual':
            print(f"Przypisany do: {task.get('assignee', '-')}")
            print(f"Termin: {task.get('due_date', '-')}")
        else:
            print(f"Wykonawca: {task.get('executor', '-')}")
            print(f"Wyzwalacz: {task.get('trigger', '-')}")
            print(f"Skrypt: {task.get('script', '-')}")
        
        print(f"Tagi: {', '.join(task['tags'])}")
        
        if task['history']:
            print("\nHistoria zadania:")
            for entry in task['history']:
                old_status = entry.get('old_status', '-')
                new_status = entry.get('new_status', '-')
                timestamp = entry.get('timestamp', '-')
                changed_by = entry.get('changed_by', '-')
                
                print(f"[{timestamp}] {changed_by}: {old_status} -> {new_status}")
                if entry.get('comment'):
                    print(f"  Komentarz: {entry['comment']}")
    
    def task_update(self, task_id: str, status: str, comment: Optional[str] = None):
        """
        Aktualizuje status zadania.
        
        Args:
            task_id: ID zadania
            status: Nowy status zadania
            comment: Komentarz do zmiany statusu
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.task_manager:
            logger.error("Menedżer zadań nie jest skonfigurowany.")
            return
        
        # Sprawdź, czy status jest prawidłowy
        valid_statuses = ["pending", "in_progress", "completed", "blocked", "failed"]
        if status not in valid_statuses:
            logger.error(f"Nieprawidłowy status. Dozwolone wartości: {', '.join(valid_statuses)}")
            return
        
        if self.task_manager.update_task_status(task_id, status, "user", comment):
            logger.info(f"Status zadania {task_id} został zaktualizowany na {status}")
        else:
            logger.error(f"Nie udało się zaktualizować statusu zadania {task_id}")
    
    def task_execute(self, task_id: str):
        """
        Ręcznie uruchamia zadanie automatyczne.
        
        Args:
            task_id: ID zadania
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.task_manager:
            logger.error("Menedżer zadań nie jest skonfigurowany.")
            return
        
        task = self.task_manager.get_task(task_id)
        
        if not task:
            logger.error(f"Nie znaleziono zadania o ID {task_id}")
            return
        
        if task['type'] != 'automated':
            logger.error(f"Zadanie {task_id} nie jest zadaniem automatycznym")
            return
        
        logger.info(f"Uruchamianie zadania {task_id}...")
        
        if self.task_manager.execute_automated_task(task_id):
            logger.info(f"Zadanie {task_id} zostało wykonane pomyślnie")
        else:
            logger.error(f"Błąd podczas wykonywania zadania {task_id}")
    
    def send_webhook(self, event_type: str, data_file: Optional[str] = None):
        """
        Wysyła powiadomienie przez webhook.
        
        Args:
            event_type: Typ zdarzenia
            data_file: Opcjonalna ścieżka do pliku JSON z danymi
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.communication_manager:
            logger.error("Menedżer komunikacji nie jest skonfigurowany.")
            return
        
        # Przygotuj dane
        data = {}
        
        if data_file:
            try:
                with open(data_file, 'r') as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Błąd podczas wczytywania pliku {data_file}: {e}")
                return
        
        # Dodaj podstawowe informacje
        data["event"] = event_type
        data["timestamp"] = time.time()
        
        # Wyślij powiadomienie
        self.communication_manager.send_webhook_notification(event_type, data)
        logger.info(f"Wysłano powiadomienie typu {event_type}")
    
    def call_api(self, api_id: str, method_name: str, params_file: Optional[str] = None):
        """
        Wywołuje metodę API.
        
        Args:
            api_id: Identyfikator API
            method_name: Nazwa metody
            params_file: Opcjonalna ścieżka do pliku JSON z parametrami
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.communication_manager:
            logger.error("Menedżer komunikacji nie jest skonfigurowany.")
            return
        
        # Przygotuj parametry
        params = {}
        
        if params_file:
            try:
                with open(params_file, 'r') as f:
                    params = json.load(f)
            except Exception as e:
                logger.error(f"Błąd podczas wczytywania pliku {params_file}: {e}")
                return
        
        # Wywołaj API
        result = self.communication_manager.call_api(api_id, method_name, **params)
        
        if result is not None:
            print("\nWynik wywołania API:")
            print(json.dumps(result, indent=2))
        else:
            logger.error(f"Błąd podczas wywoływania API {api_id}.{method_name}")
    
    # Pozostałe metody (sync, build, itp.) są podobne do obecnych
    # ...
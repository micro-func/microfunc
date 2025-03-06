#!/usr/bin/env python3
"""
gRPC Project CLI z integracją LLM - Narzędzie do zarządzania projektem gRPC

To narzędzie umożliwia tworzenie i zarządzanie projektem gRPC na podstawie pliku konfiguracyjnego.
Obsługuje pobieranie plików z różnych źródeł (lokalnych, zdalnych i generowanych przez LLM),
generowanie usług gRPC oraz konfigurację TLS dla bezpiecznej komunikacji.

Użycie:
    python grpc-project-cli.py init [nazwa-projektu]
    python grpc-project-cli.py llm-generate [--force]
    python grpc-project-cli.py sync
    python grpc-project-cli.py build
    python grpc-project-cli.py up
    python grpc-project-cli.py down
    python grpc-project-cli.py status
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

# Import modułu integracji LLM
try:
    from llm_integration import create_llm_integration
except ImportError:
    # Jeśli moduł nie jest dostępny, użyj zaślepki
    def create_llm_integration(config, global_config):
        return None

# Konfiguracja logowania
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("grpc-project")

class GrpcProject:
    """Klasa zarządzająca projektem gRPC z integracją LLM."""
    
    def __init__(self, config_file: str = "grpc-project.yaml"):
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
        else:
            self.llm_integration = None
    
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
            ".llm_cache"
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        
        # Utwórz przykładowy plik konfiguracyjny z integracją LLM
        example_config = {
            "version": "1.1",
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
                }
            }
        }
        
        with open("grpc-project.yaml", 'w') as f:
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
            
        # Utwórz plik modułu integracji LLM
        self._create_llm_module()
        
        logger.info(f"Projekt '{project_name}' został zainicjalizowany")
        logger.info(f"Przejdź do katalogu '{project_name}' i dostosuj plik grpc-project.yaml")
        logger.info("Aby wygenerować pliki LLM, użyj komendy:")
        logger.info("  python grpc-project-cli.py llm-generate")
    
    def _create_llm_module(self):
        """
        Tworzy plik modułu integracji z LLM.
        """
        llm_module_path = "llm_integration.py"
        
        # Sprawdź, czy plik już istnieje
        if os.path.exists(llm_module_path):
            logger.info(f"Plik {llm_module_path} już istnieje, pomijanie.")
            return
        
        # Treść modułu integracji LLM
        llm_module_content = """#!/usr/bin/env python3
\"\"\"
llm_integration.py - Moduł integracji z modelami językowymi (LLM)
==================================================================

Ten moduł obsługuje interakcję z różnymi dostawcami LLM (OpenAI, Anthropic, itp.)
w celu generowania kodu i zasobów na potrzeby usług gRPC.
\"\"\"

import os
import json
import time
import hashlib
import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Union

# Konfiguracja logowania
logger = logging.getLogger("llm_integration")

class LLMProvider:
    \"\"\"Abstrakcyjna klasa bazowa dla dostawców LLM.\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        \"\"\"
        Inicjalizuje dostawcę LLM.
        
        Args:
            config: Konfiguracja dostawcy
        \"\"\"
        self.config = config
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        \"\"\"
        Generuje tekst na podstawie promptu.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania (temperature, max_tokens, itp.)
            
        Returns:
            Wygenerowany tekst
        \"\"\"
        raise NotImplementedError("Metoda generate() musi być zaimplementowana przez podklasy")

class OpenAIProvider(LLMProvider):
    \"\"\"Dostawca LLM wykorzystujący API OpenAI.\"\"\"
    
    def __init__(self, config: Dict[str, Any]):
        \"\"\"
        Inicjalizuje dostawcę OpenAI.
        
        Args:
            config: Konfiguracja dostawcy
        \"\"\"
        super().__init__(config)
        self.api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"))
        if not self.api_key:
            raise ValueError(f"Nie znaleziono klucza API OpenAI w zmiennej środowiskowej {config.get('api_key_env')}")
        
        self.model = config.get("model", "gpt-4")
        self.api_url = "https://api.openai.com/v1/chat/completions"
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        \"\"\"
        Generuje tekst za pomocą API OpenAI.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            
        Returns:
            Wygenerowany tekst
        \"\"\"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model,
            "messages": [{"role": "system", "content": "Jesteś asystentem AI specjalizującym się w generowaniu kodu i zasobów dla usług gRPC."},
                        {"role": "user", "content": prompt}],
            "temperature": parameters.get("temperature", 0.7),
            "max_tokens": parameters.get("max_tokens", 2000)
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"].strip()
            else:
                raise ValueError("Nieprawidłowa odpowiedź od API OpenAI")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd podczas komunikacji z API OpenAI: {e}")
            raise

# Pozostała część kodu integracji LLM...
# (Tutaj dodano by resztę klas LLMIntegration, AnthropicProvider, itp.)

class LLMIntegration:
    \"\"\"Klasa zarządzająca integracją z LLM.\"\"\"
    
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any]):
        \"\"\"
        Inicjalizuje integrację z LLM.
        
        Args:
            config: Konfiguracja LLM z pliku grpc-project.yaml
            global_config: Globalna konfiguracja projektu
        \"\"\"
        self.config = config
        self.global_config = global_config
        
        # Inicjalizacja dostawcy LLM
        provider_type = config.get("provider", "openai").lower()
        if provider_type == "openai":
            self.provider = OpenAIProvider(config)
        else:
            raise ValueError(f"Nieobsługiwany dostawca LLM: {provider_type}")
        
        # Konfiguracja cachowania
        llm_integration_config = global_config.get("llm_integration", {})
        self.cache_dir = Path(llm_integration_config.get("cache_dir", "./.llm_cache"))
        self.cache_ttl = llm_integration_config.get("cache_ttl", 86400)  # 24 godziny w sekundach
        self.refresh_on_build = llm_integration_config.get("refresh_on_build", True)
        self.fallback_mode = llm_integration_config.get("fallback_mode", "use_cached")
        
        # Utwórz katalog cache, jeśli nie istnieje
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_files(self, force_refresh: bool = False) -> Dict[str, str]:
        \"\"\"
        Generuje wszystkie pliki zdefiniowane w konfiguracji.
        
        Args:
            force_refresh: Czy wymusić odświeżenie wszystkich plików, ignorując cache
            
        Returns:
            Słownik z wygenerowanymi ścieżkami plików
        \"\"\"
        generated_files = {}
        
        # Generuj funkcje
        if "generated_functions" in self.config:
            functions_config = self.config["generated_functions"]
            output_path = Path(functions_config.get("path", "./llm_generated/functions"))
            output_path.mkdir(parents=True, exist_ok=True)
            
            for name, prompt_config in functions_config.get("prompts", {}).items():
                output_file = output_path / prompt_config.get("output_file")
                content = self._generate_or_get_cached(
                    prompt=prompt_config.get("prompt"),
                    parameters=prompt_config.get("parameters", {}),
                    cache_key=f"function_{name}",
                    force_refresh=force_refresh
                )
                
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(content)
                generated_files[f"function_{name}"] = str(output_file)
                logger.info(f"Wygenerowano funkcję {name} do pliku {output_file}")
        
        # Podobnie dla innych typów zasobów
        # ...
        
        return generated_files
    
    def _generate_or_get_cached(self, prompt: str, parameters: Dict[str, Any], 
                              cache_key: str, force_refresh: bool = False) -> str:
        \"\"\"
        Generuje tekst lub pobiera go z cache'u, jeśli istnieje i jest aktualny.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            cache_key: Klucz cache'u
            force_refresh: Czy wymusić odświeżenie, ignorując cache
            
        Returns:
            Wygenerowany tekst
        \"\"\"
        # Oblicz klucz hasha na podstawie promptu i parametrów
        prompt_hash = hashlib.md5((prompt + json.dumps(parameters, sort_keys=True)).encode()).hexdigest()
        cache_file = self.cache_dir / f"{cache_key}_{prompt_hash}.json"
        
        # Sprawdź, czy istnieje ważny cache
        if not force_refresh and cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                # Sprawdź, czy cache jest wciąż aktualny
                if cache_data.get("timestamp", 0) + self.cache_ttl > time.time():
                    logger.info(f"Pobrano zawartość z cache'u dla {cache_key}")
                    return cache_data["content"]
            except Exception as e:
                logger.warning(f"Błąd podczas odczytu cache'u: {e}")
        
        try:
            # Generuj nową zawartość
            content = self.provider.generate(prompt, parameters)
            
            # Zapisz do cache'u
            cache_data = {
                "timestamp": time.time(),
                "content": content,
                "prompt": prompt,
                "parameters": parameters
            }
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.info(f"Wygenerowano nową zawartość dla {cache_key} i zapisano do cache'u")
            return content
            
        except Exception as e:
            logger.error(f"Błąd podczas generowania zawartości: {e}")
            
            # W przypadku błędu, spróbuj użyć cache'u (nawet jeśli jest nieaktualny)
            if self.fallback_mode == "use_cached" and cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        cache_data = json.load(f)
                    
                    logger.warning(f"Używam nieaktualnego cache'u dla {cache_key} w trybie awaryjnym")
                    return cache_data["content"]
                except:
                    pass
            
            raise

# Funkcja pomocnicza do tworzenia integracji z LLM
def create_llm_integration(config: Dict[str, Any], global_config: Dict[str, Any]) -> Optional[LLMIntegration]:
    \"\"\"
    Tworzy obiekt integracji z LLM na podstawie konfiguracji.
    
    Args:
        config: Konfiguracja LLM z pliku grpc-project.yaml
        global_config: Globalna konfiguracja projektu
        
    Returns:
        Obiekt integracji z LLM lub None, jeśli nie skonfigurowano
    \"\"\"
    if not config or "provider" not in config:
        return None
    
    try:
        return LLMIntegration(config, global_config)
    except Exception as e:
        logger.error(f"Błąd podczas inicjalizacji integracji z LLM: {e}")
        return None
"""
        
        with open(llm_module_path, 'w') as f:
            f.write(llm_module_content)
        
        logger.info(f"Utworzono moduł integracji LLM: {llm_module_path}")
    
    def llm_generate(self, force_refresh: bool = False):
        """
        Generuje pliki za pomocą LLM.
        
        Args:
            force_refresh: Czy wymusić odświeżenie wszystkich plików, ignorując cache
        """
        if not self.config:
            logger.error("Nie znaleziono pliku konfiguracyjnego. Uruchom 'init' najpierw.")
            return
        
        if not self.llm_integration:
            logger.error("Integracja LLM nie jest skonfigurowana.")
            if 'sources' not in self.config or 'llm' not in self.config['sources']:
                logger.error("Brak sekcji '
#!/usr/bin/env python3
"""
communication_manager.py - Moduł zarządzania komunikacją w projekcie gRPC
========================================================================

Ten moduł obsługuje komunikację z zewnętrznymi systemami za pomocą webhooków i API
zdefiniowanych w pliku grpc-project.yaml.
"""

import os
import json
import yaml
import logging
import requests
import re
import grpc
import importlib
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import threading
import urllib.parse

# Konfiguracja logowania
logger = logging.getLogger("communication_manager")

class CommunicationManager:
    """Klasa zarządzająca komunikacją projektu."""
    
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any]):
        """
        Inicjalizuje menedżera komunikacji.
        
        Args:
            config: Konfiguracja komunikacji z pliku grpc-project.yaml
            global_config: Globalna konfiguracja projektu
        """
        self.config = config
        self.global_config = global_config
        
        # Inicjalizacja webhooków
        self.webhooks = self.config.get("webhooks", [])
        
        # Inicjalizacja API
        self.apis = {}
        self._init_apis()
    
    def _init_apis(self):
        """Inicjalizuje konfiguracje API."""
        api_configs = self.config.get("apis", [])
        
        for api_config in api_configs:
            api_id = api_config.get("id")
            if not api_id:
                logger.warning("Znaleziono konfigurację API bez ID, pomijanie.")
                continue
            
            api_type = api_config.get("type", "rest").lower()
            
            # Inicjalizuj odpowiedni typ API
            if api_type == "rest":
                self.apis[api_id] = RESTApiClient(api_config)
            elif api_type == "grpc":
                self.apis[api_id] = GRPCApiClient(api_config)
            else:
                logger.warning(f"Nieobsługiwany typ API: {api_type}, pomijanie.")
        
        logger.info(f"Zainicjalizowano {len(self.apis)} API: {', '.join(self.apis.keys())}")
    
    def send_webhook_notification(self, event_type: str, data: Dict[str, Any]):
        """
        Wysyła powiadomienie przez webhooks.
        
        Args:
            event_type: Typ zdarzenia
            data: Dane do wysłania
        """
        for webhook in self.webhooks:
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
                else:
                    logger.info(f"Powiadomienie typu {event_type} wysłane do {url}")
            except Exception as e:
                logger.error(f"Błąd podczas wysyłania powiadomienia do {url}: {e}")
    
    def notify_service_start(self, service_name: str, port: int):
        """
        Powiadamia o uruchomieniu usługi.
        
        Args:
            service_name: Nazwa usługi
            port: Port usługi
        """
        # Przygotuj dane do powiadomienia
        notification_data = {
            "event": "service.start",
            "service_name": service_name,
            "port": port,
            "timestamp": time.time()
        }
        
        # Wyślij powiadomienie
        self.send_webhook_notification("service.start", notification_data)
    
    def notify_service_stop(self, service_name: str):
        """
        Powiadamia o zatrzymaniu usługi.
        
        Args:
            service_name: Nazwa usługi
        """
        # Przygotuj dane do powiadomienia
        notification_data = {
            "event": "service.stop",
            "service_name": service_name,
            "timestamp": time.time()
        }
        
        # Wyślij powiadomienie
        self.send_webhook_notification("service.stop", notification_data)
    
    def notify_error(self, error_type: str, message: str, service_name: Optional[str] = None):
        """
        Powiadamia o błędzie.
        
        Args:
            error_type: Typ błędu
            message: Komunikat błędu
            service_name: Opcjonalna nazwa usługi, której dotyczy błąd
        """
        # Przygotuj dane do powiadomienia
        notification_data = {
            "event": "error",
            "error_type": error_type,
            "message": message,
            "timestamp": time.time()
        }
        
        if service_name:
            notification_data["service_name"] = service_name
        
        # Wyślij powiadomienie
        self.send_webhook_notification("error", notification_data)
    
    def get_api_client(self, api_id: str) -> Optional[Any]:
        """
        Pobiera klienta API.
        
        Args:
            api_id: Identyfikator API
            
        Returns:
            Klient API lub None, jeśli nie znaleziono
        """
        return self.apis.get(api_id)
    
    def call_api(self, api_id: str, method_name: str, **kwargs) -> Optional[Any]:
        """
        Wywołuje metodę API.
        
        Args:
            api_id: Identyfikator API
            method_name: Nazwa metody
            **kwargs: Parametry metody
            
        Returns:
            Wynik wywołania lub None w przypadku błędu
        """
        api_client = self.get_api_client(api_id)
        if not api_client:
            logger.error(f"Nie znaleziono API o ID {api_id}")
            return None
        
        try:
            return api_client.call(method_name, **kwargs)
        except Exception as e:
            logger.error(f"Błąd podczas wywoływania {method_name} w API {api_id}: {e}")
            return None

class RESTApiClient:
    """Klient API REST."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje klienta API REST.
        
        Args:
            config: Konfiguracja API
        """
        self.config = config
        self.base_url = config.get("base_url", "")
        
        # Skonfiguruj autentykację
        self.auth_type = config.get("auth_type", "").lower()
        self.auth_config = config.get("auth_config", {})
        self.access_token = None
        self.token_expiry = 0
        
        # Pobierz konfigurację endpointów
        self.endpoints = {}
        for endpoint in config.get("endpoints", []):
            path = endpoint.get("path", "")
            method = endpoint.get("method", "GET").upper()
            if path and method:
                self.endpoints[f"{method}:{path}"] = endpoint
    
    def _get_auth_header(self) -> Dict[str, str]:
        """
        Pobiera nagłówek uwierzytelniania.
        
        Returns:
            Słownik z nagłówkiem uwierzytelniania
        """
        # Brak uwierzytelniania
        if not self.auth_type:
            return {}
        
        # Basic Auth
        if self.auth_type == "basic":
            username = self._get_env_var(self.auth_config.get("username", ""))
            password = self._get_env_var(self.auth_config.get("password", ""))
            if username and password:
                import base64
                auth_str = f"{username}:{password}"
                auth_bytes = auth_str.encode("utf-8")
                auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
                return {"Authorization": f"Basic {auth_b64}"}
        
        # API Key
        elif self.auth_type == "api_key":
            api_key = self._get_env_var(self.auth_config.get("api_key", ""))
            header_name = self.auth_config.get("header_name", "X-API-Key")
            if api_key:
                return {header_name: api_key}
        
        # OAuth 2.0
        elif self.auth_type == "oauth2":
            # Sprawdź, czy token jest ważny
            current_time = time.time()
            if not self.access_token or current_time >= self.token_expiry:
                # Pobierz nowy token
                self._refresh_oauth_token()
            
            if self.access_token:
                return {"Authorization": f"Bearer {self.access_token}"}
        
        return {}
    
    def _refresh_oauth_token(self):
        """Odświeża token OAuth 2.0."""
        token_url = self.auth_config.get("token_url", "")
        client_id = self._get_env_var(self.auth_config.get("client_id", ""))
        client_secret = self._get_env_var(self.auth_config.get("client_secret", ""))
        
        if not token_url or not client_id or not client_secret:
            logger.error("Brak wymaganych parametrów do odświeżenia tokenu OAuth")
            return
        
        try:
            # Przygotuj dane żądania
            data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret
            }
            
            # Wyślij żądanie
            response = requests.post(token_url, data=data)
            if response.status_code == 200:
                # Przetwórz odpowiedź
                token_data = response.json()
                self.access_token = token_data.get("access_token")
                
                # Ustaw czas wygaśnięcia tokenu
                expires_in = token_data.get("expires_in", 3600)  # Domyślnie 1 godzina
                self.token_expiry = time.time() + expires_in - 60  # 60 sekund zapasu
                
                logger.info("Token OAuth 2.0 został odświeżony")
            else:
                logger.error(f"Błąd podczas odświeżania tokenu OAuth: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"Błąd podczas odświeżania tokenu OAuth: {e}")
    
    def _get_env_var(self, value: str) -> str:
        """
        Pobiera wartość zmiennej środowiskowej.
        
        Args:
            value: Wartość z możliwymi referencjami do zmiennych środowiskowych
            
        Returns:
            Rozwinięta wartość
        """
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value
    
    def call(self, method_name: str, **kwargs) -> Optional[Any]:
        """
        Wywołuje metodę API.
        
        Args:
            method_name: Nazwa metody
            **kwargs: Parametry metody
            
        Returns:
            Wynik wywołania lub None w przypadku błędu
        """
        # Znajdź endpoint
        endpoint = self.endpoints.get(method_name)
        if not endpoint:
            # Sprawdź, czy method_name to samo path, a method jest GET
            endpoint = self.endpoints.get(f"GET:{method_name}")
        
        if not endpoint:
            logger.error(f"Nie znaleziono endpointu {method_name}")
            return None
        
        path = endpoint.get("path", "")
        http_method = endpoint.get("method", "GET").upper()
        
        # Przygotuj URL
        url = self.base_url
        if not url.endswith("/") and not path.startswith("/"):
            url += "/"
        url += path
        
        # Zastąp parametry ścieżki
        for param_name, param_value in kwargs.items():
            if f"{{{param_name}}}" in url:
                url = url.replace(f"{{{param_name}}}", urllib.parse.quote(str(param_value)))
        
        # Przygotuj nagłówki
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        headers.update(self._get_auth_header())
        
        # Przygotuj parametry zapytania i ciało
        params = {}
        json_data = None
        
        if http_method in ["GET", "DELETE"]:
            # Dodaj parametry jako query string
            for param_name, param_value in kwargs.items():
                if f"{{{param_name}}}" not in path:
                    params[param_name] = param_value
        else:
            # Dodaj parametry jako JSON body
            json_data = {}
            for param_name, param_value in kwargs.items():
                if f"{{{param_name}}}" not in path:
                    json_data[param_name] = param_value
        
        # Wyślij żądanie
        try:
            if http_method == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif http_method == "POST":
                response = requests.post(url, headers=headers, json=json_data)
            elif http_method == "PUT":
                response = requests.put(url, headers=headers, json=json_data)
            elif http_method == "DELETE":
                response = requests.delete(url, headers=headers, params=params)
            elif http_method == "PATCH":
                response = requests.patch(url, headers=headers, json=json_data)
            else:
                logger.error(f"Nieobsługiwana metoda HTTP: {http_method}")
                return None
            
            # Sprawdź, czy żądanie było udane
            response.raise_for_status()
            
            # Próbuj przetworzyć odpowiedź jako JSON
            try:
                return response.json()
            except ValueError:
                # Jeśli odpowiedź nie jest JSON, zwróć tekst
                return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd podczas wywoływania API {url}: {e}")
            return None

class GRPCApiClient:
    """Klient API gRPC."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje klienta API gRPC.
        
        Args:
            config: Konfiguracja API
        """
        self.config = config
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 50051)
        self.use_tls = config.get("use_tls", False)
        self.proto_file = config.get("proto_file")
        self.service_name = config.get("service_name")
        
        self.stub = None
        self.methods = {}
        
        # Załaduj metody
        for method in config.get("methods", []):
            method_name = method.get("name")
            if method_name:
                self.methods[method_name] = method
        
        # Spróbuj załadować stub, jeśli podano plik proto i nazwę usługi
        if self.proto_file and self.service_name:
            self._load_stub()
    
    def _load_stub(self):
        """Ładuje stub gRPC."""
        # Sprawdź, czy plik proto istnieje
        if not os.path.exists(self.proto_file):
            logger.error(f"Nie znaleziono pliku proto: {self.proto_file}")
            return
        
        try:
            # To jest uproszczone podejście. W rzeczywistości należałoby użyć
            # protoc do wygenerowania kodu Python z pliku proto.
            # Tutaj zakładamy, że kod już został wygenerowany.
            
            # Zakładamy, że moduł generowany ma nazwę [nazwa_proto]_pb2
            proto_name = os.path.basename(self.proto_file).split('.')[0]
            pb2_module_name = f"{proto_name}_pb2"
            pb2_grpc_module_name = f"{proto_name}_pb2_grpc"
            
            # Spróbuj zaimportować moduły
            try:
                pb2 = importlib.import_module(pb2_module_name)
                pb2_grpc = importlib.import_module(pb2_grpc_module_name)
            except ImportError:
                # Spróbuj zaimportować z katalogu proto_gen
                sys.path.append("./proto_gen")
                pb2 = importlib.import_module(pb2_module_name)
                pb2_grpc = importlib.import_module(pb2_grpc_module_name)
            
            # Utwórz kanał gRPC
            if self.use_tls:
                # Użyj TLS
                creds = grpc.ssl_channel_credentials()
                channel = grpc.secure_channel(f"{self.host}:{self.port}", creds)
            else:
                # Użyj połączenia niezabezpieczonego
                channel = grpc.insecure_channel(f"{self.host}:{self.port}")
            
            # Utwórz stub
            stub_class = getattr(pb2_grpc, f"{self.service_name}Stub")
            self.stub = stub_class(channel)
            
            logger.info(f"Załadowano stub gRPC dla usługi {self.service_name}")
        except Exception as e:
            logger.error(f"Błąd podczas ładowania stuba gRPC: {e}")
    
    def call(self, method_name: str, **kwargs) -> Optional[Any]:
        """
        Wywołuje metodę API gRPC.
        
        Args:
            method_name: Nazwa metody
            **kwargs: Parametry metody
            
        Returns:
            Wynik wywołania lub None w przypadku błędu
        """
        if not self.stub:
            logger.error("Stub gRPC nie został załadowany")
            return None
        
        # Sprawdź, czy metoda jest zdefiniowana
        if method_name not in self.methods:
            logger.error(f"Nie znaleziono metody {method_name}")
            return None
        
        try:
            # Pobierz metodę z stuba
            grpc_method = getattr(self.stub, method_name)
            if not grpc_method:
                logger.error(f"Nie znaleziono metody {method_name} w stubie gRPC")
                return None
            
            # Przygotuj żądanie
            request_class_name = f"{method_name}Request"
            proto_name = os.path.basename(self.proto_file).split('.')[0]
            pb2_module_name = f"{proto_name}_pb2"
            pb2 = importlib.import_module(pb2_module_name)
            
            # Utwórz obiekt żądania
            request_class = getattr(pb2, request_class_name)
            request = request_class(**kwargs)
            
            # Wywołaj metodę
            response = grpc_method(request)
            
            # Zwróć odpowiedź jako słownik (jeśli możliwe)
            if hasattr(response, "__dict__"):
                return {k: v for k, v in response.__dict__.items() if not k.startswith('_')}
            
            return response
        except Exception as e:
            logger.error(f"Błąd podczas wywoływania metody gRPC {method_name}: {e}")
            return None

# Funkcja pomocnicza do tworzenia menedżera komunikacji
def create_communication_manager(config: Dict[str, Any], global_config: Dict[str, Any]) -> Optional[CommunicationManager]:
    """
    Tworzy obiekt menedżera komunikacji na podstawie konfiguracji.
    
    Args:
        config: Konfiguracja komunikacji z pliku grpc-project.yaml
        global_config: Globalna konfiguracja projektu
        
    Returns:
        Obiekt menedżera komunikacji lub None, jeśli nie skonfigurowano
    """
    if not config:
        return None
    
    try:
        return CommunicationManager(config, global_config)
    except Exception as e:
        logger.error(f"Błąd podczas inicjalizacji menedżera komunikacji: {e}")
        return None
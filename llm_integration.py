#!/usr/bin/env python3
"""
llm_integration.py - Moduł integracji z modelami językowymi (LLM)
==================================================================

Ten moduł obsługuje interakcję z różnymi dostawcami LLM (OpenAI, Anthropic, itp.)
w celu generowania kodu i zasobów na potrzeby usług gRPC.
"""

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
    """Abstrakcyjna klasa bazowa dla dostawców LLM."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje dostawcę LLM.
        
        Args:
            config: Konfiguracja dostawcy
        """
        self.config = config
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        """
        Generuje tekst na podstawie promptu.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania (temperature, max_tokens, itp.)
            
        Returns:
            Wygenerowany tekst
        """
        raise NotImplementedError("Metoda generate() musi być zaimplementowana przez podklasy")

class OpenAIProvider(LLMProvider):
    """Dostawca LLM wykorzystujący API OpenAI."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje dostawcę OpenAI.
        
        Args:
            config: Konfiguracja dostawcy
        """
        super().__init__(config)
        self.api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"))
        if not self.api_key:
            raise ValueError(f"Nie znaleziono klucza API OpenAI w zmiennej środowiskowej {config.get('api_key_env')}")
        
        self.model = config.get("model", "gpt-4")
        self.api_url = "https://api.openai.com/v1/chat/completions"
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        """
        Generuje tekst za pomocą API OpenAI.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            
        Returns:
            Wygenerowany tekst
        """
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

class AnthropicProvider(LLMProvider):
    """Dostawca LLM wykorzystujący API Anthropic (Claude)."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje dostawcę Anthropic.
        
        Args:
            config: Konfiguracja dostawcy
        """
        super().__init__(config)
        self.api_key = os.environ.get(config.get("api_key_env", "ANTHROPIC_API_KEY"))
        if not self.api_key:
            raise ValueError(f"Nie znaleziono klucza API Anthropic w zmiennej środowiskowej {config.get('api_key_env')}")
        
        self.model = config.get("model", "claude-3-opus-20240229")
        self.api_url = "https://api.anthropic.com/v1/messages"
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        """
        Generuje tekst za pomocą API Anthropic.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            
        Returns:
            Wygenerowany tekst
        """
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": parameters.get("max_tokens", 2000),
            "temperature": parameters.get("temperature", 0.7)
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            if "content" in result and len(result["content"]) > 0:
                return result["content"][0]["text"]
            else:
                raise ValueError("Nieprawidłowa odpowiedź od API Anthropic")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd podczas komunikacji z API Anthropic: {e}")
            raise

class CustomProvider(LLMProvider):
    """Dostawca LLM wykorzystujący niestandardowe API."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje niestandardowego dostawcę.
        
        Args:
            config: Konfiguracja dostawcy
        """
        super().__init__(config)
        self.api_key = os.environ.get(config.get("api_key_env", "CUSTOM_API_KEY"))
        if not self.api_key:
            raise ValueError(f"Nie znaleziono klucza API w zmiennej środowiskowej {config.get('api_key_env')}")
        
        self.api_url = config.get("api_url")
        if not self.api_url:
            raise ValueError("Nie określono adresu API w konfiguracji")
    
    def generate(self, prompt: str, parameters: Dict[str, Any]) -> str:
        """
        Generuje tekst za pomocą niestandardowego API.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            
        Returns:
            Wygenerowany tekst
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Dostosuj strukturę danych do specyfiki API
        data = {
            "prompt": prompt,
            "parameters": parameters
        }
        
        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            
            # Dostosuj przetwarzanie odpowiedzi do specyfiki API
            if "result" in result:
                return result["result"]
            else:
                raise ValueError("Nieprawidłowa odpowiedź od API")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Błąd podczas komunikacji z API: {e}")
            raise

class LLMIntegration:
    """Klasa zarządzająca integracją z LLM."""
    
    def __init__(self, config: Dict[str, Any], global_config: Dict[str, Any]):
        """
        Inicjalizuje integrację z LLM.
        
        Args:
            config: Konfiguracja LLM z pliku grpc-project.yaml
            global_config: Globalna konfiguracja projektu
        """
        self.config = config
        self.global_config = global_config
        
        # Inicjalizacja dostawcy LLM
        provider_type = config.get("provider", "openai").lower()
        if provider_type == "openai":
            self.provider = OpenAIProvider(config)
        elif provider_type == "anthropic":
            self.provider = AnthropicProvider(config)
        elif provider_type == "custom":
            self.provider = CustomProvider(config)
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
        """
        Generuje wszystkie pliki zdefiniowane w konfiguracji.
        
        Args:
            force_refresh: Czy wymusić odświeżenie wszystkich plików, ignorując cache
            
        Returns:
            Słownik z wygenerowanymi ścieżkami plików
        """
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
        
        # Generuj konfiguracje
        if "generated_configs" in self.config:
            configs_config = self.config["generated_configs"]
            output_path = Path(configs_config.get("path", "./llm_generated/config"))
            output_path.mkdir(parents=True, exist_ok=True)
            
            for name, prompt_config in configs_config.get("prompts", {}).items():
                output_file = output_path / prompt_config.get("output_file")
                content = self._generate_or_get_cached(
                    prompt=prompt_config.get("prompt"),
                    parameters=prompt_config.get("parameters", {}),
                    cache_key=f"config_{name}",
                    force_refresh=force_refresh
                )
                
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(content)
                generated_files[f"config_{name}"] = str(output_file)
                logger.info(f"Wygenerowano konfigurację {name} do pliku {output_file}")
        
        # Generuj pliki proto
        if "generated_protos" in self.config:
            protos_config = self.config["generated_protos"]
            output_path = Path(protos_config.get("path", "./llm_generated/proto"))
            output_path.mkdir(parents=True, exist_ok=True)
            
            for name, prompt_config in protos_config.get("prompts", {}).items():
                output_file = output_path / prompt_config.get("output_file")
                content = self._generate_or_get_cached(
                    prompt=prompt_config.get("prompt"),
                    parameters=prompt_config.get("parameters", {}),
                    cache_key=f"proto_{name}",
                    force_refresh=force_refresh
                )
                
                output_file.parent.mkdir(parents=True, exist_ok=True)
                output_file.write_text(content)
                generated_files[f"proto_{name}"] = str(output_file)
                logger.info(f"Wygenerowano plik proto {name} do pliku {output_file}")
        
        return generated_files
    
    def _generate_or_get_cached(self, prompt: str, parameters: Dict[str, Any], 
                              cache_key: str, force_refresh: bool = False) -> str:
        """
        Generuje tekst lub pobiera go z cache'u, jeśli istnieje i jest aktualny.
        
        Args:
            prompt: Tekst promptu
            parameters: Parametry generowania
            cache_key: Klucz cache'u
            force_refresh: Czy wymusić odświeżenie, ignorując cache
            
        Returns:
            Wygenerowany tekst
        """
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
                else:
                    logger.info(f"Cache dla {cache_key} jest nieaktualny, generowanie nowej zawartości")
            except (json.JSONDecodeError, KeyError) as e:
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
    """
    Tworzy obiekt integracji z LLM na podstawie konfiguracji.
    
    Args:
        config: Konfiguracja LLM z pliku grpc-project.yaml
        global_config: Globalna konfiguracja projektu
        
    Returns:
        Obiekt integracji z LLM lub None, jeśli nie skonfigurowano
    """
    if not config or "provider" not in config:
        return None
    
    try:
        return LLMIntegration(config, global_config)
    except Exception as e:
        logger.error(f"Błąd podczas inicjalizacji integracji z LLM: {e}")
        return None
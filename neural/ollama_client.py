#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ollama Client para NEXUS
Cliente para la API local de Ollama (http://localhost:11434)
"""

import json
import urllib.request
import urllib.error
import os


class OllamaClient:
    """Cliente para Ollama API local"""
    
    def __init__(self, base_url: str = None, model: str = None):
        """
        Inicializar cliente de Ollama
        
        Args:
            base_url: URL base de Ollama (default: http://localhost:11434)
            model: Modelo a usar (default: llama3.2:1b o OLLAMA_MODEL env var)
        """
        # Soportar tanto OLLAMA_HOST como OLLAMA_URL para compatibilidad
        self.base_url = (
            base_url or 
            os.environ.get('OLLAMA_HOST') or 
            os.environ.get('OLLAMA_URL', 'http://localhost:11434')
        )
        self.model = model or os.environ.get('OLLAMA_MODEL', 'llama3.2:1b')
        self.available = False
        self.check()
    
    def check(self):
        """Verificar si Ollama está disponible y corriendo"""
        try:
            # Primero verificar si el servidor está activo
            req = urllib.request.Request(
                f'{self.base_url}/api/tags',
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    data = json.loads(r.read())
                    models = [m['name'] for m in data.get('models', [])]
                    
                    # Verificar si el modelo está disponible
                    model_found = False
                    for m in models:
                        if self.model in m or m.startswith(self.model.split(':')[0]):
                            model_found = True
                            self.model = m  # Usar el nombre exacto
                            break
                    
                    if model_found:
                        self.available = True
                        print(f"✓ Ollama disponible — modelo: {self.model}", flush=True)
                    else:
                        print(f"⚠ Modelo '{self.model}' no encontrado en Ollama", flush=True)
                        print(f"  Modelos disponibles: {', '.join(models)}", flush=True)
                        if models:
                            # Usar el primer modelo disponible como fallback
                            self.model = models[0]
                            self.available = True
                            print(f"  Usando fallback: {self.model}", flush=True)
                else:
                    print(f"⚠ Ollama error: HTTP {r.status}", flush=True)
                    
        except urllib.error.URLError as e:
            print(f"⚠ Ollama no disponible: {e.reason}", flush=True)
            print("  ¿Está corriendo 'ollama serve'?", flush=True)
        except Exception as e:
            print(f"⚠ Error al conectar con Ollama: {e}", flush=True)
    
    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 600) -> str:
        """
        Enviar mensaje de chat a Ollama
        
        Args:
            messages: Lista de mensajes [{"role": "user/assistant/system", "content": "..."}, ...]
            temperature: Creatividad (0-2)
            max_tokens: Tokens máximos de respuesta
            
        Returns:
            Respuesta del modelo o None si hay error
        """
        if not self.available:
            return None
        
        # Ollama espera el formato de OpenAI
        payload = {
            'model': self.model,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens,  # Ollama usa num_predict
            }
        }
        
        try:
            req = urllib.request.Request(
                f'{self.base_url}/api/chat',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            
            # Extraer respuesta
            if 'message' in data and 'content' in data['message']:
                return data['message']['content'].strip()
            else:
                print(f"[Ollama] Respuesta inesperada: {data}", flush=True)
                return None
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"[Ollama] HTTP Error {e.code}: {error_body}", flush=True)
            return None
        except Exception as e:
            print(f"[Ollama] Error en chat: {e}", flush=True)
            return None
    
    def generate(self, prompt: str, temperature: float = 0.3, max_tokens: int = 400) -> str:
        """
        Generar texto simple usando el endpoint /api/generate
        
        Args:
            prompt: Texto de entrada
            temperature: Creatividad (0-2)
            max_tokens: Tokens máximos
            
        Returns:
            Respuesta generada o None
        """
        if not self.available:
            return None
        
        payload = {
            'model': self.model,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens,
            }
        }
        
        try:
            req = urllib.request.Request(
                f'{self.base_url}/api/generate',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
            
            # Extraer respuesta
            if 'response' in data:
                return data['response'].strip()
            else:
                print(f"[Ollama] Respuesta inesperada: {data}", flush=True)
                return None
                
        except Exception as e:
            print(f"[Ollama] Error en generate: {e}", flush=True)
            return None


if __name__ == '__main__':
    # Test del cliente
    print("=== Test de Ollama Client ===\n")
    
    client = OllamaClient()
    
    if client.available:
        print(f"✓ Ollama conectado con modelo: {client.model}\n")
        
        # Test 1: Generate simple
        print("Test 1: Generación simple")
        response = client.generate("Di 'Hola' en 3 idiomas diferentes")
        if response:
            print(f"Respuesta: {response}\n")
        else:
            print("Sin respuesta\n")
        
        # Test 2: Chat con contexto
        print("Test 2: Chat con contexto")
        messages = [
            {"role": "system", "content": "Eres un asistente conciso y amigable."},
            {"role": "user", "content": "¿Qué es una red neuronal? Responde en máximo 30 palabras."}
        ]
        response = client.chat(messages, temperature=0.5, max_tokens=100)
        if response:
            print(f"Respuesta: {response}\n")
        else:
            print("Sin respuesta\n")
        
        # Test 3: Conversación multi-turno
        print("Test 3: Conversación multi-turno")
        messages = [
            {"role": "user", "content": "Recuerda que mi color favorito es el azul."},
            {"role": "assistant", "content": "Entendido, tu color favorito es el azul."},
            {"role": "user", "content": "¿Cuál es mi color favorito?"}
        ]
        response = client.chat(messages)
        if response:
            print(f"Respuesta: {response}\n")
        else:
            print("Sin respuesta\n")
    else:
        print("❌ Ollama no está disponible")
        print("\nAsegúrate de:")
        print("1. Tener Ollama instalado (https://ollama.ai)")
        print("2. Ejecutar: ollama serve")
        print("3. Tener un modelo descargado: ollama pull llama3.2:1b")

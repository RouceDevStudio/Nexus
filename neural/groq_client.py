#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UnifiedLLMClient - Cliente unificado para Anthropic Claude, Groq y Ollama
Creado por: Jhonatan David Castro Galvis

Lógica de disponibilidad dinámica:
  - Los tres clientes (Claude + Groq + Ollama) se inicializan siempre
  - En cada llamada: intenta el preferido primero, luego los demás en orden
  - Si ninguno responde → retorna None → brain usa Smart Mode
  - Re-chequea disponibilidad cada N llamadas para auto-recuperarse
  - Smart Mode SOLO cuando ningún LLM responde en esa llamada

Jerarquía de proveedores (configurable con LLM_PREFER):
  1. Claude (Anthropic) — principal para CHAT + CODEGEN  [ANTHROPIC_API_KEY]
  2. Groq               — fallback rápido               [GROQ_API_KEY]
  3. Ollama             — fallback local sin internet    [OLLAMA_BASE_URL]
"""

import json
import urllib.request
import urllib.error
import os
import sys


# ──────────────────────────────────────────────────────────────────────────────
#  CLIENTE ANTHROPIC (Claude)
# ──────────────────────────────────────────────────────────────────────────────

class AnthropicClient:
    """
    Cliente para la API de Anthropic (Claude).
    Usa claude-sonnet-4-5 por defecto — el mejor modelo para CodeGen.
    Interfaz compatible con GroqClient y OllamaClient.
    """

    ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    # Modelos disponibles en orden de preferencia
    MODELS = [
        "claude-sonnet-4-5",           # Mejor calidad, ideal para CodeGen
        "claude-haiku-4-5-20251001",   # Más rápido, ideal para chat rápido
    ]

    def __init__(self):
        self.api_key     = os.environ.get('ANTHROPIC_API_KEY', '').strip()
        self.model       = os.environ.get('ANTHROPIC_MODEL', self.MODELS[0])
        self.available   = False
        self._fail_count = 0
        self._MAX_FAILS  = 3
        self.check()

    def check(self):
        """
        Verifica si Anthropic está disponible con un mini mensaje real.
        Usa max_tokens=5 para ser lo más ligero posible.
        """
        if not self.api_key:
            print("⚠️  ANTHROPIC_API_KEY no encontrada — obtén una en https://console.anthropic.com", flush=True)
            self.available = False
            return False
        try:
            payload = json.dumps({
                "model":      self.model,
                "max_tokens": 5,
                "messages":   [{"role": "user", "content": "hi"}]
            }).encode("utf-8")
            req = urllib.request.Request(
                self.ANTHROPIC_API_URL,
                data=payload,
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         self.api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                }
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    self.available   = True
                    self._fail_count = 0
                    print(f"✓ Anthropic/Claude disponible — modelo: {self.model}", flush=True)
                    return True
                else:
                    print(f"⚠️  Anthropic error: HTTP {r.status}", flush=True)
                    self.available = False
                    return False
        except urllib.error.HTTPError as e:
            body = ''
            try: body = e.read().decode('utf-8')[:200]
            except: pass
            print(f"⚠️  Anthropic no disponible: HTTP {e.code} — {body}", flush=True)
            self.available = False
            return False
        except Exception as e:
            print(f"⚠️  Anthropic no disponible: {e}", flush=True)
            self.available = False
            return False

    def _convert_messages(self, messages: list):
        """
        Convierte mensajes al formato Anthropic.
        Separa el system prompt de los mensajes user/assistant.
        Retorna (system_str, messages_list).
        """
        system_parts = []
        chat_msgs    = []

        for m in messages:
            role    = m.get("role", "user")
            content = m.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(block.get("text", ""))
            elif role in ("user", "assistant"):
                if isinstance(content, list):
                    # Multimodal (imagen + texto) — convertir image_url → bloque Anthropic
                    blocks = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            blocks.append({"type": "text", "text": block["text"]})
                        elif block.get("type") == "image_url":
                            url_info = block.get("image_url", {})
                            url_str  = url_info.get("url", "")
                            if url_str.startswith("data:"):
                                try:
                                    media_type, b64 = url_str.split(";base64,", 1)
                                    media_type = media_type.replace("data:", "")
                                    blocks.append({
                                        "type":   "image",
                                        "source": {
                                            "type":       "base64",
                                            "media_type": media_type,
                                            "data":       b64,
                                        }
                                    })
                                except Exception:
                                    blocks.append({"type": "text", "text": "[imagen]"})
                            else:
                                blocks.append({
                                    "type":   "image",
                                    "source": {"type": "url", "url": url_str}
                                })
                    chat_msgs.append({"role": role, "content": blocks})
                else:
                    chat_msgs.append({"role": role, "content": str(content)})

        # Anthropic exige que los mensajes alternen user/assistant
        # y que el primero sea "user". Fusionar turnos consecutivos del mismo rol.
        fixed     = []
        last_role = None
        for m in chat_msgs:
            r = m["role"]
            if r == last_role and fixed:
                prev = fixed[-1]
                if isinstance(prev["content"], str) and isinstance(m["content"], str):
                    prev["content"] += "\n" + m["content"]
                elif isinstance(prev["content"], list) and isinstance(m["content"], str):
                    prev["content"].append({"type": "text", "text": m["content"]})
                else:
                    fixed.append(m)
                    last_role = r
            else:
                fixed.append(m)
                last_role = r

        # Si empieza con assistant, insertar un user vacío
        if fixed and fixed[0]["role"] == "assistant":
            fixed.insert(0, {"role": "user", "content": "..."})

        system_str = "\n\n".join(system_parts) if system_parts else ""
        return system_str, fixed

    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 8192,
             model_override: str = None) -> str:
        """
        Envía mensajes a Claude.
        - model_override: modelo específico para esta llamada
        - Soporta mensajes multimodales (imagen + texto)
        """
        if not self.available:
            return None

        model_to_use = model_override or self.model

        # Temperatura más baja para CodeGen (más determinismo)
        if max_tokens >= 4096:
            temperature = min(temperature, 0.3)

        system_str, chat_msgs = self._convert_messages(messages)
        if not chat_msgs:
            return None

        payload = {
            "model":       model_to_use,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    chat_msgs,
        }
        if system_str:
            payload["system"] = system_str

        # Timeout más largo para CodeGen
        timeout = 300 if max_tokens > 4000 else 90

        try:
            req = urllib.request.Request(
                self.ANTHROPIC_API_URL,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         self.api_key,
                    "anthropic-version": self.ANTHROPIC_VERSION,
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data   = json.loads(r.read().decode("utf-8"))
                blocks = data.get("content", [])
                parts  = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                result = "\n".join(parts).strip()
                if result:
                    self._fail_count = 0
                    return result
                return None
        except urllib.error.HTTPError as e:
            body = ''
            try: body = e.read().decode('utf-8')[:300]
            except: pass
            print(f"[Anthropic] HTTP Error {e.code}: {body}", flush=True)
            if e.code == 429:
                print("[Anthropic] Rate limit — esperando...", flush=True)
                return None
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                print(f"[Anthropic] {self._MAX_FAILS} fallos consecutivos — marcando no disponible temporalmente", flush=True)
                self.available = False
            return None
        except Exception as e:
            print(f"[Anthropic] Error en chat: {e}", flush=True)
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                self.available = False
            return None

    def chat_codegen(self, messages: list, temperature: float = 0.2,
                     max_tokens: int = 16000) -> str:
        """
        Variante optimizada para generación de código.
        Temperatura baja = código más determinista y correcto.
        max_tokens alto = archivos completos sin cortes.
        """
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, temperature)


# ──────────────────────────────────────────────────────────────────────────────
#  CLIENTE GROQ (original intacto)
# ──────────────────────────────────────────────────────────────────────────────

class GroqClient:
    """Cliente para Groq Cloud API"""
    
    def __init__(self):
        self.api_key  = os.environ.get('GROQ_API_KEY', '')
        self.model    = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
        self.base_url = 'https://api.groq.com/openai/v1'
        self.available = False
        self._fail_count = 0        # fallos consecutivos en runtime
        self._MAX_FAILS  = 3        # tras 3 fallos seguidos, marca como no disponible
        self.check()
    
    def check(self):
        """
        Verifica si Groq está disponible haciendo un mini chat real.
        NO usa /v1/models porque ese endpoint da 403 en cuentas gratuitas.
        Usa /v1/chat/completions con max_tokens=1 para ser lo más ligero posible.
        """
        if not self.api_key:
            print("⚠️  GROQ_API_KEY no encontrada — obtén una gratis en https://console.groq.com", flush=True)
            self.available = False
            return False
        try:
            payload = json.dumps({
                'model':      self.model,
                'messages':   [{'role': 'user', 'content': 'hi'}],
                'max_tokens': 1
            }).encode('utf-8')
            req = urllib.request.Request(
                f'{self.base_url}/chat/completions',
                data=payload,
                headers={
                    'Authorization':  f'Bearer {self.api_key}',
                    'Content-Type':   'application/json',
                    'User-Agent':     'groq-python/0.11.0',
                    'X-Stainless-OS': 'Linux',
                    'Accept':         'application/json',
                }
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    self.available   = True
                    self._fail_count = 0
                    print(f"✓ Groq disponible — modelo: {self.model}", flush=True)
                    return True
                else:
                    print(f"⚠️  Groq error: HTTP {r.status}", flush=True)
                    self.available = False
                    return False
        except urllib.error.HTTPError as e:
            body = ''
            try: body = e.read().decode('utf-8')[:120]
            except: pass
            print(f"⚠️  Groq no disponible: HTTP {e.code} — {body}", flush=True)
            self.available = False
            return False
        except Exception as e:
            print(f"⚠️  Groq no disponible: {e}", flush=True)
            self.available = False
            return False
    
    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 600,
             model_override: str = None) -> str:
        """
        Envía mensajes al LLM.
        - model_override: usa un modelo diferente para esta llamada (ej. modelo de visión)
        - Soporta mensajes multimodales (content como lista con image_url para visión)
        """
        if not self.available:
            return None
        model_to_use = model_override or self.model
        # Groq tiene límite de 8000 tokens de salida
        max_tokens = min(max_tokens, 8000)
        payload = {
            'model':       model_to_use,
            'messages':    messages,
            'temperature': temperature,
            'max_tokens':  max_tokens
        }
        # Timeout mayor para generación de archivos grandes
        timeout = 300 if max_tokens > 4000 else 60
        try:
            req = urllib.request.Request(
                f'{self.base_url}/chat/completions',
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Authorization':  f'Bearer {self.api_key}',
                    'Content-Type':   'application/json',
                    'User-Agent':     'groq-python/0.11.0',
                    'X-Stainless-OS': 'Linux',
                    'Accept':         'application/json',
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode('utf-8'))
                self._fail_count = 0   # reset en éxito
                return data['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"[Groq] HTTP Error {e.code}: {error_body[:200]}", flush=True)
            # No contar rate limits (429) como fallos del modelo
            if e.code == 429:
                print(f"[Groq] Rate limit — esperando...", flush=True)
                return None
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                print(f"[Groq] {self._MAX_FAILS} fallos consecutivos — marcando no disponible temporalmente", flush=True)
                self.available = False
            return None
        except Exception as e:
            print(f"[Groq] Error en chat: {e}", flush=True)
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                self.available = False
            return None
    
    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, temperature)


# ──────────────────────────────────────────────────────────────────────────────
#  CLIENTE OLLAMA (original intacto)
# ──────────────────────────────────────────────────────────────────────────────

class OllamaClient:
    """
    Cliente para Ollama local.
    Sin límite artificial de tiempo — Ollama puede tardar lo que necesite.
    """
    
    def __init__(self):
        self.base_url  = os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
        self.model     = os.environ.get('OLLAMA_MODEL', 'llama3.2:1b')
        self.available = False
        self._fail_count = 0
        self._MAX_FAILS  = 3
        self.check()
    
    def check(self):
        """Verifica si Ollama está disponible. Se puede llamar en cualquier momento."""
        try:
            req = urllib.request.Request(self.base_url)
            with urllib.request.urlopen(req, timeout=3) as r:
                if r.status == 200:
                    self.available   = True
                    self._fail_count = 0
                    print(f"✓ Ollama disponible — modelo: {self.model}", flush=True)
                    return True
                else:
                    print(f"⚠️  Ollama error: HTTP {r.status}", flush=True)
                    self.available = False
                    return False
        except Exception as e:
            print(f"⚠️  Ollama no disponible: {e}", flush=True)
            self.available = False
            return False
    
    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 600,
             model_override: str = None) -> str:
        if not self.available:
            return None
        
        model_to_use = model_override or self.model
        prompt = "\n".join([f"{msg['role']}: {msg['content'] if isinstance(msg['content'], str) else str(msg['content'])}" for msg in messages])
        payload = {
            'model':   model_to_use,
            'prompt':  prompt,
            'stream':  False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens
            }
        }
        
        try:
            req = urllib.request.Request(
                f'{self.base_url}/api/generate',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            # Sin timeout — Ollama puede tardar lo que necesite
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read().decode('utf-8'))
                self._fail_count = 0
                return data.get('response', '')
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            print(f"[Ollama] HTTP Error {e.code}: {error_body[:200]}", flush=True, file=sys.stderr)
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                self.available = False
            return None
        except Exception as e:
            print(f"[Ollama] Error en chat: {e}", flush=True, file=sys.stderr)
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                self.available = False
            return None
    
    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        if not self.available:
            return None
        
        payload = {
            'model':   self.model,
            'prompt':  prompt,
            'stream':  False,
            'options': {'temperature': temperature}
        }
        
        try:
            req = urllib.request.Request(
                f'{self.base_url}/api/generate',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req) as r:
                data = json.loads(r.read().decode('utf-8'))
                self._fail_count = 0
                return data.get('response', '')
        except Exception as e:
            print(f"[Ollama] Error en generate: {e}", flush=True, file=sys.stderr)
            self._fail_count += 1
            if self._fail_count >= self._MAX_FAILS:
                self.available = False
            return None


# ──────────────────────────────────────────────────────────────────────────────
#  CLIENTE UNIFICADO
# ──────────────────────────────────────────────────────────────────────────────

class UnifiedLLMClient:
    """
    Cliente unificado con disponibilidad DINÁMICA.

    Los tres clientes se inicializan siempre.
    En cada llamada:
      1. Intenta el preferido (por defecto Claude, configurable con LLM_PREFER)
      2. Si falla o no está disponible → intenta los siguientes en orden
      3. Si ninguno responde → retorna None → brain activa Smart Mode

    Orden de preferencia por defecto:
      claude → groq → ollama

    Configurable con LLM_PREFER=groq o LLM_PREFER=ollama

    Auto-recuperación: cada RECHECK_EVERY llamadas vuelve a chequear disponibilidad.

    Variables de entorno:
      ANTHROPIC_API_KEY  → habilita Claude (console.anthropic.com)
      GROQ_API_KEY       → habilita Groq   (console.groq.com — gratis)
      OLLAMA_BASE_URL    → habilita Ollama local (default: http://127.0.0.1:11434)
      LLM_PREFER         → claude | groq | ollama  (default: claude)
    """
    
    RECHECK_EVERY = 20   # re-chequear disponibilidad cada 20 llamadas
    
    def __init__(self):
        self.anthropic   = None
        self.groq        = None
        self.ollama      = None
        self._call_count = 0

        # Inicializar los TRES siempre
        try:
            self.anthropic = AnthropicClient()
        except Exception as e:
            print(f"⚠️  No se pudo instanciar AnthropicClient: {e}", flush=True)

        try:
            self.groq = GroqClient()
        except Exception as e:
            print(f"⚠️  No se pudo instanciar GroqClient: {e}", flush=True)

        try:
            self.ollama = OllamaClient()
        except Exception as e:
            print(f"⚠️  No se pudo instanciar OllamaClient: {e}", flush=True)

        # Orden de preferencia (configurable)
        prefer = os.environ.get('LLM_PREFER', 'claude').lower()
        if prefer == 'groq':
            self._order = [self.groq, self.anthropic, self.ollama]
            self._names = ['Groq', 'Claude', 'Ollama']
        elif prefer == 'ollama':
            self._order = [self.ollama, self.anthropic, self.groq]
            self._names = ['Ollama', 'Claude', 'Groq']
        else:
            # Por defecto: Claude primero
            self._order = [self.anthropic, self.groq, self.ollama]
            self._names = ['Claude', 'Groq', 'Ollama']

        self._log_status()
    
    def _log_status(self):
        claude_ok = self.anthropic and self.anthropic.available
        groq_ok   = self.groq      and self.groq.available
        ollama_ok = self.ollama    and self.ollama.available

        activos = []
        if claude_ok: activos.append(f"Claude/{self.anthropic.model}")
        if groq_ok:   activos.append(f"Groq/{self.groq.model}")
        if ollama_ok: activos.append(f"Ollama/{self.ollama.model}")

        if activos:
            print(f"✓ LLM activo: {' + '.join(activos)} (preferido: {self._names[0]})", flush=True)
        else:
            print("⚠️  Sin LLM disponible — NEXUS funcionará en Smart Mode", flush=True)
    
    @property
    def available(self) -> bool:
        """True si AL MENOS UNO está disponible."""
        return (
            bool(self.anthropic and self.anthropic.available) or
            bool(self.groq      and self.groq.available)      or
            bool(self.ollama    and self.ollama.available)
        )
    
    @property
    def model(self) -> str:
        """Nombre del modelo activo (el preferido que esté disponible)."""
        for client, name in zip(self._order, self._names):
            if client and client.available:
                m = getattr(client, 'model', '?')
                return f"{name}/{m}"
        return "sin LLM (Smart Mode)"

    def _maybe_recheck(self):
        """Cada RECHECK_EVERY llamadas, vuelve a verificar disponibilidad."""
        self._call_count += 1
        if self._call_count % self.RECHECK_EVERY == 0:
            changed = False
            for client in [self.anthropic, self.groq, self.ollama]:
                if client:
                    was = client.available
                    client.check()
                    if client.available != was:
                        changed = True
            if changed:
                print("[LLM] Estado de disponibilidad cambió:", flush=True)
                self._log_status()

    def _try_in_order(self, method: str, *args, **kwargs) -> str:
        """
        Llama al método (chat/generate/chat_codegen) en el orden de preferencia.
        Si el primero falla o no está disponible, prueba el siguiente.
        """
        self._maybe_recheck()

        for client, name in zip(self._order, self._names):
            if not client or not client.available:
                continue
            # chat_codegen solo existe en AnthropicClient
            # Para Groq/Ollama usar chat normal con los mismos args
            actual_method = method
            if method == 'chat_codegen' and not hasattr(client, 'chat_codegen'):
                actual_method = 'chat'
            try:
                result = getattr(client, actual_method)(*args, **kwargs)
                if result is not None:
                    return result
                print(f"[LLM] {name} retornó None → probando siguiente...", flush=True)
            except TypeError:
                # El cliente no soporta algún kwarg (ej. model_override en Ollama) — intentar sin él
                try:
                    filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'model_override'}
                    result = getattr(client, actual_method)(*args, **filtered_kwargs)
                    if result is not None:
                        return result
                except Exception as e2:
                    print(f"[LLM] {name} error (retry sin kwargs extra): {e2}", flush=True)
            except Exception as e:
                print(f"[LLM] {name} excepción inesperada: {e} → probando siguiente...", flush=True)

        return None

    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 8192,
             model_override: str = None) -> str:
        return self._try_in_order('chat', messages, temperature, max_tokens, model_override=model_override)

    def chat_codegen(self, messages: list, temperature: float = 0.2,
                     max_tokens: int = 16000) -> str:
        """
        Variante optimizada para CodeGen.
        Prioriza Claude Sonnet — si no está disponible cae a Groq/Ollama con chat normal.
        Temperatura baja = código correcto y determinista.
        max_tokens alto = archivos completos sin cortes.
        """
        return self._try_in_order('chat_codegen', messages, temperature, max_tokens)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        return self._try_in_order('generate', prompt, temperature)


# ──────────────────────────────────────────────────────────────────────────────
#  TEST
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=== Test UnifiedLLMClient (Claude + Groq + Ollama) ===")
    client = UnifiedLLMClient()
    print(f"\n✓ Disponible: {client.available}")
    print(f"✓ Modelo activo: {client.model}\n")

    if client.available:
        # Test chat general
        response = client.generate("Di 'Hola' en 5 idiomas diferentes")
        print(f"Generate test:\n{response}\n")

        # Test chat con historial
        messages = [
            {"role": "system",  "content": "Eres un asistente conciso."},
            {"role": "user",    "content": "¿Qué es una red neuronal en 20 palabras?"}
        ]
        response = client.chat(messages)
        print(f"Chat test:\n{response}\n")

        # Test CodeGen
        codegen_msgs = [
            {"role": "system", "content": "Eres un experto en Python. Responde SOLO con código, sin explicaciones ni markdown."},
            {"role": "user",   "content": "Escribe una función Python que calcule el factorial de n de forma recursiva."}
        ]
        response = client.chat_codegen(codegen_msgs, max_tokens=300)
        print(f"CodeGen test:\n{response}\n")
    else:
        print("❌ No hay LLM disponible — Smart Mode activo")
        print("Configura ANTHROPIC_API_KEY, GROQ_API_KEY o levanta Ollama")

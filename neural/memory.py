#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS - Sistema de Memoria v3.3 (IMPROVED)
Memoria episódica, semántica y de trabajo con mejor persistencia
"""

import json
import time
import numpy as np
import pickle
import os
from pathlib import Path
from collections import deque
from typing import List, Dict, Optional, Tuple
import sys


# ─────────────────────────────────────────────
#  MEMORIA DE TRABAJO (RAM del agente)
# ─────────────────────────────────────────────

class WorkingMemory:
    """
    Contexto actual de la conversación.
    Almacena los últimos N turnos con sus embeddings.
    """

    def __init__(self, max_turns: int = 24):
        self.max_turns = max_turns
        self.turns: deque = deque(maxlen=max_turns)
        self.topic_stack: List[str] = []
        self.entities: Dict[str, str] = {}

    def add(self, role: str, text: str, embedding: Optional[np.ndarray] = None):
        self.turns.append({
            'role': role,
            'text': text,
            'embedding': embedding,
            'ts': time.time()
        })

    def context_text(self, n_last: int = 6) -> str:
        recent = list(self.turns)[-n_last:]
        return "\n".join(f"[{t['role']}] {t['text']}" for t in recent)

    def context_embeddings(self) -> List[np.ndarray]:
        return [t['embedding'] for t in self.turns if t['embedding'] is not None]

    def clear(self):
        self.turns.clear()
        self.topic_stack.clear()
        self.entities.clear()

    def push_topic(self, topic: str):
        """Actualiza el tema actual"""
        if not self.topic_stack or self.topic_stack[-1] != topic:
            self.topic_stack.append(topic)
        if len(self.topic_stack) > 5:
            self.topic_stack.pop(0)

    def current_topic(self) -> Optional[str]:
        return self.topic_stack[-1] if self.topic_stack else None

    def turn_count(self) -> int:
        return len(self.turns)


# ─────────────────────────────────────────────
#  MEMORIA EPISÓDICA (MEJORADA)
# ─────────────────────────────────────────────

class EpisodicMemory:
    """
    Almacena episodios de búsqueda con mejor persistencia.
    MEJORADO: Ya no requiere embeddings para guardar - se calculan al buscar.
    """

    def __init__(self, path: str = 'data/episodic.pkl', max_episodes: int = 50000):
        self.path = path
        self.max_episodes = max_episodes
        self.episodes: List[Dict] = []
        self._load()

    def add(self, query: str, results: List[Dict], clicked_url: Optional[str] = None, reward: float = 0.5):
        """
        Guarda episodio SIN VALIDACIÓN RESTRICTIVA.
        MEJORADO: Guarda incluso sin resultados para tracking.
        """
        episode = {
            'query': query,
            'results': results[:5] if results else [],
            'clicked': clicked_url,
            'reward': reward,
            'ts': time.time()
        }
        
        self.episodes.append(episode)
        
        # Trim por tamaño
        if len(self.episodes) > self.max_episodes:
            self.episodes = self.episodes[-self.max_episodes:]
        
        print(f"[EpisodicMemory] Episodio añadido: '{query[:50]}' ({len(results)} resultados)", file=sys.stderr, flush=True)

    def store(self, query: str, query_emb: np.ndarray,
              top_results: List[Dict], clicked_url: Optional[str],
              reward: float):
        """
        Almacena con embedding validado (para compatibilidad)
        """
        # Validar embedding
        if query_emb is None or not isinstance(query_emb, np.ndarray):
            # Fallback: guardar sin embedding
            self.add(query, top_results, clicked_url, reward)
            return
        
        expected_dim = 128
        if query_emb.shape != (expected_dim,):
            self.add(query, top_results, clicked_url, reward)
            return
        
        if np.all(query_emb == 0) or np.any(np.isnan(query_emb)):
            self.add(query, top_results, clicked_url, reward)
            return
        
        episode = {
            'query': query,
            'emb': query_emb,
            'results': top_results[:5],
            'clicked': clicked_url,
            'reward': reward,
            'ts': time.time()
        }
        self.episodes.append(episode)

        # Trim
        if len(self.episodes) > self.max_episodes:
            self.episodes = self.episodes[-self.max_episodes:]

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Búsqueda por similitud de palabras clave (NO requiere embeddings)
        """
        if not self.episodes:
            return []
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        scored = []
        for ep in self.episodes:
            ep_query_lower = ep['query'].lower()
            ep_words = set(ep_query_lower.split())
            
            # Jaccard similarity
            intersection = len(query_words & ep_words)
            union = len(query_words | ep_words)
            similarity = intersection / union if union > 0 else 0
            
            if similarity > 0.1:  # Umbral más bajo para capturar más episodios
                ep_copy = dict(ep)
                # Remover embedding si existe
                if 'emb' in ep_copy:
                    del ep_copy['emb']
                ep_copy['similarity'] = similarity
                scored.append(ep_copy)
        
        scored.sort(key=lambda x: x['similarity'], reverse=True)
        return scored[:top_k]

    def retrieve_similar(self, query_emb: np.ndarray,
                         top_k: int = 5, min_reward: float = 0.0) -> List[Dict]:
        """
        Recupera episodios con embeddings válidos
        """
        if not self.episodes:
            return []

        candidates = []
        for e in self.episodes:
            if e.get('reward', 0) < min_reward:
                continue
            
            emb = e.get('emb')
            if emb is None or not isinstance(emb, np.ndarray):
                continue
            
            if emb.shape != query_emb.shape:
                continue
            
            if np.all(emb == 0) or np.any(np.isnan(emb)):
                continue
            
            candidates.append(e)
        
        if not candidates:
            return []

        try:
            embs = np.stack([e['emb'] for e in candidates])
            sims = embs @ query_emb
        except Exception as e:
            print(f"[EpisodicMemory] Error calculando similitudes: {e}", file=sys.stderr, flush=True)
            return []

        top_idx = np.argsort(sims)[::-1][:top_k]
        results = []
        for i in top_idx:
            ep = dict(candidates[i])
            ep['similarity'] = float(sims[i])
            if 'emb' in ep:
                del ep['emb']
            results.append(ep)
        return results

    def update_reward(self, query: str, url: str, delta: float):
        """Actualiza reward de episodios específicos"""
        count = 0
        for ep in reversed(self.episodes[-200:]):
            if ep['query'].lower() == query.lower():
                # Buscar resultado con esa URL
                for result in ep.get('results', []):
                    if result.get('url') == url:
                        ep['reward'] = min(1.0, max(0.0, ep['reward'] + delta))
                        count += 1
                        print(f"[EpisodicMemory] Reward actualizado: {query[:30]} -> {ep['reward']:.2f}", file=sys.stderr, flush=True)
                        break
        
        if count == 0:
            print(f"[EpisodicMemory] No se encontró episodio para: {query[:30]}", file=sys.stderr, flush=True)

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'rb') as f:
                self.episodes = pickle.load(f)
            print(f"[EpisodicMemory] ✅ Cargados {len(self.episodes)} episodios", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[EpisodicMemory] ⚠️ Error cargando: {e}", file=sys.stderr, flush=True)
            self.episodes = []

    def save(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, 'wb') as f:
                pickle.dump(self.episodes, f)
            print(f"[EpisodicMemory] ✅ Guardados {len(self.episodes)} episodios", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[EpisodicMemory] ⚠️ Error guardando: {e}", file=sys.stderr, flush=True)

    def stats(self) -> dict:
        if not self.episodes:
            return {'total': 0, 'avg_reward': 0, 'recent_queries': []}
        
        valid_episodes = [e for e in self.episodes if 'reward' in e]
        
        if not valid_episodes:
            return {'total': len(self.episodes), 'avg_reward': 0, 'recent_queries': []}
        
        rewards = [e['reward'] for e in valid_episodes]
        return {
            'total': len(self.episodes),
            'avg_reward': round(float(np.mean(rewards)), 3),
            'max_reward': round(float(np.max(rewards)), 3),
            'recent_queries': [e['query'] for e in self.episodes[-5:]]
        }


# ─────────────────────────────────────────────
#  MEMORIA SEMÁNTICA (MEJORADA)
# ─────────────────────────────────────────────

class SemanticMemory:
    """
    Almacena hechos, preferencias y patrones de largo plazo.
    MEJORADO: Mejor extracción automática de hechos.
    """

    def __init__(self, path: str = 'data/semantic.json'):
        self.path = path
        self.facts: Dict[str, Dict] = {}
        self.preferences: Dict[str, float] = {}
        self.query_clusters: Dict[str, List[str]] = {}
        self._load()

    def learn_fact(self, concept: str, value: str, confidence: float = 0.7):
        """
        Almacena un hecho con confianza acumulativa progresiva.
        MEJORADO: Ponderación más agresiva para retener info nueva con alta confianza.
        """
        existing = self.facts.get(concept, {})
        old_conf = existing.get('confidence', 0)
        # Peso más agresivo: 70% nuevo, 30% viejo (era 40/60 invertido)
        new_conf = old_conf * 0.3 + confidence * 0.7

        self.facts[concept] = {
            'value': value,
            'confidence': round(min(new_conf, 1.0), 3),
            'ts': time.time(),
            'updates': existing.get('updates', 0) + 1
        }

        print(f"[SemanticMemory] Hecho aprendido: {concept} = {value} (conf: {new_conf:.2f})", file=sys.stderr, flush=True)

    def get_all_facts_for_context(self, min_confidence: float = 0.4) -> str:
        """
        Devuelve TODOS los hechos aprendidos como bloque de texto para inyectar al LLM.
        Filtra por confianza mínima y ordena por confianza descendente.
        """
        if not self.facts:
            return ""

        # Labels legibles para cada tipo de hecho
        LABELS = {
            'user_name':       'Nombre del usuario',
            'user_nickname':   'Apodo del usuario',
            'user_alt_name':   'Nombre alternativo',
            'user_age':        'Edad',
            'user_birth_year': 'Año de nacimiento',
            'user_birthday':   'Cumpleaños',
            'user_location':   'Ubicación',
            'user_country':    'País',
            'user_neighborhood': 'Barrio/Sector',
            'user_profession': 'Profesión',
            'user_study':      'Estudios',
            'user_workplace':  'Lugar de trabajo',
            'user_seniority':  'Años de experiencia',
            'fav_game':        'Juego favorito',
            'gaming_platform': 'Plataforma de juego',
            'gaming_character':'Personaje favorito',
            'gaming_level':    'Nivel de juego',
            'user_language':   'Idioma',
            'learning_language':'Idioma que aprende',
            'user_os':         'Sistema operativo',
            'user_phone':      'Teléfono/Dispositivo',
            'preference_like': 'Le gusta',
            'preference_dislike': 'No le gusta',
            'preference_fav':  'Favorito',
            'interest':        'Interés',
            'passion':         'Pasión',
            'recent_purchase': 'Compra reciente',
            'purchase_intent': 'Quiere comprar',
        }

        valid = [
            (k, v) for k, v in self.facts.items()
            if (v.get('confidence', 0) if isinstance(v, dict) else 0.5) >= min_confidence
        ]
        # Ordenar por confianza descendente
        valid.sort(key=lambda x: (x[1].get('confidence', 0) if isinstance(x[1], dict) else 0.5), reverse=True)

        lines = []
        for key, entry in valid:
            val  = entry.get('value', '') if isinstance(entry, dict) else entry
            conf = entry.get('confidence', 0.5) if isinstance(entry, dict) else 0.5
            label = LABELS.get(key, key.replace('_', ' ').capitalize())
            if val:
                lines.append(f"  • {label}: {val}  (confianza: {conf:.0%})")

        # También añadir preferencias aprendidas
        pref_lines = []
        for k, v in sorted(self.preferences.items(), key=lambda x: x[1], reverse=True):
            if v > 0.6:  # solo preferencias fuertes
                pref_lines.append(f"  • Preferencia por '{k}': {v:.0%}")

        result = ""
        if lines:
            result += "📚 Hechos aprendidos del usuario:\n" + "\n".join(lines)
        if pref_lines:
            result += "\n\n🎯 Preferencias detectadas:\n" + "\n".join(pref_lines[:20])
        if self.query_clusters:
            topics = list(self.query_clusters.keys())
            result += f"\n\n🗂 Temas que el usuario ha explorado ({len(topics)} clusters): {', '.join(topics[:15])}"

        return result

    def get_fact(self, concept: str) -> Optional[Dict]:
        """Obtiene un hecho específico"""
        return self.facts.get(concept)

    def update_preference(self, key: str, delta: float):
        """Refuerza o debilita una preferencia"""
        current = self.preferences.get(key, 0.5)
        self.preferences[key] = max(0.0, min(1.0, current + delta))

    def get_preference(self, key: str) -> float:
        return self.preferences.get(key, 0.5)

    def add_to_cluster(self, topic: str, query: str):
        """Agrupa queries por tema — capacidad ×10"""
        if topic not in self.query_clusters:
            self.query_clusters[topic] = []
        if query not in self.query_clusters[topic]:
            self.query_clusters[topic].append(query)
            if len(self.query_clusters[topic]) > 500:          # era 50 → ×10
                self.query_clusters[topic] = self.query_clusters[topic][-500:]

    def get_related_queries(self, topic: str, n: int = 50) -> List[str]:   # era 5 → ×10
        return self.query_clusters.get(topic, [])[-n:]

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.facts = data.get('facts', {})
            self.preferences = data.get('preferences', {})
            self.query_clusters = data.get('query_clusters', {})
            print(f"[SemanticMemory] ✅ Cargados {len(self.facts)} hechos", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SemanticMemory] ⚠️ Error cargando: {e}", file=sys.stderr, flush=True)

    def save(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump({
                    'facts': self.facts,
                    'preferences': self.preferences,
                    'query_clusters': self.query_clusters
                }, f, ensure_ascii=False, indent=2)
            print(f"[SemanticMemory] ✅ Guardados {len(self.facts)} hechos", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[SemanticMemory] ⚠️ Error guardando: {e}", file=sys.stderr, flush=True)

    def stats(self) -> dict:
        return {
            'facts': len(self.facts),
            'preferences': len(self.preferences),
            'clusters': len(self.query_clusters)
        }

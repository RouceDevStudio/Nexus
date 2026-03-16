#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS - Dynamic Parameter Growth System
Sistema de parámetros que crece orgánicamente
"""

import numpy as np
import pickle
import os
from pathlib import Path
from collections import defaultdict
import time
import sys


# ═══════════════════════════════════════════════════════════
#  CAPA DINÁMICA (Puede crecer)
# ═══════════════════════════════════════════════════════════

class DynamicLayer:
    """Capa neuronal que puede agregar neuronas dinámicamente"""
    
    def __init__(self, in_size: int, out_size: int, activation: str = 'relu'):
        # Inicialización He
        self.W = np.random.randn(in_size, out_size) * np.sqrt(2.0 / in_size)
        self.b = np.zeros((1, out_size))
        self.activation = activation
        
        # Estado para backprop
        self._x = None
        self._z = None
        
        # Adam
        self.mW = np.zeros_like(self.W)
        self.vW = np.zeros_like(self.W)
        self.mb = np.zeros_like(self.b)
        self.vb = np.zeros_like(self.b)
        self.t = 0
        
        # Métricas de uso
        self.activation_stats = []
        self.gradient_stats = []
    
    def forward(self, x: np.ndarray, training: bool = False) -> np.ndarray:
        self._x = x
        self._z = x @ self.W + self.b
        out = self._activate(self._z)
        
        # Guardar estadísticas de activación
        if training:
            self.activation_stats.append(np.mean(np.abs(out)))
            if len(self.activation_stats) > 1000:
                self.activation_stats = self.activation_stats[-500:]
        
        return out
    
    def backward(self, grad_out: np.ndarray, lr: float = 1e-3):
        dz = grad_out * self._activate_grad(self._z)
        dW = self._x.T @ dz
        db = np.sum(dz, axis=0, keepdims=True)
        dx = dz @ self.W.T
        
        # Guardar estadísticas de gradiente
        self.gradient_stats.append(np.mean(np.abs(dW)))
        if len(self.gradient_stats) > 1000:
            self.gradient_stats = self.gradient_stats[-500:]
        
        # Adam update
        self.t += 1
        self.mW = 0.9 * self.mW + 0.1 * dW
        self.vW = 0.999 * self.vW + 0.001 * dW ** 2
        mW_c = self.mW / (1 - 0.9 ** self.t)
        vW_c = self.vW / (1 - 0.999 ** self.t)
        self.W -= lr * mW_c / (np.sqrt(vW_c) + 1e-8)
        
        self.mb = 0.9 * self.mb + 0.1 * db
        self.vb = 0.999 * self.vb + 0.001 * db ** 2
        mb_c = self.mb / (1 - 0.9 ** self.t)
        vb_c = self.vb / (1 - 0.999 ** self.t)
        self.b -= lr * mb_c / (np.sqrt(vb_c) + 1e-8)
        
        return dx
    
    def _activate(self, z):
        if self.activation == 'relu':
            return np.maximum(0, z)
        elif self.activation == 'leaky_relu':
            return np.where(z > 0, z, 0.01 * z)
        elif self.activation == 'sigmoid':
            return 1 / (1 + np.exp(-np.clip(z, -500, 500)))
        elif self.activation == 'tanh':
            return np.tanh(z)
        return np.maximum(0, z)
    
    def _activate_grad(self, z):
        if self.activation == 'relu':
            return (z > 0).astype(float)
        elif self.activation == 'leaky_relu':
            return np.where(z > 0, 1.0, 0.01)
        elif self.activation == 'sigmoid':
            s = 1 / (1 + np.exp(-np.clip(z, -500, 500)))
            return s * (1 - s)
        elif self.activation == 'tanh':
            return 1 - np.tanh(z) ** 2
        return (z > 0).astype(float)
    
    def grow(self, new_neurons: int):
        """
        ✨ CRECIMIENTO: Agrega nuevas neuronas a esta capa
        """
        old_out = self.W.shape[1]
        new_out = old_out + new_neurons
        
        # Expandir W
        new_W = np.random.randn(self.W.shape[0], new_neurons) * np.sqrt(2.0 / self.W.shape[0])
        self.W = np.hstack([self.W, new_W])
        
        # Expandir b
        new_b = np.zeros((1, new_neurons))
        self.b = np.hstack([self.b, new_b])
        
        # Expandir Adam states
        new_mW = np.zeros((self.mW.shape[0], new_neurons))
        self.mW = np.hstack([self.mW, new_mW])
        
        new_vW = np.zeros((self.vW.shape[0], new_neurons))
        self.vW = np.hstack([self.vW, new_vW])
        
        new_mb = np.zeros((1, new_neurons))
        self.mb = np.hstack([self.mb, new_mb])
        
        new_vb = np.zeros((1, new_neurons))
        self.vb = np.hstack([self.vb, new_vb])
        
        return new_out - old_out  # Retorna cuántas neuronas se agregaron
    
    def is_saturated(self):
        """Detecta si la capa está saturada (necesita más neuronas)"""
        if len(self.activation_stats) < 100:
            return False
        
        # Alta activación promedio = saturación
        recent_activation = np.mean(self.activation_stats[-100:])
        
        # Alta varianza en gradientes = dificultad para aprender
        if len(self.gradient_stats) >= 100:
            gradient_variance = np.var(self.gradient_stats[-100:])
            return recent_activation > 0.8 and gradient_variance > 0.1
        
        return recent_activation > 0.9
    
    def count_params(self):
        """Cuenta parámetros totales"""
        return self.W.size + self.b.size


# ═══════════════════════════════════════════════════════════
#  RED DINÁMICA (Red que crece)
# ═══════════════════════════════════════════════════════════

class DynamicNeuralNet:
    """Red neuronal que puede crecer dinámicamente"""
    
    def __init__(self, layers_cfg: list, lr: float = 1e-3):
        self.layers = []
        self.lr = lr
        self.loss_history = []
        self.growth_history = []
        self.epoch = 0
        
        # Crear capas
        for cfg in layers_cfg:
            self.layers.append(DynamicLayer(
                cfg['in'], cfg['out'],
                activation=cfg.get('act', 'relu')
            ))
        
        # Tracking
        self.last_growth_epoch = 0
        self.stagnation_count = 0
    
    def predict(self, x: np.ndarray) -> np.ndarray:
        out = x
        for layer in self.layers:
            out = layer.forward(out, training=False)
        return out
    
    def train_step(self, x: np.ndarray, y: np.ndarray) -> float:
        # Forward
        out = x
        for layer in self.layers:
            out = layer.forward(out, training=True)
        
        # Loss (MSE)
        diff = out - y
        loss = float(np.mean(diff ** 2))
        self.loss_history.append(loss)
        
        # Truncar historial
        if len(self.loss_history) > 10000:
            self.loss_history = self.loss_history[-5000:]
        
        # Backward
        grad = 2 * diff / diff.size
        for layer in reversed(self.layers):
            grad = layer.backward(grad, lr=self.lr)
        
        self.epoch += 1
        
        # ✨ Auto-crecimiento
        self._check_and_grow()
        
        return loss
    
    def _check_and_grow(self):
        """
        ✨ LÓGICA DE CRECIMIENTO AUTOMÁTICO
        
        Crece si:
        1. Loss no mejora en 500 epochs
        2. Alguna capa está saturada
        3. No ha crecido recientemente (cooldown)
        """
        
        # Cooldown: No crecer muy seguido
        if self.epoch - self.last_growth_epoch < 500:
            return
        
        # Verificar si loss está estancado
        if len(self.loss_history) >= 500:
            recent_loss = np.mean(self.loss_history[-100:])
            older_loss = np.mean(self.loss_history[-500:-400])
            
            # Loss no mejoró
            if recent_loss >= older_loss * 0.95:  # Menos del 5% de mejora
                self.stagnation_count += 1
            else:
                self.stagnation_count = 0
        
        # Verificar saturación de capas
        saturated_layers = [i for i, layer in enumerate(self.layers[:-1])  # No última capa
                           if layer.is_saturated()]
        
        # ✨ DECIDIR CRECER
        should_grow = (
            self.stagnation_count >= 3 or  # 3 veces estancado
            len(saturated_layers) > 0      # Alguna capa saturada
        )
        
        if should_grow:
            self._grow_network(saturated_layers)
            self.last_growth_epoch = self.epoch
            self.stagnation_count = 0
    
    def _grow_network(self, saturated_layers):
        """
        ✨ CRECIMIENTO: Agrega neuronas a capas saturadas
        """
        
        if saturated_layers:
            # Crecer capas saturadas
            for layer_idx in saturated_layers:
                growth_size = max(8, self.layers[layer_idx].W.shape[1] // 4)  # 25% más neuronas
                added = self.layers[layer_idx].grow(growth_size)
                
                # Ajustar capa siguiente (debe recibir más inputs)
                if layer_idx + 1 < len(self.layers):
                    next_layer = self.layers[layer_idx + 1]
                    old_in = next_layer.W.shape[0]
                    new_in = old_in + added
                    
                    # Expandir pesos de entrada de siguiente capa
                    new_W_in = np.random.randn(added, next_layer.W.shape[1]) * np.sqrt(2.0 / new_in)
                    next_layer.W = np.vstack([next_layer.W, new_W_in])
                    
                    # Expandir Adam states
                    new_mW = np.zeros((added, next_layer.mW.shape[1]))
                    next_layer.mW = np.vstack([next_layer.mW, new_mW])
                    new_vW = np.zeros((added, next_layer.vW.shape[1]))
                    next_layer.vW = np.vstack([next_layer.vW, new_vW])
                
                self.growth_history.append({
                    'epoch': self.epoch,
                    'layer': layer_idx,
                    'neurons_added': added,
                    'total_params': self.count_params()
                })
                
                print(f"🌱 [Epoch {self.epoch}] Capa {layer_idx} creció: +{added} neuronas (total params: {self.count_params():,})", file=sys.stderr)
        else:
            # Crecer capa oculta más grande (si loss estancado pero nada saturado)
            largest_layer_idx = max(range(len(self.layers) - 1), 
                                   key=lambda i: self.layers[i].W.shape[1])
            
            growth_size = max(16, self.layers[largest_layer_idx].W.shape[1] // 8)
            added = self.layers[largest_layer_idx].grow(growth_size)
            
            # Ajustar siguiente capa
            if largest_layer_idx + 1 < len(self.layers):
                next_layer = self.layers[largest_layer_idx + 1]
                new_W_in = np.random.randn(added, next_layer.W.shape[1]) * 0.01
                next_layer.W = np.vstack([next_layer.W, new_W_in])
                
                new_mW = np.zeros((added, next_layer.mW.shape[1]))
                next_layer.mW = np.vstack([next_layer.mW, new_mW])
                new_vW = np.zeros((added, next_layer.vW.shape[1]))
                next_layer.vW = np.vstack([next_layer.vW, new_vW])
            
            self.growth_history.append({
                'epoch': self.epoch,
                'layer': largest_layer_idx,
                'neurons_added': added,
                'reason': 'stagnation',
                'total_params': self.count_params()
            })
            
            print(f"🌱 [Epoch {self.epoch}] Crecimiento por estancamiento: +{added} neuronas (total: {self.count_params():,})", file=sys.stderr)
    
    def count_params(self):
        """Cuenta parámetros totales de la red"""
        return sum(layer.count_params() for layer in self.layers)
    
    def avg_recent_loss(self, n: int = 100) -> float:
        if not self.loss_history:
            return 1.0
        return float(np.mean(self.loss_history[-n:]))
    
    def save(self, path: str):
        state = {
            'layers': [{'W': l.W, 'b': l.b, 'mW': l.mW, 'vW': l.vW, 
                       'mb': l.mb, 'vb': l.vb, 't': l.t,
                       'activation': l.activation} for l in self.layers],
            'lr': self.lr,
            'loss_history': self.loss_history[-200:],
            'growth_history': self.growth_history,
            'epoch': self.epoch
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(state, f)
    
    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'rb') as f:
                state = pickle.load(f)
            
            # Reconstruir capas con tamaño correcto
            self.layers = []
            for layer_state in state['layers']:
                in_size, out_size = layer_state['W'].shape
                layer = DynamicLayer(in_size, out_size, layer_state['activation'])
                layer.W = layer_state['W']
                layer.b = layer_state['b']
                layer.mW = layer_state.get('mW', np.zeros_like(layer.W))
                layer.vW = layer_state.get('vW', np.zeros_like(layer.W))
                layer.mb = layer_state.get('mb', np.zeros_like(layer.b))
                layer.vb = layer_state.get('vb', np.zeros_like(layer.b))
                layer.t = layer_state.get('t', 0)
                self.layers.append(layer)
            
            self.lr = state.get('lr', self.lr)
            self.loss_history = state.get('loss_history', [])
            self.growth_history = state.get('growth_history', [])
            self.epoch = state.get('epoch', 0)
            return True
        except Exception as e:
            print(f"[DynamicNeuralNet] Error cargando: {e}", file=sys.stderr)
            return False


# ═══════════════════════════════════════════════════════════
#  EMBEDDINGS INFINITOS
# ═══════════════════════════════════════════════════════════

class InfiniteEmbeddings:
    """Sistema de embeddings sin límite de vocabulario"""
    
    def __init__(self, embed_dim: int = 128, chunk_size: int = 10000):
        self.embed_dim = embed_dim
        self.chunk_size = chunk_size
        self.vocab = {}  # word -> global_index
        self.chunks = []  # Lista de matrices
        self.idf = {}
        self.doc_count = 0
        self.ngram_doc_freq = defaultdict(int)
    
    def add_word(self, word: str) -> int:
        """Agrega palabra nueva (sin límite)"""
        if word in self.vocab:
            return self.vocab[word]
        
        # Nuevo índice global
        idx = len(self.vocab)
        self.vocab[word] = idx
        
        # ¿Necesita nuevo chunk?
        chunk_idx = idx // self.chunk_size
        local_idx = idx % self.chunk_size
        
        if chunk_idx >= len(self.chunks):
            self._create_chunk()
            print(f"📦 Nuevo chunk de embeddings creado. Vocabulario: {len(self.vocab):,} palabras", file=sys.stderr)
        
        # Inicializar embedding
        self.chunks[chunk_idx][local_idx] = np.random.randn(self.embed_dim) * 0.1
        
        return idx
    
    def _create_chunk(self):
        """Crea nuevo chunk de embeddings"""
        new_chunk = np.random.randn(self.chunk_size, self.embed_dim) * 0.1
        self.chunks.append(new_chunk)
    
    def get_embedding(self, word: str) -> np.ndarray:
        """Obtiene embedding de palabra"""
        if word not in self.vocab:
            return np.zeros(self.embed_dim, dtype=np.float32)
        
        idx = self.vocab[word]
        chunk_idx = idx // self.chunk_size
        local_idx = idx % self.chunk_size
        
        return self.chunks[chunk_idx][local_idx]
    
    def vocab_size(self) -> int:
        return len(self.vocab)
    
    def total_params(self) -> int:
        """Parámetros totales en embeddings"""
        return len(self.vocab) * self.embed_dim
    
    def stats(self) -> dict:
        return {
            'vocab_size': len(self.vocab),
            'chunks': len(self.chunks),
            'embed_dim': self.embed_dim,
            'total_params': self.total_params(),
            'size_mb': (self.total_params() * 4) / (1024 * 1024)  # Float32 = 4 bytes
        }


# ═══════════════════════════════════════════════════════════
#  SISTEMA COMPLETO DE PARÁMETROS DINÁMICOS
# ═══════════════════════════════════════════════════════════

class DynamicParameterSystem:
    """Sistema que gestiona crecimiento de toda la arquitectura"""
    
    def __init__(self, initial_budget: int = 1_000_000):
        self.param_budget = initial_budget
        self.networks = {}
        self.embeddings = InfiniteEmbeddings()
        
        # Tracking
        self.creation_time = time.time()
        self.total_operations = 0
        
        print(f"🌱 Sistema de parámetros dinámico inicializado", file=sys.stderr)
        print(f"   Budget: {initial_budget:,} parámetros", file=sys.stderr)
    
    def create_network(self, name: str, architecture: list):
        """Crea una red dinámica"""
        net = DynamicNeuralNet(architecture)
        self.networks[name] = net
        
        params = net.count_params()
        print(f"✓ Red '{name}' creada: {params:,} parámetros", file=sys.stderr)
        
        return net
    
    def get_total_params(self) -> int:
        """Parámetros totales del sistema"""
        network_params = sum(net.count_params() for net in self.networks.values())
        embedding_params = self.embeddings.total_params()
        return network_params + embedding_params
    
    def get_utilization(self) -> float:
        """% de budget utilizado"""
        return self.get_total_params() / self.param_budget
    
    def can_grow(self) -> bool:
        """¿Puede seguir creciendo?"""
        return self.get_total_params() < self.param_budget * 0.95  # 95% límite
    
    def get_stats(self) -> dict:
        """Estadísticas completas"""
        total_params = self.get_total_params()
        
        network_stats = {}
        for name, net in self.networks.items():
            network_stats[name] = {
                'params': net.count_params(),
                'layers': len(net.layers),
                'growth_events': len(net.growth_history),
                'current_loss': net.avg_recent_loss()
            }
        
        return {
            'total_parameters': total_params,
            'parameter_budget': self.param_budget,
            'utilization_pct': self.get_utilization() * 100,
            'can_grow': self.can_grow(),
            'networks': network_stats,
            'embeddings': self.embeddings.stats(),
            'age_hours': (time.time() - self.creation_time) / 3600,
            'total_operations': self.total_operations
        }
    
    def print_report(self):
        """Imprime reporte detallado"""
        stats = self.get_stats()
        
        print("\n" + "="*60)
        print("📊 REPORTE DE PARÁMETROS DINÁMICOS")
        print("="*60)
        print(f"Total parámetros: {stats['total_parameters']:,} / {stats['parameter_budget']:,}")
        print(f"Utilización: {stats['utilization_pct']:.1f}%")
        print(f"Puede crecer: {'✓ Sí' if stats['can_grow'] else '✗ No (límite alcanzado)'}")
        print(f"Tiempo activo: {stats['age_hours']:.1f} horas")
        print(f"\nRedes neuronales:")
        for name, net_stats in stats['networks'].items():
            print(f"  • {name}: {net_stats['params']:,} params, "
                  f"{net_stats['growth_events']} crecimientos, "
                  f"loss={net_stats['current_loss']:.4f}")
        print(f"\nEmbeddings:")
        print(f"  • Vocabulario: {stats['embeddings']['vocab_size']:,} palabras")
        print(f"  • Chunks: {stats['embeddings']['chunks']}")
        print(f"  • Tamaño: {stats['embeddings']['size_mb']:.1f} MB")
        print("="*60 + "\n")


# ═══════════════════════════════════════════════════════════
#  DEMO
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("🧬 DEMO: Sistema de Parámetros Dinámicos\n")
    
    # Crear sistema
    system = DynamicParameterSystem(initial_budget=1_000_000)
    
    # Crear red pequeña inicial
    net = system.create_network('test_net', [
        {'in': 10, 'out': 20, 'act': 'relu'},
        {'in': 20, 'out': 10, 'act': 'relu'},
        {'in': 10, 'out': 1, 'act': 'sigmoid'}
    ])
    
    print(f"\nInicio: {net.count_params():,} parámetros\n")
    
    # Simular entrenamiento que causará crecimiento
    print("Entrenando (causará crecimiento automático)...\n")
    
    for i in range(2000):
        # Datos dummy
        x = np.random.randn(1, 10).astype(np.float32)
        y = np.random.rand(1, 1).astype(np.float32)
        
        loss = net.train_step(x, y)
        
        if i % 500 == 0:
            print(f"Epoch {i}: Loss={loss:.4f}, Params={net.count_params():,}")
    
    # Reporte final
    system.print_report()
    
    # Historial de crecimiento
    if net.growth_history:
        print("\n📈 Historial de crecimiento:")
        for event in net.growth_history:
            print(f"  Epoch {event['epoch']}: +{event['neurons_added']} neuronas "
                  f"en capa {event['layer']} → {event['total_params']:,} params totales")

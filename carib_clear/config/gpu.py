"""GPU compute detection and configuration loading for H200 deployments.

Detects whether we're running on H200 (buildathon compute) or CPU fallback.
Loads model routing config from gpu_config.json.

Usage:
    from carib_clear.config.gpu import get_ollama_client, have_gpu, gpu_config

    if have_gpu():
        client = get_ollama_client()
        response = client.chat(model="kreyol:3b", messages=[...])
    else:
        # fallback to mock rules
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def _load_config() -> Dict[str, Any]:
    """Load gpu_config.json, cached after first read."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    config_path = Path(__file__).parent / "gpu_config.json"
    if not config_path.exists():
        logger.warning("gpu_config.json not found — using defaults")
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE

    with open(config_path) as f:
        _CONFIG_CACHE = json.load(f)
    return _CONFIG_CACHE


def have_gpu() -> bool:
    """Check if GPU is available and enabled.

    Respects USE_GPU=0 env var (force CPU fallback).
    Falls back to torch.cuda.is_available() if env not set.
    """
    env_val = os.environ.get("USE_GPU", "")
    if env_val == "0":
        logger.info("GPU disabled via USE_GPU=0")
        return False
    if env_val == "1":
        return True

    # Auto-detect
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.info(f"GPU detected: {gpu_name} ({vram_gb:.1f} GB VRAM)")

            config = _load_config()
            min_vram = config.get("gpu_detection", {}).get("min_vram_gb", 40)
            if vram_gb < min_vram:
                logger.warning(f"VRAM {vram_gb:.0f}GB < {min_vram}GB minimum — running lean")
            return True
    except ImportError:
        logger.debug("torch not installed — no GPU support")
    except Exception as e:
        logger.warning(f"GPU detection failed: {e}")

    return False


def get_ollama_base_url() -> str:
    """Get Ollama base URL from env override or config default."""
    config = _load_config()
    default = config.get("ollama", {}).get("base_url", "http://localhost:11434")
    return os.environ.get("OLLAMA_BASE_URL", default)


def get_ollama_client():
    """Get an Ollama client with configured base URL.

    Returns None if ollama package is not installed or USE_GPU=0.
    """
    if os.environ.get("USE_GPU") == "0":
        return None

    try:
        import ollama
        return ollama.Client(host=get_ollama_base_url())
    except ImportError:
        logger.warning("ollama package not installed — GPU inference unavailable")
        return None


def get_model_for_task(task: str) -> Optional[str]:
    """Get the best model for a task, respecting env overrides.

    Task names: 'fx_matching', 'credit_scoring', 'compliance', 'embeddings'
    Env vars (use these to override per-task models at deploy time):
        CREDIT_MODEL, FX_MATCHING_MODEL, VOICE_MODEL
    """
    config = _load_config()
    models = config.get("models", {})

    # Check env override first
    env_map = {
        "fx_matching": "FX_MATCHING_MODEL",
        "credit_scoring": "CREDIT_MODEL",
        "compliance": "COMPLIANCE_MODEL",
        "embeddings": "EMBEDDINGS_MODEL",
    }
    env_key = env_map.get(task)
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]

    # Fall back to config
    task_config = models.get(task, {})
    return task_config.get("model") or task_config.get("fallback")


def infer_with_ollama(task: str, prompt: str, system_prompt: str = "") -> Optional[str]:
    """Simple inference helper: send prompt to Ollama, get response back.

    Handles fallback: GPU model -> fallback model -> None.
    Returns None if no model available (caller should use mock/rules).
    """
    client = get_ollama_client()
    if client is None:
        return None

    model = get_model_for_task(task)
    if not model:
        logger.warning(f"No model configured for task '{task}'")
        return None

    config = _load_config()
    inference = config.get("inference", {})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = client.chat(
            model=model,
            messages=messages,
            options={
                "temperature": inference.get("temperature", 0.1),
                "num_predict": inference.get("max_tokens", 2048),
            },
        )
        return response.get("message", {}).get("content", "")
    except Exception as e:
        logger.warning(f"Ollama inference failed for task '{task}': {e}")
        # Try fallback model
        task_config = _load_config().get("models", {}).get(task, {})
        fallback = task_config.get("fallback")
        if fallback and fallback != model:
            try:
                logger.info(f"Falling back to {fallback}")
                response = client.chat(
                    model=fallback,
                    messages=messages,
                    options={"temperature": 0.1, "num_predict": 2048},
                )
                return response.get("message", {}).get("content", "")
            except Exception as e2:
                logger.warning(f"Fallback also failed: {e2}")
        return None

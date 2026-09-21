"""Model identity for vector namespaces; secrets never enter persisted metadata."""
import hashlib
import json

LEGACY_MODEL = "nvidia/llama-embed-nemotron-8b"


def embedding_profile(config):
    emb = config.get("embedding", {})
    provider = emb.get("provider", "local")
    if provider not in {"local", "openai", "google"}:
        raise ValueError("embedding.provider must be local, openai or google")
    model = emb.get("model", LEGACY_MODEL)
    dim = emb.get("dimension", 4096 if provider == "local" and model == LEGACY_MODEL else None)
    if type(dim) is not int or dim < 1:
        raise ValueError("Set embedding.dimension explicitly for a new model")
    base = emb.get("endpoint_url", emb.get("base_url", ""))
    if provider != "local":
        from agents.provider_support import endpoint
        if not base:
            base = "https://generativelanguage.googleapis.com/v1beta" if provider == "google" else ""
        endpoint(base, "embeddings")  # Validate no credentials/query in persisted URL.
    identity = {"provider": provider, "model": model, "dimension": dim,
                "endpoint": base.rstrip("/"), "normalized": True,
                "max_seq_length": emb.get("max_seq_length", 512),
                "task_type": emb.get("task_type"), "revision": emb.get("revision"),
                "text_extraction": "skill_md_sections-v1"}
    legacy = (provider == "local" and model == LEGACY_MODEL and dim == 4096
              and identity["max_seq_length"] == 512 and not identity["revision"] and not identity["task_type"])
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    return {**identity, "id": fingerprint, "legacy": legacy}

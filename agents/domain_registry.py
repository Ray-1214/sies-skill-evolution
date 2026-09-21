"""
domain_registry.py — Domain Label Registry (W4)

Maps SIES domain labels to SkillRL Task-Specific Skills categories.
SkillRL's SkillBank uses two tiers:
  - General Skills: domain-agnostic (e.g., systematic-debugging, test-driven-development)
  - Task-Specific Skills: domain-bound (e.g., web-scraping belongs to "web" domain)

This registry defines the canonical domain taxonomy for SIES, ensuring:
  1. A1's domain output aligns with SkillRL's category system
  2. A2 can filter skills by domain when building working memory
  3. SKILL.md frontmatter 'domain' field uses consistent labels

Usage:
    from agents.domain_registry import DOMAIN_REGISTRY, validate_domain, classify_domain
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical domain taxonomy
# ---------------------------------------------------------------------------
# Each domain maps to:
#   description  — human-readable explanation
#   input_types  — which of the 5 input_type values commonly map here
#   skillrl_cat  — corresponding SkillRL Task-Specific Skills category name
#   keywords     — heuristic trigger words for LLM-free fallback classification
# ---------------------------------------------------------------------------

DOMAIN_REGISTRY: dict[str, dict] = {
    "software-engineering": {
        "description": "Writing, debugging, refactoring, testing code",
        "input_types": ["code_task"],
        "skillrl_cat": "CodeGeneration",
        "keywords": [
            "code", "function", "class", "debug", "refactor", "test",
            "compile", "lint", "api", "sdk", "library", "module",
            "implement", "script", "bug", "error", "exception",
            "python", "javascript", "rust", "java", "sql",
        ],
    },
    "research": {
        "description": "Information gathering, literature review, fact-checking",
        "input_types": ["research_task"],
        "skillrl_cat": "InformationRetrieval",
        "keywords": [
            "research", "search", "find", "investigate", "survey",
            "literature", "paper", "study", "source", "reference",
            "compare", "benchmark", "review", "state-of-the-art",
        ],
    },
    "data-analysis": {
        "description": "Data processing, statistics, visualization, ML",
        "input_types": ["analysis_task"],
        "skillrl_cat": "DataAnalysis",
        "keywords": [
            "data", "analyze", "statistics", "csv", "json", "dataset",
            "visualization", "chart", "graph", "trend", "correlation",
            "model", "prediction", "cluster", "regression", "metric",
        ],
    },
    "content-creation": {
        "description": "Writing, editing, translating, summarizing text",
        "input_types": ["creative_task"],
        "skillrl_cat": "TextGeneration",
        "keywords": [
            "write", "draft", "edit", "translate", "summarize",
            "blog", "article", "essay", "report", "documentation",
            "rewrite", "proofread", "creative", "story", "content",
        ],
    },
    "web-automation": {
        "description": "Browser interaction, scraping, form filling, web testing",
        "input_types": ["web_task"],
        "skillrl_cat": "WebInteraction",
        "keywords": [
            "website", "browser", "scrape", "crawl", "click",
            "navigate", "url", "html", "dom", "form", "login",
            "download", "screenshot", "web", "page", "http",
        ],
    },
    "system-ops": {
        "description": "File management, shell commands, deployment, DevOps",
        "input_types": ["code_task"],
        "skillrl_cat": "SystemOperation",
        "keywords": [
            "file", "directory", "deploy", "docker", "server",
            "install", "configure", "backup", "cron", "shell",
            "permission", "process", "service", "log", "monitor",
        ],
    },
    "planning": {
        "description": "Project planning, task management, scheduling",
        "input_types": ["analysis_task", "creative_task"],
        "skillrl_cat": "Planning",
        "keywords": [
            "plan", "schedule", "roadmap", "milestone", "priority",
            "timeline", "workflow", "strategy", "organize", "coordinate",
        ],
    },
}

# Flat set for O(1) lookup
VALID_DOMAINS = frozenset(DOMAIN_REGISTRY.keys())


def validate_domain(domain: str) -> bool:
    """Check if a domain label is in the canonical registry."""
    return domain in VALID_DOMAINS


def validate_domains(domains: list[str]) -> tuple[list[str], list[str]]:
    """
    Validate a list of domain labels.
    Returns (valid, invalid) tuple.
    """
    valid = [d for d in domains if d in VALID_DOMAINS]
    invalid = [d for d in domains if d not in VALID_DOMAINS]
    return valid, invalid


def classify_domain(text: str) -> list[str]:
    """
    Heuristic (LLM-free) domain classification based on keyword matching.
    Returns up to 2 most-matching domains, sorted by match count descending.
    Used as fallback when LLM output lacks a domain field.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, info in DOMAIN_REGISTRY.items():
        count = sum(1 for kw in info["keywords"] if kw in text_lower)
        if count > 0:
            scores[domain] = count

    if not scores:
        return ["software-engineering"]  # safe default

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [d for d, _ in ranked[:2]]


def get_skillrl_category(domain: str) -> str | None:
    """Map a SIES domain label to its SkillRL Task-Specific Skills category."""
    entry = DOMAIN_REGISTRY.get(domain)
    return entry["skillrl_cat"] if entry else None


def input_type_to_domains(input_type: str) -> list[str]:
    """Given an input_type, return all domains that commonly handle it."""
    return [
        domain
        for domain, info in DOMAIN_REGISTRY.items()
        if input_type in info["input_types"]
    ]
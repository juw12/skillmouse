"""
SkillMouse 2 - your Claude / Codex / OpenCode / Gemini skills AND agents, on any model.

Select text anywhere -> press the mouse forward button (or Ctrl+Alt+Space)
-> search a skill / agent / command -> pick a model -> answer streams in.

Discovers:
  skills    SKILL.md folders (Claude, Codex, OpenCode, Gemini/Antigravity, Vector, .agents)
  agents    agents/*.md (Claude, OpenCode, Codex, skill sub-agents) and persona folders (SOUL.md)
  commands  commands/, command/, prompts/, workflows/ *.md   ($ARGUMENTS supported)
  rules     CLAUDE.md, AGENTS.md, GEMINI.md, .cursorrules
  library   anything you import with the Import button (stored next to this file in library/)

Models: any OpenAI-compatible endpoint (OpenAI, Anthropic, Gemini, OpenRouter, DeepSeek,
Groq, Ollama, LM Studio ...). Standard library only. Windows.

CLI:
    python skillmouse.py                  run in the background
    python skillmouse.py --list           list everything discovered
    python skillmouse.py --models         list usable models
    python skillmouse.py --prompt NAME    print the system prompt for an item
    python skillmouse.py --ask NAME --model provider:model --text "..."
    python skillmouse.py --import PATH    import a skill/agent folder, .md or .zip into the library
"""

import argparse
import bisect
import base64
import copy
import math
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "SkillMouse"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
LIBRARY_DIR = APP_DIR / "library"
CONFIG_VERSION = 2

DEFAULT_SOURCES = [
    "{app}/library",
    "~/.claude/skills",
    "~/.claude/agents",
    "~/.claude/commands",
    "~/.claude/plugins",
    "~/.claude/CLAUDE.md",
    "~/.agents/skills",
    "~/.codex/skills",
    "~/.codex/agents",
    "~/.codex/prompts",
    "~/.codex/AGENTS.md",
    "~/.config/opencode/skills",
    "~/.config/opencode/skill",
    "~/.config/opencode/agent",
    "~/.config/opencode/agents",
    "~/.config/opencode/command",
    "~/.config/opencode/commands",
    "~/.gemini/skills",
    "~/.gemini/commands",
    "~/.gemini/antigravity/skills",
    "~/.gemini/GEMINI.md",
    "~/.vector/skills",
]

DEFAULT_UI = {
    "theme": "Midnight",
    "accent": "",
    "font": "Segoe UI",
    "font_size": 10,
    "opacity": 1.0,
    "show_descriptions": True,
    "width": 760,
    "height": 700,
}

DEFAULT_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-5-mini"],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-sonnet-4-5", "claude-haiku-4-5"],
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": ["deepseek/deepseek-chat", "qwen/qwen3-coder", "meta-llama/llama-3.3-70b-instruct"],
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "models": ["llama-3.3-70b-versatile"],
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "auto_models": True,
        "models": [],
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "auto_models": True,
        "models": [],
    },
}

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "hotkey": "ctrl+alt+space",
    "mouse_button": "x2",
    "drag_modifier": "ctrl",
    "drag_threshold": 28,
    "auto_copy_selection": True,
    "max_context_chars": 60000,
    "default_model": "",
    "sources": DEFAULT_SOURCES,
    "ui": DEFAULT_UI,
    "providers": DEFAULT_PROVIDERS,
}

SKILL_PREAMBLE = """You are executing an agent "skill" originally written for an agentic tool \
(Claude Code / Codex / OpenCode / Gemini). You are now running on a different model inside a \
universal launcher.

Rules:
- Follow the skill's instructions, workflow, output format and tone faithfully.
- You have NO tools, shell, browser or file access in this session. When the skill says to run \
a command, call a tool, or read a file: use the bundled file contents below if present; otherwise \
tell the user the exact command or step to run and continue as far as you can.
- Map vendor-specific tool names to the closest equivalent action.
- Work on the user's input (instruction and/or input text) in the user message.
"""

AGENT_PREAMBLE = """You are now acting as the agent defined below. It was originally written for \
an agentic tool (Claude Code / Codex / OpenCode / Gemini) and now runs on a different model inside \
a universal launcher.

Rules:
- Adopt the agent's role, voice, rules and output format exactly.
- You have NO tools, shell, browser or file access in this session. Where the agent would use a \
tool, work from the provided input, or tell the user precisely what to run or fetch, then continue.
- Ignore tool permission settings in the definition; they do not apply here.
"""

PRUNE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build",
    "site-packages", ".next", "target", "logs", "cache", "projects", "todos",
    "shell-snapshots", "statsig", "sessions", "checkpoints", ".pytest_cache",
}
IGNORED_MD = {"README.MD", "INDEX.MD", "USER_INDEX.MD", "CHANGELOG.MD", "LICENSE.MD", "CONTRIBUTING.MD"}
RULE_FILES = {"CLAUDE.md", "AGENTS.md", "GEMINI.md", ".cursorrules"}
AGENT_DIRS = {"agents", "agent"}
COMMAND_DIRS = {"commands", "command", "prompts", "workflows"}
PERSONA_FILES = ["SOUL.md", "IDENTITY.md", "AGENTS.md", "USER.md", "MEMORY.md"]
BUNDLE_EXT_PRIORITY = {
    ".md": 0, ".txt": 0, ".yaml": 1, ".yml": 1, ".json": 1, ".toml": 1,
    ".py": 2, ".sh": 2, ".ps1": 2, ".js": 2, ".ts": 2,
}
KIND_ORDER = {"builtin": -1, "skill": 0, "agent": 1, "command": 2, "rules": 3}
KIND_LABEL = {"builtin": "ASK", "skill": "SKILL", "agent": "AGENT", "command": "CMD", "rules": "RULES"}


# =========================================================================== config

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_config():
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)
    stored = load_json(CONFIG_PATH, {})
    if stored.get("version", 1) < CONFIG_VERSION:
        old_dirs = list(stored.pop("skill_dirs", [])) + list(stored.pop("extra_dirs", []))
        sources = list(DEFAULT_SOURCES)
        for directory in old_dirs:
            if directory not in sources:
                sources.append(directory)
        stored["sources"] = sources
        stored["version"] = CONFIG_VERSION
        for key in [k for k in stored if k.startswith("_")]:
            stored.pop(key)
        save_json(CONFIG_PATH, stored)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update({k: v for k, v in stored.items() if k not in ("ui", "providers")})
    config["ui"] = {**DEFAULT_UI, **stored.get("ui", {})}
    providers = copy.deepcopy(DEFAULT_PROVIDERS)
    for name, provider in stored.get("providers", {}).items():
        providers[name] = {**providers.get(name, {}), **provider}
    config["providers"] = providers
    return config


def expand(path_text):
    text = path_text.replace("{app}", str(APP_DIR))
    return Path(os.path.expandvars(os.path.expanduser(text)))


# =========================================================================== discovery

@dataclass
class Item:
    name: str
    description: str
    kind: str
    path: Path = None
    source: str = ""
    key: str = ""
    persona: bool = False

    @property
    def search_text(self):
        return f"{self.name} {self.description} {self.source} {self.kind}".lower()


ASK_ITEM = Item("Just ask", "Send your input to the model with no skill", "builtin", source="", key="__ask__")


def parse_frontmatter(text):
    meta = {}
    body = text
    match = re.match(r"^\ufeff?---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", text, re.S)
    if not match:
        return meta, body
    body = text[match.end():]
    lines = match.group(1).splitlines()
    index = 0
    while index < len(lines):
        key_match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", lines[index])
        index += 1
        if not key_match:
            continue
        key = key_match.group(1).lower()
        value = key_match.group(2).strip()
        if value in (">", "|", ">-", "|-", ">+", "|+"):
            block = []
            while index < len(lines) and (lines[index].startswith((" ", "\t")) or not lines[index].strip()):
                block.append(lines[index].strip())
                index += 1
            value = " ".join(part for part in block if part)
        meta[key] = value.strip().strip("\"'")
    return meta, body


def first_meaningful_line(body):
    for line in body.splitlines():
        stripped = line.strip().lstrip("#>*-").strip()
        if stripped and not stripped.startswith("---"):
            return stripped
    return ""


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")


CUSTOM_SOURCE_LABELS = []   # filled from config["source_labels"]: {"path": "Label"}


def source_label(path):
    lowered = str(path).lower().replace("/", "\\")
    for prefix, label in CUSTOM_SOURCE_LABELS:
        if lowered.startswith(prefix):
            return label
    rules = [
        (str(LIBRARY_DIR).lower(), "Library"),
        ("\\.config\\opencode", "OpenCode"),
        ("\\.opencode\\", "OpenCode"),
        ("\\.claude\\", "Claude"),
        ("\\.codex\\", "Codex"),
        ("\\.gemini\\", "Gemini"),
        ("\\.agents\\", "Agents"),
        ("\\.vector\\", "Vector"),
    ]
    for needle, label in rules:
        if needle in lowered:
            return label
    return Path(path).parent.name


def persona_text(folder):
    parts = []
    for name in PERSONA_FILES:
        path = Path(folder) / name
        if path.exists():
            parts.append(f"## {name}\n{read_text(path).strip()}")
    return "\n\n".join(parts)


def make_item(path, kind, persona=False):
    path = Path(path)
    if persona:
        text = persona_text(path.parent)
        identity = path.parent / "IDENTITY.md"
        description = first_meaningful_line(read_text(identity if identity.exists() else path))
        name = path.parent.name
        meta = {}
    else:
        text = read_text(path)
        meta, body = parse_frontmatter(text)
        description = meta.get("description") or first_meaningful_line(body)
        if kind == "skill":
            name = meta.get("name") or path.parent.name
        elif kind == "agent":
            name = meta.get("name") or re.sub(r"\.(agent|chatmode|prompt)$", "", path.stem)
        elif kind == "command":
            name = "/" + path.stem
        else:
            name = f"{path.name} - {path.parent.name}"
    digest = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
    return Item(name, description, kind, path, source_label(path), digest, persona)


def walk_sources(root, found, depth=0, inside_skill=False):
    if depth > 6:
        return
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return
    names = {entry.name for entry in entries}
    folder_name = Path(root).name.lower()
    has_skill = "SKILL.md" in names
    has_persona = "SOUL.md" in names and not inside_skill and not has_skill
    if has_skill:
        found.append(make_item(Path(root) / "SKILL.md", "skill"))
    if has_persona:
        found.append(make_item(Path(root) / "SOUL.md", "agent", persona=True))
    for entry in entries:
        try:
            is_file = entry.is_file()
        except OSError:
            continue
        if not is_file:
            continue
        name = entry.name
        upper = name.upper()
        if not upper.endswith(".MD") and name not in RULE_FILES:
            continue
        if upper in IGNORED_MD or name == "SKILL.md":
            continue
        if folder_name in AGENT_DIRS:
            found.append(make_item(entry.path, "agent"))
        elif has_persona and name in PERSONA_FILES:
            continue
        elif name in RULE_FILES and not inside_skill and not has_skill:
            found.append(make_item(entry.path, "rules"))
        elif folder_name in COMMAND_DIRS and not inside_skill and not has_skill:
            found.append(make_item(entry.path, "command"))
    for entry in entries:
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir and entry.name not in PRUNE_DIRS:
            walk_sources(entry.path, found, depth + 1, inside_skill or has_skill)


def discover_items(config):
    CUSTOM_SOURCE_LABELS.clear()
    for raw_path, label in config.get("source_labels", {}).items():
        CUSTOM_SOURCE_LABELS.append((str(expand(raw_path)).lower().replace("/", "\\"), label))
    found = []
    for raw in config.get("sources", []):
        path = expand(raw)
        try:
            if path.is_file():
                if path.name in RULE_FILES:
                    kind = "rules"
                elif path.name == "SKILL.md":
                    kind = "skill"
                elif path.parent.name.lower() in AGENT_DIRS:
                    kind = "agent"
                else:
                    kind = "command"
                found.append(make_item(path, kind))
            elif path.is_dir():
                walk_sources(str(path), found)
        except OSError:
            continue
    unique = {}
    seen_signatures = set()
    for item in found:
        signature = (item.kind, item.name.lower(), item.description.lower())
        if item.key in unique or signature in seen_signatures:
            continue
        unique[item.key] = item
        seen_signatures.add(signature)
    return sorted(unique.values(), key=lambda i: (KIND_ORDER[i.kind], i.name.lower()))


def bundled_files(skill_dir, main_file):
    files = []
    for path in skill_dir.rglob("*"):
        if path == main_file or not path.is_file():
            continue
        relative_parts = path.relative_to(skill_dir).parts
        if any(part in PRUNE_DIRS for part in relative_parts):
            continue
        priority = BUNDLE_EXT_PRIORITY.get(path.suffix.lower())
        if priority is None:
            continue
        files.append((priority, len(relative_parts), str(path).lower(), path))
    return [entry[3] for entry in sorted(files)]


def build_system_prompt(item, instruction, budget):
    if item.kind == "builtin":
        return "You are a helpful, precise assistant. Work on the user's input."
    if item.kind == "agent":
        if item.persona:
            body = persona_text(item.path.parent)
        else:
            _, body = parse_frontmatter(read_text(item.path))
        return f"{AGENT_PREAMBLE}\n# Agent: {item.name}\n{item.description}\n\n{body.strip()}"
    _, body = parse_frontmatter(read_text(item.path))
    body = body.strip()
    if item.kind == "command":
        body = body.replace("$ARGUMENTS", instruction or "(see user message)")
        body = re.sub(r"\$\d+", "", body)
    header = {"skill": "Skill", "command": "Slash command", "rules": "Project rules"}[item.kind]
    parts = [SKILL_PREAMBLE, f"\n# {header}: {item.name}\n{item.description}\n\n{body}"]
    used = sum(len(part) for part in parts)
    if item.kind == "skill":
        skill_dir = item.path.parent
        omitted = []
        for path in bundled_files(skill_dir, item.path):
            relative = path.relative_to(skill_dir).as_posix()
            try:
                content = read_text(path)
            except OSError:
                continue
            block = f"\n\n### Bundled file: {relative}\n```\n{content.strip()}\n```"
            if used + len(block) > budget:
                omitted.append(relative)
                continue
            parts.append(block)
            used += len(block)
        if omitted:
            parts.append("\n\n(Files not included, context budget reached: " + ", ".join(omitted) + ")")
    return "".join(parts)


def build_user_message(selection, instruction):
    parts = []
    if instruction.strip():
        parts.append(instruction.strip())
    if selection.strip():
        parts.append("Input text:\n<<<\n" + selection.strip() + "\n>>>")
    return "\n\n".join(parts) or "Begin."


# =========================================================================== library import

def classify_markdown(path):
    text = read_text(path)
    meta, _ = parse_frontmatter(text)
    parent = path.parent.name.lower()
    if parent in AGENT_DIRS or any(key in meta for key in ("mode", "tools", "model", "color", "temperature")):
        return "agent"
    if parent in COMMAND_DIRS or "argument-hint" in meta or "$ARGUMENTS" in text:
        return "command"
    return "skill"


def unique_path(path):
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{number}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path


def import_into_library(source):
    """Copy a skill/agent folder, .md file or .zip into the library. Returns imported labels."""
    source = Path(source)
    imported = []
    for sub in ("skills", "agents", "commands"):
        (LIBRARY_DIR / sub).mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as temp:
            with zipfile.ZipFile(source) as archive:
                archive.extractall(temp)
            return import_into_library(Path(temp))
    if source.is_dir():
        skill_files = [p for p in source.rglob("SKILL.md") if not any(x in PRUNE_DIRS for x in p.parts)]
        for skill_file in skill_files:
            target = LIBRARY_DIR / "skills" / skill_file.parent.name
            shutil.copytree(skill_file.parent, target, dirs_exist_ok=True)
            imported.append(f"skill {skill_file.parent.name}")
        if (source / "SOUL.md").exists():
            target = LIBRARY_DIR / "agents" / source.name
            shutil.copytree(source, target, dirs_exist_ok=True)
            imported.append(f"agent {source.name}")
        if not skill_files and not (source / "SOUL.md").exists():
            for md_file in sorted(source.glob("*.md")):
                if md_file.name.upper() not in IGNORED_MD:
                    imported.extend(import_into_library(md_file))
        return imported
    if source.suffix.lower() == ".md":
        if source.name == "SKILL.md":
            target = LIBRARY_DIR / "skills" / source.parent.name
            shutil.copytree(source.parent, target, dirs_exist_ok=True)
            return [f"skill {source.parent.name}"]
        kind = classify_markdown(source)
        if kind == "agent":
            shutil.copy2(source, unique_path(LIBRARY_DIR / "agents" / source.name))
        elif kind == "command":
            shutil.copy2(source, unique_path(LIBRARY_DIR / "commands" / source.name))
        else:
            folder = unique_path(LIBRARY_DIR / "skills" / source.stem)
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder / "SKILL.md")
        return [f"{kind} {source.stem}"]
    return imported


SKILL_TEMPLATE = """---
name: {name}
description: One sentence - what this skill does and when to use it.
---

# {title}

## Goal
Describe the outcome you want.

## Steps
1. ...
2. ...

## Output format
- ...
"""

AGENT_TEMPLATE = """---
name: {name}
description: One sentence - who this agent is and when to use it.
---

You are {title}. Your job is ...

Rules:
- ...

Output format:
- ...
"""


def create_from_template(kind):
    if kind == "skill":
        folder = unique_path(LIBRARY_DIR / "skills" / "my-skill")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "SKILL.md"
        path.write_text(SKILL_TEMPLATE.format(name=folder.name, title=folder.name.replace("-", " ").title()), encoding="utf-8")
    else:
        (LIBRARY_DIR / "agents").mkdir(parents=True, exist_ok=True)
        path = unique_path(LIBRARY_DIR / "agents" / "my-agent.md")
        path.write_text(AGENT_TEMPLATE.format(name=path.stem, title=path.stem.replace("-", " ").title()), encoding="utf-8")
    return path


# =========================================================================== dropped content

TEXT_FILE_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".log", ".html", ".htm", ".css", ".scss", ".xml",
    ".sql", ".sh", ".ps1", ".bat", ".cmd", ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".kt", ".go",
    ".rs", ".rb", ".php", ".swift", ".m", ".r", ".lua", ".vue", ".svelte", ".tex", ".srt", ".env",
}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
              ".webp": "image/webp", ".bmp": "image/bmp"}


def office_text(path):
    """Plain text from .docx / .pptx (zip + XML), no extra libraries."""
    parts = []
    with zipfile.ZipFile(path) as archive:
        names = sorted(n for n in archive.namelist()
                       if n == "word/document.xml" or re.match(r"ppt/slides/slide\d+\.xml$", n))
        for name in names:
            xml = archive.read(name).decode("utf-8", "replace")
            xml = re.sub(r"</(w:p|a:p)>", "\n", xml)
            parts.append(re.sub(r"<[^>]+>", "", xml))
    return "\n".join(parts).strip()


def read_dropped_file(path, budget):
    """Returns (text_block, image_part). Either may be None."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if path.is_dir():
            names = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())[:200]
            return f"Folder: {path}\n" + "\n".join(names), None
        if suffix in IMAGE_MIME:
            if path.stat().st_size > 8 * 1024 * 1024:
                return f"Image: {path.name} (too large to send, over 8 MB)", None
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            part = {"type": "image_url", "image_url": {"url": f"data:{IMAGE_MIME[suffix]};base64,{data}"}}
            return f"Image attached: {path.name}", part
        if suffix in (".docx", ".pptx"):
            content = office_text(path)[:budget]
        elif suffix in TEXT_FILE_EXT or path.stat().st_size < 400_000:
            raw = path.read_bytes()[: budget * 4]
            if b"\x00" in raw[:4096]:
                return f"File: {path.name} (binary file - not readable as text)", None
            content = raw.decode("utf-8", errors="replace")[:budget]
        else:
            return f"File: {path.name} (large binary file - not read)", None
    except Exception as error:
        return f"File: {path.name} (could not read: {error})", None
    return f"File: {path.name}\n```\n{content}\n```", None


def payload_to_input(payload, budget=60000):
    """payload = {'text': str, 'files': [paths]} -> (input_text, image_parts)."""
    blocks = []
    images = []
    if payload.get("text"):
        blocks.append(payload["text"])
    files = payload.get("files") or []
    share = max(4000, budget // max(1, len(files)))
    for file_path in files:
        block, image_part = read_dropped_file(file_path, share)
        if block:
            blocks.append(block)
        if image_part:
            images.append(image_part)
    return "\n\n".join(blocks), images


# =========================================================================== models

def provider_key(provider):
    return provider.get("api_key") or os.environ.get(provider.get("api_key_env", ""), "")


def fetch_local_models(provider):
    try:
        url = provider["base_url"].rstrip("/") + "/models"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {provider_key(provider)}"})
        with urllib.request.urlopen(request, timeout=3) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [item["id"] for item in data.get("data", [])]
    except Exception:
        return []


def available_models(config):
    models = []
    for name, provider in config.get("providers", {}).items():
        if provider.get("disabled") or not provider_key(provider):
            continue
        listed = fetch_local_models(provider) if provider.get("auto_models") else list(provider.get("models", []))
        models.extend(f"{name}:{model}" for model in listed)
    return models


def stream_chat(config, model_ref, messages, on_delta, stop_event):
    provider_name, model = model_ref.split(":", 1)
    provider = config["providers"][provider_name]
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "stream": True}
    payload.update(provider.get("extra_body", {}))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider_key(provider)}",
        "User-Agent": "SkillMouse/2.0",
    }
    headers.update(provider.get("headers", {}))
    request = urllib.request.Request(url, json.dumps(payload).encode("utf-8"), headers)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            for raw_line in response:
                if stop_event.is_set():
                    break
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                thinking = delta.get("reasoning") or delta.get("reasoning_content")
                if thinking:
                    on_delta(thinking, "reasoning")
                if delta.get("content"):
                    on_delta(delta["content"], "content")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"{provider_name} HTTP {error.code}: {detail}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach {provider_name} ({url}): {error.reason}") from None


# =========================================================================== Win32

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
    ]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetForegroundWindow.restype = wt.HWND
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.OpenClipboard.argtypes = [wt.HWND]
user32.GetClipboardData.argtypes = [wt.UINT]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.GetClipboardSequenceNumber.restype = wt.DWORD
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.GetParent.argtypes = [wt.HWND]
user32.GetParent.restype = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
user32.MonitorFromPoint.restype = wt.HMONITOR
user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE

WH_MOUSE_LL = 14
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEWHEEL = 0x0200, 0x0201, 0x0202, 0x020A
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
LLMHF_INJECTED = 0x01
CF_UNICODETEXT = 13
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN, VK_TAB = 0x10, 0x11, 0x12, 0x5B, 0x5C, 0x09
KEYEVENTF_KEYUP = 0x0002
TERMINAL_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "mintty", "VirtualConsoleClass"}
MODIFIERS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
NAMED_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "backquote": 0xC0, "`": 0xC0}


def parse_hotkey(text):
    modifiers, key = 0x4000, None   # MOD_NOREPEAT
    for part in text.lower().replace(" ", "").split("+"):
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif part in NAMED_KEYS:
            key = NAMED_KEYS[part]
        elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", part):
            key = 0x6F + int(part[1:])
        elif len(part) == 1:
            key = ord(part.upper())
    return modifiers, key


def window_class(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def open_clipboard():
    for _ in range(20):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def get_clipboard_text():
    if not open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    buffer = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buffer)
    if not open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(0x0002, size)
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, buffer, size)
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(CF_UNICODETEXT, handle)
        return True
    finally:
        user32.CloseClipboard()


def tap_ctrl_and(letter):
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(ord(letter), 0, 0, 0)
    user32.keybd_event(ord(letter), 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def wait_for_modifiers_released(timeout=0.8):
    deadline = time.time() + timeout
    while time.time() < deadline:
        held = any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))
        if not held:
            return
        time.sleep(0.02)


def grab_selection(target_hwnd):
    """Copy the foreground app's selection, then restore the user's clipboard."""
    if window_class(target_hwnd) in TERMINAL_CLASSES:
        return ""   # Ctrl+C in a terminal would send an interrupt
    wait_for_modifiers_released()
    previous = get_clipboard_text()
    sequence = user32.GetClipboardSequenceNumber()
    tap_ctrl_and("C")
    deadline = time.time() + 0.6
    while time.time() < deadline and user32.GetClipboardSequenceNumber() == sequence:
        time.sleep(0.02)
    if user32.GetClipboardSequenceNumber() == sequence:
        return ""
    time.sleep(0.03)
    selection = get_clipboard_text() or ""
    if previous is not None:
        set_clipboard_text(previous)
    return selection


def force_foreground(hwnd):
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
    attached = False
    if foreground_thread and foreground_thread != current_thread:
        attached = bool(user32.AttachThreadInput(foreground_thread, current_thread, True))
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(foreground_thread, current_thread, False)


def work_area_at(x, y):
    monitor = user32.MonitorFromPoint(wt.POINT(x, y), 2)   # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        work = info.rcWork
        return work.left, work.top, work.right, work.bottom
    return 0, 0, 1920, 1080


def style_title_bar(window, theme):
    """Dark/colored native title bar (Windows 10 20H1+ / Windows 11). Silently ignored elsewhere."""
    try:
        hwnd = int(window.wm_frame(), 16)
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if theme["dark"] else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
        red, green, blue = hex_to_rgb(theme["bg"])
        caption = ctypes.c_int(red | (green << 8) | (blue << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
        red, green, blue = hex_to_rgb(theme["text"])
        text_color = ctypes.c_int(red | (green << 8) | (blue << 16))
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), 4)
    except Exception:
        pass


class InputListener(threading.Thread):
    """Global hotkey + low-level mouse hook (trigger button, modifier+drag gesture, donut wheel)."""

    def __init__(self, events, hotkey, mouse_button, drag_modifier="ctrl", drag_threshold=28):
        super().__init__(daemon=True)
        self.events = events
        self.hotkey = hotkey
        self.mouse_button = (mouse_button or "none").lower()
        self.drag_modifier = (drag_modifier or "none").lower()
        self.drag_threshold = int(drag_threshold or 28)
        self.accept_injected = False   # only enabled by --selftest
        self.donut_visible = False
        self.press_point = None
        self.dragging = False
        self.thread_id = None
        self.status = []
        self._proc = HOOKPROC(self._mouse_proc)

    @property
    def needs_hook(self):
        return self.mouse_button != "none" or self.drag_modifier != "none"

    def _modifier_held(self):
        vk = {"ctrl": VK_CONTROL, "alt": VK_MENU, "shift": VK_SHIFT}.get(self.drag_modifier)
        return bool(vk and user32.GetAsyncKeyState(vk) & 0x8000)

    def _mouse_proc(self, code, w_param, l_param):
        if code == 0:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not info.flags & LLMHF_INJECTED or self.accept_injected:
                x, y = info.pt.x, info.pt.y
                if w_param == WM_MOUSEMOVE:
                    if self.press_point and not self.dragging and self.drag_modifier != "none":
                        dx = x - self.press_point[0]
                        dy = y - self.press_point[1]
                        if dx * dx + dy * dy >= self.drag_threshold ** 2 and self._modifier_held():
                            self.dragging = True
                            self.events.put(("drag_start", x, y))
                elif w_param == WM_LBUTTONDOWN:
                    self.press_point = (x, y)
                    self.dragging = False
                elif w_param == WM_LBUTTONUP:
                    if self.dragging:
                        self.events.put(("drag_end", x, y))
                    self.press_point = None
                    self.dragging = False
                elif w_param == WM_MOUSEWHEEL:
                    if self.donut_visible:
                        delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                        self.events.put(("wheel", delta))
                        return 1
                elif self.mouse_button != "none":
                    button = None
                    if w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                        button = "x1" if (info.mouseData >> 16) & 0xFFFF == 1 else "x2"
                    elif w_param in (WM_MBUTTONDOWN, WM_MBUTTONUP):
                        button = "middle"
                    if button == self.mouse_button:
                        if w_param in (WM_XBUTTONDOWN, WM_MBUTTONDOWN):
                            self.events.put("trigger")
                        return 1   # swallow so the app underneath doesn't also go back/forward
        return user32.CallNextHookEx(None, code, w_param, l_param)

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        modifiers, key = parse_hotkey(self.hotkey or "")
        if key and user32.RegisterHotKey(None, 1, modifiers, key):
            self.status.append(self.hotkey)
        elif key:
            self.status.append(f"{self.hotkey} (in use)")
        hook = None
        if self.needs_hook:
            hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
            labels = {"x1": "mouse back", "x2": "mouse forward", "middle": "middle click"}
            parts = []
            if self.mouse_button != "none":
                parts.append(labels.get(self.mouse_button, self.mouse_button))
            if self.drag_modifier != "none":
                parts.append(f"{self.drag_modifier}+drag")
            self.status.append(" + ".join(parts) if hook else "mouse hook failed")
        message = wt.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                self.events.put("trigger")
        if hook:
            user32.UnhookWindowsHookEx(hook)
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.join(timeout=1.5)


# =========================================================================== theme

THEMES = {
    "Midnight": {"dark": True, "bg": "#101216", "surface": "#15181d", "surface2": "#1d2128",
                 "border": "#262a32", "text": "#e8eaef", "muted": "#8a909b", "accent": "#7c9cff"},
    "Graphite": {"dark": True, "bg": "#131315", "surface": "#1a1a1d", "surface2": "#232327",
                 "border": "#303036", "text": "#ececf1", "muted": "#9a9aa6", "accent": "#a78bfa"},
    "Nord": {"dark": True, "bg": "#2b303b", "surface": "#323846", "surface2": "#3b4252",
             "border": "#475066", "text": "#eceff4", "muted": "#a3adc2", "accent": "#88c0d0"},
    "Rose Pine": {"dark": True, "bg": "#191724", "surface": "#1f1d2e", "surface2": "#26233a",
                  "border": "#393552", "text": "#e0def4", "muted": "#908caa", "accent": "#ebbcba"},
    "Forest": {"dark": True, "bg": "#0f1512", "surface": "#151d19", "surface2": "#1c2721",
               "border": "#29382f", "text": "#e3ede6", "muted": "#8fa596", "accent": "#5fd39a"},
    "Paper": {"dark": False, "bg": "#f4f5f7", "surface": "#ffffff", "surface2": "#eef0f3",
              "border": "#dfe2e8", "text": "#1c2027", "muted": "#6b7280", "accent": "#2563eb"},
    "Sand": {"dark": False, "bg": "#f5f0e8", "surface": "#fffdf9", "surface2": "#efe8dc",
             "border": "#e0d6c4", "text": "#2b261f", "muted": "#857a69", "accent": "#c2410c"},
}
ACCENT_PRESETS = ["#7c9cff", "#a78bfa", "#f472b6", "#fb7185", "#f59e0b", "#5fd39a", "#22d3ee", "#2563eb"]
KIND_COLORS = {"builtin": None, "skill": "#60a5fa", "agent": "#c084fc", "command": "#34d399", "rules": "#fbbf24"}
FONT_CHOICES = ["Segoe UI", "Segoe UI Variable Text", "Inter", "Roboto", "Calibri", "Arial", "Verdana", "Bahnschrift"]
MONO_CHOICES = ["Cascadia Code", "Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New"]


def hex_to_rgb(color):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def blend(color_a, color_b, amount):
    a = hex_to_rgb(color_a)
    b = hex_to_rgb(color_b)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * amount for i in range(3)))


def luminance(color):
    red, green, blue = (v / 255 for v in hex_to_rgb(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def build_theme(ui):
    theme = dict(THEMES.get(ui.get("theme"), THEMES["Midnight"]))
    if ui.get("accent"):
        theme["accent"] = ui["accent"]
    accent = theme["accent"]
    theme["on_accent"] = "#0b0d12" if luminance(accent) > 0.62 else "#ffffff"
    theme["accent_soft"] = blend(theme["surface"], accent, 0.16 if theme["dark"] else 0.10)
    theme["accent_hover"] = blend(accent, "#ffffff", 0.12)
    theme["hover"] = blend(theme["surface2"], theme["text"], 0.06)
    theme["selection"] = blend(theme["bg"], theme["text"], 0.085 if theme["dark"] else 0.06)
    kinds = {}
    for kind, color in KIND_COLORS.items():
        color = color or accent
        if not theme["dark"]:
            color = blend(color, "#000000", 0.30)
        kinds[kind] = (color, blend(theme["surface"], color, 0.16 if theme["dark"] else 0.12))
    theme["kinds"] = kinds
    return theme


# =========================================================================== UI widgets

DND_AVAILABLE = False


def start_ui_imports():
    global tk, ttk, tkfont, filedialog, messagebox, colorchooser
    global DND_AVAILABLE, TkinterDnD, DND_FILES, DND_TEXT
    import tkinter as tk
    from tkinter import ttk
    from tkinter import font as tkfont
    from tkinter import filedialog, messagebox, colorchooser
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES, DND_TEXT
        DND_AVAILABLE = True
    except Exception:
        DND_AVAILABLE = False


class FlatButton:
    """Label-based button with hover state. kind: primary | ghost | subtle."""

    def __init__(self, parent, text, command, theme, font, kind="ghost"):
        self.theme = theme
        self.kind = kind
        self.command = command
        colors = self._colors()
        self.widget = tk.Label(
            parent, text=text, font=font, cursor="hand2",
            bg=colors[0], fg=colors[1], padx=14, pady=6, bd=0,
        )
        self.widget.bind("<Enter>", lambda e: self.widget.config(bg=self._colors()[2]))
        self.widget.bind("<Leave>", lambda e: self.widget.config(bg=self._colors()[0]))
        self.widget.bind("<Button-1>", lambda e: self.command())

    def _colors(self):
        theme = self.theme
        if self.kind == "primary":
            return theme["accent"], theme["on_accent"], theme["accent_hover"]
        if self.kind == "subtle":
            return theme["bg"], theme["muted"], theme["surface2"]
        return theme["surface2"], theme["text"], theme["hover"]

    def pack(self, **kwargs):
        self.widget.pack(**kwargs)
        return self

    def grid(self, **kwargs):
        self.widget.grid(**kwargs)
        return self


class InputBox:
    """Flat entry inside a bordered frame, with focus ring and placeholder overlay."""

    def __init__(self, parent, theme, font, placeholder="", icon=None, show=None, muted_font=None):
        self.theme = theme
        self.frame = tk.Frame(parent, bg=theme["surface2"], highlightthickness=1,
                              highlightbackground=theme["border"], highlightcolor=theme["accent"])
        if icon:
            tk.Label(self.frame, text=icon, bg=theme["surface2"], fg=theme["muted"],
                     font=font).pack(side="left", padx=(10, 0))
        self.var = tk.StringVar()
        self.entry = tk.Entry(
            self.frame, textvariable=self.var, font=font, relief="flat", bd=0,
            bg=theme["surface2"], fg=theme["text"], insertbackground=theme["text"],
            selectbackground=theme["selection"], selectforeground=theme["text"],
            show=show or "",
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        self.placeholder = tk.Label(self.frame, text=placeholder, bg=theme["surface2"],
                                    fg=theme["muted"], font=muted_font or font, cursor="xterm")
        self.placeholder.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.var.trace_add("write", lambda *_: self._sync())
        self.entry.bind("<FocusIn>", lambda e: self.frame.config(highlightbackground=theme["accent"]), add="+")
        self.entry.bind("<FocusOut>", lambda e: self.frame.config(highlightbackground=theme["border"]), add="+")
        self.frame.after(10, self._sync)

    def _sync(self):
        if self.var.get():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(in_=self.entry, x=0, rely=0.5, anchor="w")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


class TextBox:
    """Multi-line text with border, focus ring and placeholder."""

    def __init__(self, parent, theme, font, height=4, placeholder=""):
        self.frame = tk.Frame(parent, bg=theme["surface2"], highlightthickness=1,
                              highlightbackground=theme["border"])
        self.text = tk.Text(
            self.frame, height=height, wrap="word", font=font, relief="flat", bd=0,
            bg=theme["surface2"], fg=theme["text"], insertbackground=theme["text"],
            selectbackground=theme["selection"], selectforeground=theme["text"],
            padx=10, pady=8, undo=True,
        )
        self.text.pack(fill="both", expand=True)
        self.placeholder = tk.Label(self.frame, text=placeholder, bg=theme["surface2"],
                                    fg=theme["muted"], font=font, cursor="xterm")
        self.placeholder.bind("<Button-1>", lambda e: self.text.focus_set())
        self.text.bind("<KeyRelease>", lambda e: self._sync(), add="+")
        self.text.bind("<FocusIn>", lambda e: self.frame.config(highlightbackground=theme["accent"]), add="+")
        self.text.bind("<FocusOut>", lambda e: self.frame.config(highlightbackground=theme["border"]), add="+")
        self.frame.after(10, self._sync)

    def _sync(self):
        if self.get().strip():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=12, y=8)

    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, value):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self._sync()


def rounded_rect(canvas, x0, y0, x1, y1, radius, **kwargs):
    radius = max(0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    points = [
        x0 + radius, y0, x1 - radius, y0, x1, y0, x1, y0 + radius,
        x1, y1 - radius, x1, y1, x1 - radius, y1, x0 + radius, y1,
        x0, y1, x0, y1 - radius, x0, y0 + radius, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


GLYPH = {
    "search": "\uE721", "skill": "\uE945", "agent": "\uE99A", "command": "\uE756", "rules": "\uE8A5",
    "builtin": "\uE8BD", "run": "\uE768", "star": "\uE734", "starfill": "\uE735", "open": "\uE8E5",
    "folder": "\uE8B7", "import": "\uE896", "add": "\uE710", "library": "\uE8F1", "settings": "\uE713",
    "refresh": "\uE72C", "power": "\uE7E8", "copy": "\uE8C8", "close": "\uE711", "chevron": "\uE70D",
    "edit": "\uE70F", "stop": "\uE71A", "check": "\uE73E", "model": "\uE950", "send": "\uE724",
}
KIND_GLYPH = {"builtin": GLYPH["builtin"], "skill": GLYPH["skill"], "agent": GLYPH["agent"],
              "command": GLYPH["command"], "rules": GLYPH["rules"]}
KIND_NAME = {"builtin": "Chat", "skill": "Skill", "agent": "Agent", "command": "Command", "rules": "Rules"}
WINDOW_KEY = "#020304"
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010


class RoundedWindow:
    """Borderless window with drawn rounded corners and a hairline border (works on Windows 10)."""

    def __init__(self, app, title, radius=14, header=None, on_close=None):
        self.app = app
        theme = app.theme
        self.radius = int(radius * app.scale)
        self.inset = max(4, int(self.radius * 0.36))
        self.on_close = on_close
        self.window = tk.Toplevel(app.root)
        self.window.withdraw()
        self.window.title(title)
        self.window.overrideredirect(True)
        self.window.configure(bg=WINDOW_KEY)
        self.window.attributes("-transparentcolor", WINDOW_KEY)
        self.window.attributes("-alpha", float(app.config["ui"].get("opacity", 1.0)))
        self.canvas = tk.Canvas(self.window, bg=WINDOW_KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=theme["bg"])
        self.body_id = self.canvas.create_window(self.inset, self.inset, anchor="nw", window=self.body)
        self.canvas.bind("<Configure>", self._layout)
        self._drag = None
        self._resize = None
        if header is not None:
            self._make_header(header)

    def hwnd(self):
        return int(self.window.wm_frame(), 16)

    def _layout(self, event):
        theme = self.app.theme
        self.canvas.delete("frame")
        rounded_rect(self.canvas, 0, 0, event.width - 1, event.height - 1, self.radius,
                     fill=theme["bg"], outline=theme["border"], tags="frame")
        self.canvas.tag_lower("frame")
        self.canvas.coords(self.body_id, self.inset, self.inset)
        self.canvas.itemconfigure(self.body_id, width=max(1, event.width - 2 * self.inset),
                                  height=max(1, event.height - 2 * self.inset))

    def _make_header(self, title):
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        bar = tk.Frame(self.body, bg=theme["bg"])
        bar.pack(fill="x", padx=(int(14 * scale), int(6 * scale)), pady=(int(6 * scale), int(4 * scale)))
        label = tk.Label(bar, text=title, bg=theme["bg"], fg=theme["text"], font=fonts["semibold"])
        label.pack(side="left")
        IconButton(bar, GLYPH["close"], self.close, self.app).pack(side="right")
        self.make_draggable(bar)
        self.make_draggable(label)
        tk.Frame(self.body, bg=theme["border"], height=1).pack(fill="x")

    def close(self):
        if self.on_close:
            self.on_close()
        elif self.window.winfo_exists():
            self.window.destroy()

    def make_draggable(self, widget):
        widget.bind("<ButtonPress-1>", self._drag_start, add="+")
        widget.bind("<B1-Motion>", self._drag_move, add="+")

    def _drag_start(self, event):
        self._drag = (event.x_root - self.window.winfo_rootx(), event.y_root - self.window.winfo_rooty())

    def _drag_move(self, event):
        if self._drag:
            user32.SetWindowPos(self.hwnd(), None, event.x_root - self._drag[0], event.y_root - self._drag[1],
                                0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def add_resize_grip(self, min_width, min_height):
        theme = self.app.theme
        scale = self.app.scale
        size = int(16 * scale)
        grip = tk.Canvas(self.body, width=size, height=size, bg=self.body.cget("bg"), highlightthickness=0,
                         bd=0, cursor="size_nw_se")
        dot = max(2, int(2 * scale))
        for dx, dy in ((12, 12), (8, 12), (12, 8), (4, 12), (8, 8), (12, 4)):
            x, y = int(dx * scale), int(dy * scale)
            grip.create_oval(x - dot / 2, y - dot / 2, x + dot / 2, y + dot / 2, fill=theme["muted"], outline="")
        grip.place(relx=1.0, rely=1.0, anchor="se")
        tk.Misc.lift(grip)

        def start(event):
            self._resize = (event.x_root, event.y_root, self.window.winfo_width(), self.window.winfo_height())

        def move(event):
            if not self._resize:
                return
            x0, y0, width, height = self._resize
            new_width = max(int(min_width * scale), width + event.x_root - x0)
            new_height = max(int(min_height * scale), height + event.y_root - y0)
            user32.SetWindowPos(self.hwnd(), None, 0, 0, new_width, new_height,
                                SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

        grip.bind("<ButtonPress-1>", start)
        grip.bind("<B1-Motion>", move)
        return grip

    def present(self, width, height):
        scale = self.app.scale
        width = int(width * scale)
        height = int(height * scale)
        x, y = self.app.root.winfo_pointerxy()
        left, top, right, bottom = work_area_at(x, y)
        width = min(width, right - left - 40)
        height = min(height, bottom - top - 40)
        pos_x = left + (right - left - width) // 2
        pos_y = top + max(20, int((bottom - top - height) * 0.26))
        self.present_pixels(width, height, pos_x, pos_y)

    def present_pixels(self, width, height, x, y, focus=True):
        self.window.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
        self.window.attributes("-topmost", True)
        self.window.deiconify()
        self.window.update_idletasks()
        if focus:
            force_foreground(self.hwnd())


class IconButton:
    def __init__(self, parent, glyph, command, app, size="icon_small"):
        theme = app.theme
        background = parent.cget("bg")
        hover = blend(background, theme["text"], 0.09)
        self.widget = tk.Label(parent, text=glyph, font=app.fonts[size], bg=background, fg=theme["muted"],
                               padx=int(8 * app.scale), pady=int(5 * app.scale), cursor="hand2")
        self.widget.bind("<Enter>", lambda e: self.widget.config(bg=hover, fg=theme["text"]))
        self.widget.bind("<Leave>", lambda e: self.widget.config(bg=background, fg=theme["muted"]))
        self.widget.bind("<Button-1>", lambda e: command())

    def pack(self, **kwargs):
        self.widget.pack(**kwargs)
        return self


class FlatInput:
    """Borderless single-line input with a leading icon and placeholder."""

    def __init__(self, parent, app, placeholder, glyph=None, font_key="base", icon_key="icon_small"):
        theme = app.theme
        fonts = app.fonts
        background = parent.cget("bg")
        self.frame = tk.Frame(parent, bg=background)
        if glyph:
            tk.Label(self.frame, text=glyph, font=fonts[icon_key], bg=background,
                     fg=theme["muted"]).pack(side="left", padx=(0, int(10 * app.scale)))
        self.var = tk.StringVar()
        self.entry = tk.Entry(self.frame, textvariable=self.var, font=fonts[font_key], relief="flat", bd=0,
                              bg=background, fg=theme["text"], insertbackground=theme["accent"], insertwidth=2,
                              selectbackground=theme["selection"], selectforeground=theme["text"],
                              highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, ipady=int(2 * app.scale))
        self.placeholder = tk.Label(self.frame, text=placeholder, font=fonts[font_key], bg=background,
                                    fg=theme["muted"], cursor="xterm")
        self.placeholder.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.var.trace_add("write", lambda *_: self._sync())
        self.frame.after(10, self._sync)

    def _sync(self):
        if self.var.get():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(in_=self.entry, x=0, rely=0.5, anchor="w")

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)


def draw_keycaps(canvas, right_x, center_y, keys, app):
    theme = app.theme
    fonts = app.fonts
    scale = app.scale
    height = int(18 * scale)
    gap = int(4 * scale)
    x = right_x
    for key in reversed(keys):
        width = max(height, fonts["keycap"].measure(key) + int(10 * scale))
        rounded_rect(canvas, x - width, center_y - height / 2, x, center_y + height / 2, int(4 * scale),
                     fill=theme["surface2"], outline=theme["border"])
        canvas.create_text(x - width / 2, center_y, text=key, font=fonts["keycap"], fill=theme["muted"])
        x -= width + gap
    return x + gap


class KeyHint:
    """Clickable label with keyboard-shortcut key caps (action bar item)."""

    def __init__(self, parent, app, label, keys, command, emphasis=False):
        self.app = app
        self.label = label
        self.keys = keys
        self.emphasis = emphasis
        self.background = parent.cget("bg")
        self.hover = False
        self.canvas = tk.Canvas(parent, bg=self.background, highlightthickness=0, bd=0, cursor="hand2",
                                height=int(26 * app.scale))
        self.canvas.bind("<Enter>", lambda e: self._set_hover(True))
        self.canvas.bind("<Leave>", lambda e: self._set_hover(False))
        self.canvas.bind("<Button-1>", lambda e: command())
        self.draw()

    def _set_hover(self, value):
        self.hover = value
        self.draw()

    def draw(self):
        canvas = self.canvas
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        canvas.delete("all")
        label_font = fonts["small_bold"] if self.emphasis else fonts["small"]
        caps = sum(max(int(18 * scale), fonts["keycap"].measure(k) + int(10 * scale)) for k in self.keys)
        caps += int(4 * scale) * (len(self.keys) - 1)
        width = int(10 * scale + label_font.measure(self.label) + 8 * scale + caps + 6 * scale)
        height = int(26 * scale)
        canvas.configure(width=width)
        if self.hover:
            rounded_rect(canvas, 0, 1, width, height - 1, int(6 * scale),
                         fill=blend(self.background, theme["text"], 0.07), outline="")
        color = theme["text"] if (self.emphasis or self.hover) else theme["muted"]
        canvas.create_text(int(10 * scale), height / 2, anchor="w", text=self.label, font=label_font, fill=color)
        draw_keycaps(canvas, width - int(6 * scale), height / 2, self.keys, self.app)


class ModelChip:
    def __init__(self, parent, app, variable, command):
        self.app = app
        self.variable = variable
        self.background = parent.cget("bg")
        self.hover = False
        self.canvas = tk.Canvas(parent, bg=self.background, highlightthickness=0, bd=0, cursor="hand2",
                                height=int(30 * app.scale))
        self.canvas.bind("<Enter>", lambda e: self._set_hover(True))
        self.canvas.bind("<Leave>", lambda e: self._set_hover(False))
        self.canvas.bind("<Button-1>", lambda e: command())
        variable.trace_add("write", lambda *_: self.draw())
        self.draw()

    def _set_hover(self, value):
        self.hover = value
        self.draw()

    def draw(self):
        canvas = self.canvas
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        canvas.delete("all")
        value = self.variable.get()
        provider, _, model = value.partition(":")
        label = (model or provider) if value else "Choose model"
        if len(label) > 26:
            label = label[:25] + "\u2026"
        height = int(30 * scale)
        dot = int(7 * scale)
        width = int(12 * scale + dot + 8 * scale + fonts["small"].measure(label) + 8 * scale
                    + fonts["icon_small"].measure(GLYPH["chevron"]) + 12 * scale)
        canvas.configure(width=width)
        fill = blend(theme["surface2"], theme["text"], 0.05) if self.hover else theme["surface2"]
        rounded_rect(canvas, 1, 1, width - 1, height - 1, height / 2 - 1, fill=fill, outline=theme["border"])
        local = provider in ("ollama", "lmstudio")
        dot_color = "#34d399" if local else (theme["accent"] if value else theme["muted"])
        x = int(12 * scale)
        canvas.create_oval(x, height / 2 - dot / 2, x + dot, height / 2 + dot / 2, fill=dot_color, outline="")
        x += dot + int(8 * scale)
        canvas.create_text(x, height / 2, anchor="w", text=label, font=fonts["small"], fill=theme["text"])
        canvas.create_text(width - int(12 * scale), height / 2 + 1, anchor="e", text=GLYPH["chevron"],
                           font=fonts["icon_small"], fill=theme["muted"])


def icon_tile(parent, app, kind, size=28):
    theme = app.theme
    scale = app.scale
    pixels = int(size * scale)
    canvas = tk.Canvas(parent, width=pixels, height=pixels, bg=parent.cget("bg"), highlightthickness=0, bd=0)
    color, soft = theme["kinds"][kind]
    rounded_rect(canvas, 0, 0, pixels, pixels, int(pixels * 0.26), fill=soft, outline="")
    canvas.create_text(pixels / 2, pixels / 2, text=KIND_GLYPH[kind],
                       font=app.fonts["icon"] if size >= 32 else app.fonts["icon_tile"], fill=color)
    return canvas


def logo_tile(parent, app, size=20):
    theme = app.theme
    pixels = int(size * app.scale)
    canvas = tk.Canvas(parent, width=pixels, height=pixels, bg=parent.cget("bg"), highlightthickness=0, bd=0)
    rounded_rect(canvas, 0, 0, pixels, pixels, int(pixels * 0.28), fill=theme["accent"], outline="")
    canvas.create_text(pixels / 2, pixels / 2, text=GLYPH["skill"], font=app.fonts["icon_small"],
                       fill=theme["on_accent"])
    return canvas


class ItemList:
    """Canvas list with section headers, icon tiles, inline subtitles and hover selection."""

    def __init__(self, parent, app, on_activate, on_select):
        self.app = app
        self.on_activate = on_activate
        self.on_select = on_select
        self.canvas = tk.Canvas(parent, bg=app.theme["bg"], highlightthickness=0, bd=0)
        self.items = []
        self.rows = []
        self.row_tops = []
        self.item_rows = []
        self.total_height = 0
        self.index = 0
        self.truncate_cache = {}
        scale = app.scale
        self.item_height = int(44 * scale)
        self.header_height = int(30 * scale)
        self.show_descriptions = app.config["ui"].get("show_descriptions", True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<Double-Button-1>", lambda e: self.on_activate())
        self.canvas.bind("<Motion>", self._hover)

    def set_items(self, items, sections=None):
        rows = []
        if sections:
            for title, group in sections:
                if group:
                    rows.append(("header", title))
                    rows.extend(("item", item) for item in group)
        else:
            rows = [("item", item) for item in (items or [])]
        self.rows = rows
        self.items = [row[1] for row in rows if row[0] == "item"]
        self.item_rows = [number for number, row in enumerate(rows) if row[0] == "item"]
        tops = []
        y = int(4 * self.app.scale)
        for kind, _ in rows:
            tops.append(y)
            y += self.header_height if kind == "header" else self.item_height
        self.row_tops = tops
        self.total_height = y + int(6 * self.app.scale)
        self.index = 0
        self.redraw()
        self.canvas.yview_moveto(0)
        self.on_select(self.current())

    def current(self):
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def _row_at(self, event_y):
        y = self.canvas.canvasy(event_y)
        number = bisect.bisect_right(self.row_tops, y) - 1
        if 0 <= number < len(self.rows):
            return number
        return None

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120) * 3, "units")
        return "break"

    def _click(self, event):
        number = self._row_at(event.y)
        if number is not None and number in self.item_rows:
            self.select(self.item_rows.index(number), scroll=False)

    def _hover(self, event):
        number = self._row_at(event.y)
        if number is not None and number in self.item_rows:
            index = self.item_rows.index(number)
            if index != self.index:
                self.select(index, scroll=False)

    def truncate(self, font_key, text, width):
        cache_key = (font_key, text, int(width))
        if cache_key in self.truncate_cache:
            return self.truncate_cache[cache_key]
        font = self.app.fonts[font_key]
        result = text
        if font.measure(text) > width:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if font.measure(text[:middle] + "\u2026") <= width:
                    low = middle
                else:
                    high = middle - 1
            result = text[:low].rstrip() + "\u2026"
        self.truncate_cache[cache_key] = result
        return result

    def redraw(self):
        canvas = self.canvas
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        favorites = set(self.app.state.get("favorites", []))
        for number, (kind, value) in enumerate(self.rows):
            top = self.row_tops[number]
            if kind == "header":
                canvas.create_text(int(16 * scale), top + self.header_height - int(8 * scale), anchor="sw",
                                   text=value, font=fonts["section"], fill=theme["muted"])
                continue
            item = value
            center = top + self.item_height / 2
            tile = int(28 * scale)
            x0 = int(12 * scale)
            color, soft = theme["kinds"][item.kind]
            rounded_rect(canvas, x0, center - tile / 2, x0 + tile, center + tile / 2, int(7 * scale),
                         fill=soft, outline="")
            canvas.create_text(x0 + tile / 2, center, text=KIND_GLYPH[item.kind], font=fonts["icon_tile"],
                               fill=color)
            x_title = x0 + tile + int(12 * scale)
            right = width - int(16 * scale)
            if item.source:
                canvas.create_text(right, center, anchor="e", text=item.source, font=fonts["small"],
                                   fill=theme["muted"])
                right -= fonts["small"].measure(item.source) + int(12 * scale)
            if item.key in favorites:
                canvas.create_text(right, center, anchor="e", text=GLYPH["starfill"], font=fonts["icon_small"],
                                   fill=theme["accent"])
                right -= int(22 * scale)
            name = self.truncate("semibold", item.name, max(40, right - x_title))
            canvas.create_text(x_title, center, anchor="w", text=name, font=fonts["semibold"], fill=theme["text"])
            if self.show_descriptions and item.description:
                x_sub = x_title + fonts["semibold"].measure(name) + int(10 * scale)
                room = right - x_sub
                if room > 60:
                    description = self.truncate("small", item.description.replace("\n", " "), room)
                    canvas.create_text(x_sub, center, anchor="w", text=description, font=fonts["small"],
                                       fill=theme["muted"])
        canvas.configure(scrollregion=(0, 0, width, max(self.total_height, 1)),
                         yscrollincrement=max(1, self.item_height // 3))
        self._draw_selection()

    def _draw_selection(self):
        canvas = self.canvas
        theme = self.app.theme
        scale = self.app.scale
        canvas.delete("sel")
        width = max(canvas.winfo_width(), 200)
        if not self.items:
            canvas.create_text(width / 2, int(70 * scale), text="No results", font=self.app.fonts["semibold"],
                               fill=theme["text"], tags="sel")
            canvas.create_text(width / 2, int(94 * scale), text="Try another search or tab",
                               font=self.app.fonts["small"], fill=theme["muted"], tags="sel")
            return
        top = self.row_tops[self.item_rows[self.index]]
        rounded_rect(canvas, int(4 * scale), top + 1, width - int(4 * scale), top + self.item_height - 1,
                     int(9 * scale), fill=theme["selection"], outline="", tags="sel")
        canvas.tag_lower("sel")

    def select(self, index, scroll=True):
        if not self.items:
            return
        self.index = max(0, min(len(self.items) - 1, index))
        self._draw_selection()
        if scroll:
            number = self.item_rows[self.index]
            top = self.row_tops[number]
            if self.index == 0:
                top = 0
            bottom = self.row_tops[number] + self.item_height
            view_top = self.canvas.canvasy(0)
            view_height = self.canvas.winfo_height()
            total = max(1, self.total_height)
            if top < view_top:
                self.canvas.yview_moveto(top / total)
            elif bottom > view_top + view_height:
                self.canvas.yview_moveto((bottom - view_height + int(6 * self.app.scale)) / total)
        self.on_select(self.current())

    def move(self, delta):
        self.select(self.index + delta)
        return "break"


class Popover:
    """Floating, searchable action list (Ctrl+K panel, model picker)."""

    def __init__(self, app, entries, anchor, align="bottom-right", width=360, placeholder="Search actions",
                 on_close=None):
        self.app = app
        theme = app.theme
        fonts = app.fonts
        scale = app.scale
        self.entries = entries
        self.on_close = on_close
        self.closed = False
        self.rounded = RoundedWindow(app, f"{APP_NAME} Actions", radius=12)
        self.window = self.rounded.window
        body = self.rounded.body
        self.search = FlatInput(body, app, placeholder, GLYPH["search"], font_key="base", icon_key="icon_small")
        self.search.frame.pack(fill="x", padx=int(12 * scale), pady=(int(10 * scale), int(9 * scale)))
        tk.Frame(body, bg=theme["border"], height=1).pack(fill="x")
        self.canvas = tk.Canvas(body, bg=theme["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=int(4 * scale), pady=int(4 * scale))
        self.row_height = int(34 * scale)
        self.separator_height = int(9 * scale)
        self.visible = []
        self.selectable = []
        self.row_tops = []
        self.index = 0
        self._filter()
        rows = sum(self.separator_height if e == "sep" else self.row_height for e in entries[:14])
        search_height = fonts["base"].metrics("linespace") + int(24 * scale)
        height = search_height + rows + int(12 * scale) + 2 * self.rounded.inset
        width_px = int(width * scale)
        anchor_x, anchor_y = anchor
        x = anchor_x - width_px
        y = anchor_y - height if align == "bottom-right" else anchor_y
        left, top, right, bottom = work_area_at(int(anchor_x), int(anchor_y))
        x = max(left + 8, min(x, right - width_px - 8))
        y = max(top + 8, min(y, bottom - height - 8))
        self.search.var.trace_add("write", lambda *_: self._filter())
        self.search.entry.bind("<Down>", lambda e: self._move(1))
        self.search.entry.bind("<Up>", lambda e: self._move(-1))
        self.search.entry.bind("<Return>", lambda e: self._activate())
        self.window.bind("<Escape>", lambda e: self.close())
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Button-1>", lambda e: (self._hover(e), self._activate()))
        self.window.bind("<FocusOut>", lambda e: self.window.after(150, self._check_focus), add="+")
        self.canvas.bind("<Configure>", lambda e: self._draw())
        app.active_popover = self
        self.rounded.present_pixels(width_px, height, x, y)
        self.search.entry.focus_force()

    def _filter(self):
        query = self.search.get().strip().lower()
        if query:
            visible = [e for e in self.entries if e != "sep"
                       and (query in e["label"].lower() or query in e.get("hint", "").lower())]
        else:
            visible = []
            for entry in self.entries:
                if entry == "sep" and (not visible or visible[-1] == "sep"):
                    continue
                visible.append(entry)
            while visible and visible[-1] == "sep":
                visible.pop()
        self.visible = visible
        self.selectable = [n for n, e in enumerate(visible) if e != "sep"]
        self.index = 0
        self._draw()

    def _draw(self):
        canvas = self.canvas
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        canvas.delete("all")
        width = max(canvas.winfo_width(), 200)
        y = 0
        self.row_tops = []
        selected_row = self.selectable[self.index] if self.selectable else None
        for number, entry in enumerate(self.visible):
            self.row_tops.append(y)
            if entry == "sep":
                middle = y + self.separator_height / 2
                canvas.create_line(int(10 * scale), middle, width - int(10 * scale), middle, fill=theme["border"])
                y += self.separator_height
                continue
            selected = number == selected_row
            center = y + self.row_height / 2
            if selected:
                rounded_rect(canvas, 2, y + 1, width - 2, y + self.row_height - 1, int(7 * scale),
                             fill=theme["selection"], outline="")
            canvas.create_text(int(16 * scale), center, text=entry.get("glyph", ""), font=fonts["icon_small"],
                               fill=theme["accent"] if selected else theme["muted"])
            canvas.create_text(int(40 * scale), center, anchor="w", text=entry["label"], font=fonts["base"],
                               fill=theme["text"])
            if entry.get("keys"):
                draw_keycaps(canvas, width - int(10 * scale), center, entry["keys"], self.app)
            elif entry.get("hint"):
                canvas.create_text(width - int(12 * scale), center, anchor="e", text=entry["hint"],
                                   font=fonts["small"], fill=theme["muted"])
            y += self.row_height
        if not self.visible:
            canvas.create_text(width / 2, int(30 * scale), text="No matching actions", font=fonts["small"],
                               fill=theme["muted"])
        canvas.configure(scrollregion=(0, 0, width, max(y, 1)))

    def _move(self, delta):
        if self.selectable:
            self.index = (self.index + delta) % len(self.selectable)
            self._draw()
            top = self.row_tops[self.selectable[self.index]]
            total = max(1, self.row_tops[-1] + self.row_height)
            view_top = self.canvas.canvasy(0)
            view_height = self.canvas.winfo_height()
            if top < view_top or top + self.row_height > view_top + view_height:
                self.canvas.yview_moveto(max(0, top - view_height / 2) / total)
        return "break"

    def _hover(self, event):
        y = self.canvas.canvasy(event.y)
        number = bisect.bisect_right(self.row_tops, y) - 1
        if number in self.selectable:
            index = self.selectable.index(number)
            if index != self.index:
                self.index = index
                self._draw()

    def _activate(self):
        if not self.selectable:
            return "break"
        entry = self.visible[self.selectable[self.index]]
        self.close()
        self.app.root.after(30, entry["action"])
        return "break"

    def _check_focus(self):
        if self.closed:
            return
        focus = self.app.root.focus_get()
        if focus is None or not str(focus).startswith(str(self.window)):
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.window.winfo_exists():
            self.window.destroy()
        if getattr(self.app, "active_popover", None) is self:
            self.app.active_popover = None
        if self.on_close:
            self.on_close()


def insert_markdown(text, content, extra_tag=None):
    """Very small markdown renderer: headings, bullets, numbers, **bold**, `code`, fenced blocks."""
    in_code = False

    def tags(*names):
        return tuple(name for name in names + (extra_tag,) if name)

    def inline(line, base=None):
        for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                text.insert("end", part[2:-2], tags(base, "bold"))
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                text.insert("end", part[1:-1], tags(base, "code"))
            else:
                text.insert("end", part, tags(base))

    lines = content.split("\n")
    for number, line in enumerate(lines):
        end = "\n" if number < len(lines) - 1 else ""
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            text.insert("end", line + "\n", tags("codeblock"))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        bullet = re.match(r"^\s*[-*+]\s+(.*)", line)
        numbered = re.match(r"^\s*(\d+)[.)]\s+(.*)", line)
        if heading:
            level = len(heading.group(1))
            inline(heading.group(2), "h1" if level == 1 else "h2" if level == 2 else "h3")
        elif re.fullmatch(r"[-*_]{3,}", stripped):
            text.insert("end", "", tags())
        elif bullet:
            text.insert("end", "\u2022  ", tags("bullet", "bulletmark"))
            inline(bullet.group(1), "bullet")
        elif numbered:
            text.insert("end", numbered.group(1) + ".  ", tags("bullet", "bulletmark"))
            inline(numbered.group(2), "bullet")
        else:
            inline(line)
        text.insert("end", end, tags())


def make_icon(accent):
    size = 32
    image = tk.PhotoImage(width=size, height=size)
    radius = 8
    for y in range(size):
        inset = 0
        if y < radius:
            inset = radius - int((radius ** 2 - (radius - y - 0.5) ** 2) ** 0.5)
        elif y >= size - radius:
            inset = radius - int((radius ** 2 - (y - (size - radius) + 0.5) ** 2) ** 0.5)
        image.put(accent, to=(inset, y, size - inset, y + 1))
    image.put("#ffffff", to=(12, 6, 20, 20))
    image.put(accent, to=(15, 8, 17, 12))
    image.put("#ffffff", to=(10, 22, 22, 25))
    return image



DONUT_KEY = "#010203"


def parse_drop_data(tk_app, data):
    """tkdnd drop data -> payload dict with either files or text."""
    data = data or ""
    try:
        parts = list(tk_app.tk.splitlist(data))
    except Exception:
        parts = []
    if parts and all(os.path.isabs(p) and os.path.exists(p) for p in parts):
        return {"text": "", "files": parts}
    return {"text": data, "files": []}


class Donut:
    """Filee-style radial menu: appears at the cursor during modifier+drag; drop on a slice to run it."""

    def __init__(self, app):
        self.app = app
        scale = app.scale
        self.outer = int(150 * scale)
        self.inner = int(66 * scale)
        self.hub = int(46 * scale)
        self.per_face = 8
        self.width = max(2 * self.outer + int(24 * scale), int(420 * scale))
        self.caption_top = 2 * self.outer + int(24 * scale)
        self.height = self.caption_top + int(62 * scale)
        self.cx = self.width / 2
        self.cy = self.outer + int(12 * scale)
        self.window = tk.Toplevel(app.root)
        self.window.title(f"{APP_NAME} Donut")
        self.window.overrideredirect(True)
        self.window.configure(bg=DONUT_KEY)
        self.window.attributes("-topmost", True)
        self.window.attributes("-transparentcolor", DONUT_KEY)
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height, bg=DONUT_KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.window.geometry(f"{self.width}x{self.height}+-32000+-32000")
        self.window.update_idletasks()
        self.hwnd = int(self.window.wm_frame(), 16)
        parent = user32.GetParent(self.hwnd)
        if parent:
            self.hwnd = parent
        style = user32.GetWindowLongW(self.hwnd, -20)
        user32.SetWindowLongW(self.hwnd, -20, style | 0x08000000 | 0x00000080)   # NOACTIVATE | TOOLWINDOW
        self.visible = False
        self.items = []
        self.face = 0
        self.hover = None
        self.origin = (-32000, -32000)
        self.dropped = False
        self.target_hwnd = None
        self.tab_down = False
        self.shown_at = 0.0
        self.canvas.drop_target_register(DND_FILES, DND_TEXT)
        self.canvas.dnd_bind("<<DropEnter>>", self._on_position)
        self.canvas.dnd_bind("<<DropPosition>>", self._on_position)
        self.canvas.dnd_bind("<<Drop>>", self._on_drop)

    @property
    def faces(self):
        return max(1, math.ceil(len(self.items) / self.per_face))

    def face_items(self):
        start = self.face * self.per_face
        return self.items[start:start + self.per_face]

    def show(self, x, y, target_hwnd):
        self.items = self.app.donut_items()
        self.face = 0
        self.hover = None
        self.dropped = False
        self.target_hwnd = target_hwnd
        left, top, right, bottom = work_area_at(int(x), int(y))
        origin_x = int(min(max(x - self.cx, left), right - self.width))
        origin_y = int(min(max(y - self.cy, top), bottom - self.height))
        self.origin = (origin_x, origin_y)
        self.draw()
        self._move(origin_x, origin_y)
        self.visible = True
        self.shown_at = time.time()
        if self.app.listener:
            self.app.listener.donut_visible = True
        self.window.after(30, self._tick)

    def hide(self):
        self.visible = False
        if self.app.listener:
            self.app.listener.donut_visible = False
        self._move(-32000, -32000)

    def _move(self, x, y):
        # HWND_TOPMOST, SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        user32.SetWindowPos(self.hwnd, wt.HWND(-1), int(x), int(y), 0, 0, 0x0001 | 0x0010 | 0x0040)

    def hide_if_idle(self):
        if self.visible and not self.dropped:
            self.hide()

    def flip(self, delta):
        step = 1 if delta < 0 else -1
        self.face = (self.face + step) % self.faces
        self.hover = None
        self.draw()

    def hit(self, screen_x, screen_y):
        dx = screen_x - self.origin[0] - self.cx
        dy = self.origin[1] + self.cy - screen_y
        distance = math.hypot(dx, dy)
        if distance <= self.hub:
            return "hub"
        if self.inner <= distance <= self.outer:
            extent = 360 / self.per_face
            angle = math.degrees(math.atan2(dy, dx))
            index = int(round((90 - angle) / extent)) % self.per_face
            if index < len(self.face_items()):
                return index
        return None

    def slice_center_screen(self, index):
        extent = 360 / self.per_face
        theta = math.radians(90 - index * extent)
        radius = (self.outer + self.inner) / 2
        return (int(self.origin[0] + self.cx + radius * math.cos(theta)),
                int(self.origin[1] + self.cy - radius * math.sin(theta)))

    def _set_hover(self, target):
        if target != self.hover:
            self.hover = target
            self.draw()

    def _tick(self):
        if not self.visible:
            return
        x, y = self.app.root.winfo_pointerxy()
        self._set_hover(self.hit(x, y))
        tab = bool(user32.GetAsyncKeyState(VK_TAB) & 0x8000)
        if tab and not self.tab_down:
            self.flip(-1)
        self.tab_down = tab
        if time.time() - self.shown_at > 60:
            self.hide()
            return
        self.window.after(30, self._tick)

    def _event_target(self, event):
        try:
            return self.hit(int(float(event.x_root)), int(float(event.y_root)))
        except (TypeError, ValueError, AttributeError):
            return self.hover

    def _on_position(self, event):
        target = self._event_target(event)
        self._set_hover(target)
        return "copy" if target is not None else "refuse_drop"

    def _on_drop(self, event):
        target = self._event_target(event)
        if target is None:
            target = self.hover
        payload = parse_drop_data(self.app.root, event.data)
        item = None
        if isinstance(target, int):
            items = self.face_items()
            item = items[target] if target < len(items) else None
        self.dropped = True
        self.hide()
        target_hwnd = self.target_hwnd
        self.app.root.after(20, lambda: self.app.handle_drop(item, payload, target_hwnd))
        return "copy"

    def draw(self):
        canvas = self.canvas
        theme = self.app.theme
        fonts = self.app.fonts
        scale = self.app.scale
        canvas.delete("all")
        cx, cy = self.cx, self.cy
        outer, inner, hub = self.outer, self.inner, self.hub
        extent = 360 / self.per_face
        gap = 2.4
        items = self.face_items()
        canvas.create_oval(cx - outer - 5, cy - outer - 5, cx + outer + 5, cy + outer + 5,
                           fill=theme["bg"], outline=theme["border"])
        for index in range(self.per_face):
            item = items[index] if index < len(items) else None
            hovered = self.hover == index
            if hovered:
                fill, outline = theme["accent_soft"], theme["accent"]
            elif item:
                fill, outline = theme["surface"], theme["surface2"]
            else:
                fill, outline = theme["bg"], theme["bg"]
            theta = 90 - index * extent
            canvas.create_arc(cx - outer, cy - outer, cx + outer, cy + outer,
                              start=theta - extent / 2 + gap / 2, extent=extent - gap, style="pieslice",
                              fill=fill, outline=outline, width=2 if hovered else 1)
        canvas.create_oval(cx - inner, cy - inner, cx + inner, cy + inner, fill=DONUT_KEY, outline=theme["border"])
        radius = (outer + inner) / 2
        for index, item in enumerate(items):
            theta = math.radians(90 - index * extent)
            x = cx + radius * math.cos(theta)
            y = cy - radius * math.sin(theta)
            color, _ = theme["kinds"][item.kind]
            hovered = self.hover == index
            name = item.name if len(item.name) <= 12 else item.name[:11] + "\u2026"
            canvas.create_text(x, y - 10 * scale, text=KIND_GLYPH[item.kind], fill=color, font=fonts["icon"])
            canvas.create_text(x, y + 7 * scale, text=name, fill=theme["accent"] if hovered else theme["text"],
                               font=fonts["small_bold"])
        hub_hover = self.hover == "hub"
        canvas.create_oval(cx - hub, cy - hub, cx + hub, cy + hub,
                           fill=theme["accent"] if hub_hover else theme["surface2"],
                           outline=theme["accent"] if hub_hover else theme["border"], width=2)
        canvas.create_text(cx, cy - 7 * scale, text="Open", font=fonts["small_bold"],
                           fill=theme["on_accent"] if hub_hover else theme["text"])
        canvas.create_text(cx, cy + 10 * scale, text=f"{self.face + 1} / {self.faces}", font=fonts["badge"],
                           fill=theme["on_accent"] if hub_hover else theme["muted"])
        if isinstance(self.hover, int) and self.hover < len(items):
            title = items[self.hover].name
            subtitle = (items[self.hover].description or "").replace("\n", " ")
            subtitle = subtitle if len(subtitle) <= 64 else subtitle[:63] + "\u2026"
        elif self.hover == "hub":
            title = "Open the launcher"
            subtitle = "Choose any skill and edit the input first"
        else:
            title = "Drop on a skill or agent"
            subtitle = "Wheel or Tab for more  \u00b7  " + (self.app.pick_model() or "no model yet")
        top = self.caption_top
        height = int(54 * scale)
        width = min(self.width - 8, max(fonts["bold"].measure(title), fonts["small"].measure(subtitle)) + int(40 * scale))
        rounded_rect(canvas, cx - width / 2, top, cx + width / 2, top + height, 14,
                     fill=theme["surface"], outline=theme["border"])
        canvas.create_text(cx, top + height * 0.34, text=title, fill=theme["text"], font=fonts["bold"])
        canvas.create_text(cx, top + height * 0.70, text=subtitle, fill=theme["muted"], font=fonts["small"])


SELFTEST_HELPER = """
import ctypes, json, sys, time
import tkinter as tk
from pathlib import Path
from tkinterdnd2 import TkinterDnD, DND_TEXT, COPY
ctypes.windll.shcore.SetProcessDpiAwareness(1)
state_path = Path(sys.argv[1])
stop_path = Path(sys.argv[2])
root = TkinterDnD.Tk()
root.title('SkillMouse Test Target')
root.geometry('520x320+60+60')
root.attributes('-topmost', True)
text = tk.Text(root, height=6, font=('Segoe UI', 11))
text.pack(fill='both', expand=True, padx=10, pady=10)
text.insert('1.0', 'hello from the test window')
text.tag_add('sel', '1.0', 'end-1c')
text.focus_set()
label = tk.Label(root, text='DRAG ME', bg='#334', fg='white', font=('Segoe UI', 14, 'bold'), padx=40, pady=18)
label.pack(pady=(0, 12))
label.drag_source_register(1, DND_TEXT)
label.dnd_bind('<<DragInitCmd>>', lambda event: (COPY, DND_TEXT, 'dragged text payload'))
started = time.time()
def tick():
    state = {
        'text': text.get('1.0', 'end-1c'),
        'label': [label.winfo_rootx(), label.winfo_rooty(), label.winfo_width(), label.winfo_height()],
        'hwnd': int(root.wm_frame(), 16),
    }
    state_path.write_text(json.dumps(state))
    if stop_path.exists() or time.time() - started > 120:
        root.destroy()
        return
    root.after(150, tick)
root.after(300, tick)
root.mainloop()
"""


def wait_for(check, timeout, interval=0.15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = check()
        except Exception:
            value = None
        if value:
            return value
        time.sleep(interval)
    return None


def inject_move(x, y):
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    normal_x = int((x - left) * 65535 / max(1, width - 1))
    normal_y = int((y - top) * 65535 / max(1, height - 1))
    user32.mouse_event(0x0001 | 0x8000 | 0x4000, normal_x, normal_y, 0, 0)   # MOVE | ABSOLUTE | VIRTUALDESK


def inject_mouse(flags, data=0):
    user32.mouse_event(flags, 0, 0, data & 0xFFFFFFFF, 0)


# =========================================================================== application

class SkillMouseApp:
    def __init__(self):
        start_ui_imports()
        self.root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
        self.root.withdraw()
        self.root.title("SkillMouse (background)")
        self.config = load_config()
        self.state = load_json(STATE_PATH, {})
        self.state.setdefault("recent", [])
        self.state.setdefault("favorites", [])
        self.events = queue.Queue()
        self.popup = None
        self.settings_window = None
        self.items = []
        self.models = []
        self.apply_theme()
        self.refresh()
        self.fake_reply_for_tests = None
        self.last_trigger_target = None
        self.last_result = None
        self.last_drop = None
        self.popup_api = {}
        self.settings_api = {}
        self.listener = None
        self.start_listener()
        self.donut = Donut(self) if DND_AVAILABLE else None
        self.root.after(50, self.poll_events)

    # ---- setup
    def apply_theme(self):
        ui = self.config["ui"]
        self.theme = build_theme(ui)
        self.scale = self.root.winfo_fpixels("1i") / 96.0
        families = set(tkfont.families(self.root))
        family = ui.get("font") if ui.get("font") in families else "Segoe UI"
        mono = next((m for m in MONO_CHOICES if m in families), "Courier New")
        size = int(ui.get("font_size", 10))
        semibold_family = family
        semibold_weight = "bold"
        if family == "Segoe UI" and "Segoe UI Semibold" in families:
            semibold_family, semibold_weight = "Segoe UI Semibold", "normal"
        light_family = "Segoe UI Semilight" if family == "Segoe UI" and "Segoe UI Semilight" in families else family
        icon_family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), family)

        def semibold(points):
            return tkfont.Font(family=semibold_family, size=points, weight=semibold_weight)

        self.fonts = {
            "base": tkfont.Font(family=family, size=size),
            "bold": semibold(size),
            "semibold": semibold(size),
            "small": tkfont.Font(family=family, size=max(7, size - 1)),
            "small_bold": semibold(max(7, size - 1)),
            "section": semibold(max(7, size - 2)),
            "badge": semibold(max(6, size - 3)),
            "keycap": tkfont.Font(family=family, size=max(7, size - 2)),
            "search": tkfont.Font(family=light_family, size=size + 5),
            "title": semibold(size + 3),
            "h1": semibold(size + 5),
            "h2": semibold(size + 3),
            "h3": semibold(size + 1),
            "reading": tkfont.Font(family=family, size=size + 1),
            "mono": tkfont.Font(family=mono, size=max(7, size - 1)),
            "italic": tkfont.Font(family=family, size=max(7, size - 1), slant="italic"),
            "icon": tkfont.Font(family=icon_family, size=size + 1),
            "icon_small": tkfont.Font(family=icon_family, size=max(7, size - 1)),
            "icon_tile": tkfont.Font(family=icon_family, size=size),
            "icon_large": tkfont.Font(family=icon_family, size=size + 4),
        }
        theme = self.theme
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=theme["surface2"], background=theme["surface2"],
                        foreground=theme["text"], arrowcolor=theme["muted"], bordercolor=theme["border"],
                        lightcolor=theme["surface2"], darkcolor=theme["surface2"], padding=6,
                        selectbackground=theme["surface2"], selectforeground=theme["text"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", theme["surface2"])],
                  foreground=[("readonly", theme["text"])],
                  selectbackground=[("readonly", theme["surface2"])],
                  selectforeground=[("readonly", theme["text"])],
                  bordercolor=[("focus", theme["accent"])],
                  arrowcolor=[("hover", theme["text"])])
        style.configure("Vertical.TScrollbar", background=theme["surface2"], troughcolor=theme["surface"],
                        bordercolor=theme["surface"], arrowcolor=theme["muted"], lightcolor=theme["surface2"],
                        darkcolor=theme["surface2"], gripcount=0)
        style.configure("Accent.Horizontal.TScale", background=theme["accent"], troughcolor=theme["surface2"],
                        bordercolor=theme["bg"], lightcolor=theme["accent"], darkcolor=theme["accent"],
                        sliderthickness=int(14 * self.scale))
        style.configure("TSpinbox", fieldbackground=theme["surface2"], background=theme["surface2"],
                        foreground=theme["text"], arrowcolor=theme["muted"], bordercolor=theme["border"],
                        lightcolor=theme["surface2"], darkcolor=theme["surface2"], padding=4)
        self.root.option_add("*TCombobox*Listbox.background", theme["surface2"])
        self.root.option_add("*TCombobox*Listbox.foreground", theme["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme["selection"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme["text"])
        self.root.option_add("*TCombobox*Listbox.font", self.fonts["base"])
        self.root.option_add("*TCombobox*Listbox.relief", "flat")
        self.icon = make_icon(theme["accent"])
        self.root.iconphoto(True, self.icon)

    def start_listener(self):
        if self.listener:
            self.listener.stop()
        self.listener = InputListener(
            self.events,
            self.config.get("hotkey"),
            self.config.get("mouse_button"),
            self.config.get("drag_modifier", "ctrl") if DND_AVAILABLE else "none",
            self.config.get("drag_threshold", 28),
        )
        self.listener.start()
        expected = (1 if self.config.get("hotkey") else 0) + (1 if self.listener.needs_hook else 0)
        deadline = time.time() + 1.0
        while len(self.listener.status) < expected and time.time() < deadline:
            time.sleep(0.02)

    def refresh(self):
        self.items = discover_items(self.config)
        self.refresh_models_async()

    def refresh_models_async(self):
        def worker():
            models = available_models(self.config)
            if models or not self.models:
                self.models = models

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event == "trigger":
                    self.on_trigger()
                elif isinstance(event, tuple):
                    self.handle_event(event)
        except queue.Empty:
            pass
        self.root.after(50, self.poll_events)

    def handle_event(self, event):
        kind = event[0]
        if kind == "call":
            _, function, box, done = event
            try:
                box["value"] = function()
            except Exception as error:
                box["error"] = error
            finally:
                done.set()
        elif kind == "drag_start" and self.donut:
            foreground = user32.GetForegroundWindow()
            owner_pid = wt.DWORD()
            user32.GetWindowThreadProcessId(foreground, ctypes.byref(owner_pid))
            if owner_pid.value != os.getpid():
                self.donut.show(event[1], event[2], foreground)
        elif kind == "drag_end" and self.donut:
            self.root.after(450, self.donut.hide_if_idle)
        elif kind == "wheel" and self.donut and self.donut.visible:
            self.donut.flip(event[1])

    def ui_call(self, function, timeout=20):
        """Run a function on the UI thread from a worker thread and return its result."""
        box = {}
        done = threading.Event()
        self.events.put(("call", function, box, done))
        if not done.wait(timeout):
            raise TimeoutError("UI call timed out")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def donut_items(self):
        by_key = {item.key: item for item in self.items}
        ordered = [ASK_ITEM]
        seen = {ASK_ITEM.key}
        for key in self.state.get("favorites", []) + self.state.get("recent", []):
            if key in by_key and key not in seen:
                ordered.append(by_key[key])
                seen.add(key)
        for item in self.items:
            if item.key not in seen:
                ordered.append(item)
                seen.add(item.key)
        return ordered

    def pick_model(self):
        preferred = self.state.get("model") or self.config.get("default_model")
        if preferred and preferred in self.models:
            return preferred
        if self.models:
            return self.models[0]
        if self.fake_reply_for_tests:
            return "selftest:fake"
        return None

    def handle_drop(self, item, payload, target_hwnd):
        text, images = payload_to_input(payload, int(self.config.get("max_context_chars", 60000)))
        self.last_drop = {"item": item.name if item else "launcher", "text": text, "images": len(images)}
        model = self.pick_model()
        if item is None or model is None:
            self.close_popup()
            self.show_popup(target_hwnd, text)
            return
        self.remember(item, model)
        self.open_result(item, model, text, "", target_hwnd, images=images)

    def save_state(self):
        save_json(STATE_PATH, self.state)

    def status_line(self):
        listener = ", ".join(self.listener.status) if self.listener else ""
        return f"{len(self.items)} items  \u00b7  {listener}"

    def themed_toplevel(self, title):
        window = tk.Toplevel(self.root, bg=self.theme["bg"])
        window.withdraw()
        window.title(title)
        window.attributes("-alpha", float(self.config["ui"].get("opacity", 1.0)))
        return window

    def present(self, window, width, height, topmost=True):
        width = int(width * self.scale)
        height = int(height * self.scale)
        x, y = self.root.winfo_pointerxy()
        left, top, right, bottom = work_area_at(x, y)
        width = min(width, right - left - 40)
        height = min(height, bottom - top - 40)
        pos_x = left + (right - left - width) // 2
        pos_y = top + max(20, int((bottom - top - height) * 0.28))
        window.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        window.attributes("-topmost", topmost)
        window.deiconify()
        window.update_idletasks()
        style_title_bar(window, self.theme)
        force_foreground(int(window.wm_frame(), 16))

    # ---- trigger -> popup
    def on_trigger(self):
        if self.popup and self.popup.winfo_exists():
            force_foreground(int(self.popup.wm_frame(), 16))
            return
        self.refresh_models_async()
        target = user32.GetForegroundWindow()
        self.last_trigger_target = target
        selection = grab_selection(target) if self.config.get("auto_copy_selection", True) else ""
        self.show_popup(target, selection)

    def ranked_items(self, query, kind_filter):
        favorites = set(self.state.get("favorites", []))
        recent_rank = {key: index for index, key in enumerate(self.state.get("recent", []))}
        pool = [ASK_ITEM] + self.items
        if kind_filter == "fav":
            pool = [item for item in pool if item.key in favorites]
        elif kind_filter != "all":
            pool = [item for item in pool if item.kind == kind_filter]
        query = query.strip().lower()
        if query:
            words = query.split()
            scored = []
            for item in pool:
                haystack = item.search_text
                if not all(word in haystack for word in words):
                    continue
                name = item.name.lower().lstrip("/")
                score = 0 if name.startswith(query) else 1 if query in name else 2
                scored.append((score, item.key not in favorites, recent_rank.get(item.key, 9999), name, item))
            return [entry[-1] for entry in sorted(scored, key=lambda e: e[:4])]
        return sorted(pool, key=lambda item: (
            item.kind != "builtin",
            item.key not in favorites,
            recent_rank.get(item.key, 9999),
            KIND_ORDER[item.kind],
            item.name.lower(),
        ))

    def show_popup(self, target_hwnd, selection):
        theme = self.theme
        fonts = self.fonts
        ui = self.config["ui"]
        scale = self.scale
        pad = int(16 * scale)
        rounded = RoundedWindow(self, APP_NAME, radius=16)
        popup = rounded.window
        body = rounded.body
        self.popup = popup
        state = {"tab": "all", "dialog": False, "had_focus": False, "editor_open": False}

        # search row
        search_row = tk.Frame(body, bg=theme["bg"])
        search_row.pack(fill="x", padx=(pad, int(10 * scale)), pady=(int(12 * scale), int(10 * scale)))
        search = FlatInput(search_row, self, "Search skills, agents and commands", GLYPH["search"],
                           font_key="search", icon_key="icon_large")
        search.frame.pack(side="left", fill="x", expand=True)
        model_var = tk.StringVar()
        chip = ModelChip(search_row, self, model_var, lambda: open_model_picker())
        chip.canvas.pack(side="right", padx=(int(10 * scale), 0))
        tk.Frame(body, bg=theme["border"], height=1).pack(fill="x")

        # tabs
        tabs_row = tk.Frame(body, bg=theme["bg"])
        tabs_row.pack(fill="x", padx=int(10 * scale), pady=(int(6 * scale), 0))
        counts = {kind: sum(1 for i in self.items if i.kind == kind) for kind in KIND_ORDER}
        tab_specs = [("all", "All", len(self.items)), ("skill", "Skills", counts["skill"]),
                     ("agent", "Agents", counts["agent"]), ("command", "Commands", counts["command"])]
        if counts["rules"]:
            tab_specs.append(("rules", "Rules", counts["rules"]))
        tab_specs.append(("fav", "Favorites", len(self.state.get("favorites", []))))
        tab_widgets = {}

        def style_tabs():
            for key, (label, underline) in tab_widgets.items():
                active = key == state["tab"]
                label.config(fg=theme["text"] if active else theme["muted"])
                underline.config(bg=theme["accent"] if active else theme["bg"])

        def set_tab(key):
            state["tab"] = key
            style_tabs()
            render()

        for key, name, count in tab_specs:
            holder = tk.Frame(tabs_row, bg=theme["bg"], cursor="hand2")
            holder.pack(side="left", padx=(0, int(2 * scale)))
            label = tk.Label(holder, text=f"{name}  {count}", bg=theme["bg"], font=fonts["small"],
                             padx=int(8 * scale), pady=int(4 * scale), cursor="hand2")
            label.pack()
            underline = tk.Frame(holder, bg=theme["bg"], height=2)
            underline.pack(fill="x", padx=int(8 * scale))
            for widget in (holder, label):
                widget.bind("<Button-1>", lambda e, k=key: set_tab(k))
            tab_widgets[key] = (label, underline)
        style_tabs()

        # footer action bar (packed bottom-up so it is never pushed off)
        footer = tk.Frame(body, bg=theme["surface"])
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg=theme["border"], height=1).pack(side="top", fill="x")
        footer_inner = tk.Frame(footer, bg=theme["surface"])
        footer_inner.pack(fill="x", padx=(pad, int(8 * scale)), pady=int(7 * scale))
        logo_tile(footer_inner, self).pack(side="left")
        tk.Label(footer_inner, text=APP_NAME, bg=theme["surface"], fg=theme["text"],
                 font=fonts["small_bold"]).pack(side="left", padx=(int(8 * scale), int(8 * scale)))
        detail_var = tk.StringVar()
        tk.Label(footer_inner, textvariable=detail_var, bg=theme["surface"], fg=theme["muted"],
                 font=fonts["small"]).pack(side="left")
        KeyHint(footer_inner, self, "Run", ("\u21b5",), lambda: run(), emphasis=True).canvas.pack(side="right")
        tk.Frame(footer_inner, bg=theme["border"], width=1, height=int(16 * scale)).pack(side="right",
                                                                                         padx=int(6 * scale))
        KeyHint(footer_inner, self, "Actions", ("Ctrl", "K"), lambda: open_actions()).canvas.pack(side="right")

        instruction = FlatInput(body, self, "Add instructions (optional)", GLYPH["edit"], font_key="base",
                                icon_key="icon_small")
        instruction.frame.pack(side="bottom", fill="x", padx=pad, pady=(int(6 * scale), int(10 * scale)))
        editor = TextBox(body, theme, fonts["base"], height=5, placeholder="Paste, type or drop text here")
        editor.set(selection)
        context_row = tk.Frame(body, bg=theme["bg"], cursor="hand2")
        context_row.pack(side="bottom", fill="x", padx=(pad, int(8 * scale)), pady=(int(8 * scale), 0))
        tk.Frame(body, bg=theme["border"], height=1).pack(side="bottom", fill="x")
        context_icon = tk.Label(context_row, text=GLYPH["rules"], font=fonts["icon_small"], bg=theme["bg"],
                                fg=theme["muted"], cursor="hand2")
        context_icon.pack(side="left")
        context_title = tk.Label(context_row, font=fonts["small_bold"], bg=theme["bg"], fg=theme["text"],
                                 cursor="hand2")
        context_title.pack(side="left", padx=(int(8 * scale), 0))
        IconButton(context_row, GLYPH["close"], lambda: clear_context(), self).pack(side="right")
        IconButton(context_row, GLYPH["edit"], lambda: toggle_editor(), self).pack(side="right")
        context_count = tk.Label(context_row, font=fonts["small"], bg=theme["bg"], fg=theme["muted"])
        context_count.pack(side="right", padx=(0, int(4 * scale)))
        context_preview = tk.Label(context_row, font=fonts["small"], bg=theme["bg"], fg=theme["muted"],
                                   anchor="w", cursor="hand2")
        context_preview.pack(side="left", fill="x", expand=True, padx=(int(10 * scale), int(6 * scale)))

        # list fills the rest
        def on_select(item):
            if item is None:
                detail_var.set("")
            elif item.kind == "builtin":
                detail_var.set("Chat with the model")
            else:
                detail_var.set(f"{KIND_NAME[item.kind]}  \u00b7  {item.source}")

        item_list = ItemList(body, self, on_activate=lambda: run(), on_select=on_select)
        item_list.canvas.pack(fill="both", expand=True, padx=int(6 * scale), pady=(int(4 * scale), int(4 * scale)))

        # behaviour
        def refresh_context(*_):
            text = editor.get()
            if text.strip():
                flat = " ".join(text.split())
                context_title.config(text="Input")
                context_preview.config(text=flat[:110] + ("\u2026" if len(flat) > 110 else ""))
                context_count.config(text=f"{len(text):,} chars")
            else:
                context_title.config(text="No input")
                context_preview.config(text="Select text before opening, or paste / drop it here")
                context_count.config(text="")

        def toggle_editor(*_):
            if state["editor_open"]:
                editor.frame.pack_forget()
                state["editor_open"] = False
                search.entry.focus_set()
            else:
                editor.frame.pack(side="bottom", fill="x", padx=pad, pady=(int(8 * scale), 0),
                                  after=instruction.frame)
                state["editor_open"] = True
                editor.text.focus_set()
            refresh_context()
            return "break"

        def clear_context():
            editor.set("")
            refresh_context()

        for widget in (context_row, context_icon, context_title, context_preview):
            widget.bind("<Button-1>", toggle_editor)
        editor.text.bind("<KeyRelease>", refresh_context, add="+")
        refresh_context()

        if DND_AVAILABLE:
            def drop_into_input(event):
                payload = parse_drop_data(self.root, event.data)
                text, _ = payload_to_input(payload, int(self.config.get("max_context_chars", 60000)))
                current = editor.get()
                editor.set((current + "\n\n" if current.strip() else "") + text)
                refresh_context()
                return "copy"

            for widget in (editor.text, context_row, item_list.canvas):
                widget.drop_target_register(DND_FILES, DND_TEXT)
                widget.dnd_bind("<<Drop>>", drop_into_input)

        def reload_list():
            self.refresh()
            render()

        def do_import(kind):
            state["dialog"] = True
            popup.attributes("-topmost", False)
            try:
                if kind == "folder":
                    chosen = filedialog.askdirectory(parent=popup, title="Choose a skill or agent folder")
                    chosen = [chosen] if chosen else []
                else:
                    chosen = filedialog.askopenfilenames(
                        parent=popup, title="Choose skill / agent files",
                        filetypes=[("Skills and agents", "*.md *.zip"), ("All files", "*.*")],
                    )
            finally:
                if popup.winfo_exists():
                    popup.attributes("-topmost", True)
                state["dialog"] = False
            imported = []
            for path in chosen:
                try:
                    imported.extend(import_into_library(path))
                except Exception as error:
                    messagebox.showerror(APP_NAME, f"Could not import {path}:\n{error}", parent=popup)
            if imported:
                reload_list()
                detail_var.set("Imported: " + ", ".join(imported))

        def do_new(kind):
            path = create_from_template(kind)
            os.startfile(str(path))
            reload_list()
            detail_var.set(f"Created {path.name} - edit it and it appears automatically")

        def open_library():
            LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(LIBRARY_DIR))

        import_entries = [
            ("Import skill / agent folder...", lambda: do_import("folder")),
            ("Import .md or .zip files...", lambda: do_import("files")),
            None,
            ("New skill from template", lambda: do_new("skill")),
            ("New agent from template", lambda: do_new("agent")),
            None,
            ("Open library folder", open_library),
        ]

        def sync_models():
            if not popup.winfo_exists():
                return
            if not model_var.get() and self.models:
                preferred = self.state.get("model") or self.config.get("default_model")
                model_var.set(preferred if preferred in self.models else self.models[0])
            popup.after(600, sync_models)

        def render(*_):
            query = search.get().strip()
            items = self.ranked_items(query, state["tab"])
            if not query and state["tab"] == "all":
                favorites = set(self.state.get("favorites", []))
                recent = set(self.state.get("recent", [])[:6])
                suggestions = [i for i in items if i.kind == "builtin" or i.key in favorites or i.key in recent][:8]
                chosen = {id(i) for i in suggestions}
                sections = [("Suggestions", suggestions)]
                for kind, title in (("skill", "Skills"), ("agent", "Agents"), ("command", "Commands"),
                                    ("rules", "Rules")):
                    group = [i for i in items if i.kind == kind and id(i) not in chosen]
                    sections.append((title, group))
                item_list.set_items(None, sections=sections)
            else:
                item_list.set_items(items)

        def run(*_):
            item = item_list.current()
            if item is None:
                return "break"
            if not model_var.get():
                open_model_picker()
                return "break"
            self.remember(item, model_var.get())
            text = editor.get()
            extra = instruction.get()
            self.close_popup()
            self.open_result(item, model_var.get(), text, extra, target_hwnd)
            return "break"

        def toggle_favorite(*_):
            item = item_list.current()
            if item is None or item.kind == "builtin":
                return "break"
            favorites = self.state["favorites"]
            if item.key in favorites:
                favorites.remove(item.key)
            else:
                favorites.insert(0, item.key)
            self.save_state()
            tab_widgets["fav"][0].config(text=f"Favorites  {len(favorites)}")
            index = item_list.index
            item_list.redraw()
            item_list.select(index, scroll=False)
            return "break"

        def open_item(*_):
            item = item_list.current()
            if item and item.path:
                os.startfile(str(item.path.parent if item.persona else item.path))
            return "break"

        def refocus():
            if popup.winfo_exists():
                search.entry.focus_force()

        def open_actions(*_):
            if getattr(self, "active_popover", None):
                self.active_popover.close()
            item = item_list.current()
            is_favorite = bool(item and item.key in self.state.get("favorites", []))
            entries = [
                {"label": "Run", "glyph": GLYPH["run"], "keys": ("\u21b5",), "action": run},
                {"label": "Edit input", "glyph": GLYPH["edit"], "keys": ("Ctrl", "E"), "action": toggle_editor},
                {"label": "Remove from favorites" if is_favorite else "Add to favorites",
                 "glyph": GLYPH["starfill"] if is_favorite else GLYPH["star"], "keys": ("Ctrl", "D"),
                 "action": toggle_favorite},
                {"label": "Open source file", "glyph": GLYPH["open"], "keys": ("Ctrl", "O"), "action": open_item},
                "sep",
                {"label": "Change model", "glyph": GLYPH["model"], "keys": ("Ctrl", "M"),
                 "action": open_model_picker},
            ]
            glyphs = [GLYPH["folder"], GLYPH["import"], None, GLYPH["add"], GLYPH["add"], None, GLYPH["library"]]
            entries.append("sep")
            for entry, glyph in zip(import_entries, glyphs):
                if entry is not None:
                    entries.append({"label": entry[0].replace("...", "\u2026"), "glyph": glyph,
                                    "action": entry[1]})
            entries += [
                "sep",
                {"label": "Settings", "glyph": GLYPH["settings"], "keys": ("Ctrl", ","),
                 "action": self.open_settings},
                {"label": "Rescan skills and models", "glyph": GLYPH["refresh"], "action": reload_list},
                {"label": "Quit SkillMouse", "glyph": GLYPH["power"], "action": self.quit},
            ]
            anchor = (popup.winfo_rootx() + popup.winfo_width() - int(10 * scale),
                      footer.winfo_rooty() - int(6 * scale))
            Popover(self, entries, anchor, align="bottom-right", width=380, on_close=refocus)
            return "break"

        def open_model_picker(*_):
            if getattr(self, "active_popover", None):
                self.active_popover.close()
            current = model_var.get()
            entries = []
            for model_ref in self.models:
                provider, _, model = model_ref.partition(":")
                entries.append({"label": model, "hint": provider,
                                "glyph": GLYPH["check"] if model_ref == current else GLYPH["model"],
                                "action": lambda ref=model_ref: model_var.set(ref)})
            if not entries:
                entries.append({"label": "No models yet - open Settings", "glyph": GLYPH["settings"],
                                "action": self.open_settings})
            anchor = (chip.canvas.winfo_rootx() + chip.canvas.winfo_width(),
                      chip.canvas.winfo_rooty() + chip.canvas.winfo_height() + int(6 * scale))
            Popover(self, entries, anchor, align="top-right", width=340, placeholder="Search models",
                    on_close=refocus)
            return "break"

        def on_focus_in(_):
            state["had_focus"] = True

        def on_focus_out(_):
            popup.after(200, check_blur)

        def check_blur():
            if not popup.winfo_exists() or state["dialog"] or not state["had_focus"]:
                return
            if self.settings_window and self.settings_window.winfo_exists():
                return
            if self.root.focus_get() is None and self.config.get("close_on_blur", True):
                self.close_popup()

        search.var.trace_add("write", render)
        for widget in (search.entry, instruction.entry):
            widget.bind("<Down>", lambda e: item_list.move(1))
            widget.bind("<Up>", lambda e: item_list.move(-1))
            widget.bind("<Next>", lambda e: item_list.move(8))
            widget.bind("<Prior>", lambda e: item_list.move(-8))
            widget.bind("<Return>", run)
        editor.text.bind("<Control-Return>", run)
        popup.bind("<Escape>", lambda e: toggle_editor() if state["editor_open"] else self.close_popup())
        popup.bind("<Control-k>", open_actions)
        popup.bind("<Control-m>", open_model_picker)
        popup.bind("<Control-e>", toggle_editor)
        popup.bind("<Control-d>", toggle_favorite)
        popup.bind("<Control-o>", open_item)
        popup.bind("<Control-comma>", lambda e: self.open_settings())
        popup.bind("<FocusIn>", on_focus_in, add="+")
        popup.bind("<FocusOut>", on_focus_out, add="+")
        for number, (key, _, _) in enumerate(tab_specs, start=1):
            popup.bind(f"<Control-Key-{number}>", lambda e, k=key: set_tab(k))

        self.popup_api = {
            "popup": popup,
            "input": editor,
            "instruction": instruction,
            "model_var": model_var,
            "run": run,
            "visible_names": lambda: [i.name for i in item_list.items],
            "import_entries": import_entries,
            "reload": reload_list,
            "open_actions": open_actions,
        }
        sync_models()
        rounded.present(ui.get("width", 760), ui.get("height", 700))
        render()
        search.entry.focus_force()

    def close_popup(self):
        popover = getattr(self, "active_popover", None)
        if popover:
            popover.close()
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None

    def remember(self, item, model):
        recent = [key for key in self.state.get("recent", []) if key != item.key]
        self.state["recent"] = ([item.key] + recent)[:40]
        self.state["model"] = model
        self.save_state()

    # ---- result window
    def open_result(self, item, model_ref, selection, instruction, target_hwnd, fake_reply=None, images=None):
        fake_reply = fake_reply or self.fake_reply_for_tests
        theme = self.theme
        fonts = self.fonts
        scale = self.scale
        rounded = RoundedWindow(self, f"{APP_NAME} - {item.name}", radius=14)
        window = rounded.window
        body = rounded.body
        status_var = tk.StringVar()
        base_status = f"{KIND_NAME[item.kind]}  \u00b7  {model_ref.split(':', 1)[-1]}"
        status_var.set(base_status)

        header = tk.Frame(body, bg=theme["bg"])
        header.pack(fill="x", padx=(int(16 * scale), int(8 * scale)), pady=(int(12 * scale), int(10 * scale)))
        tile = icon_tile(header, self, item.kind, size=34)
        tile.pack(side="left")
        titles = tk.Frame(header, bg=theme["bg"])
        titles.pack(side="left", padx=(int(12 * scale), 0))
        title_label = tk.Label(titles, text=item.name, bg=theme["bg"], fg=theme["text"], font=fonts["title"],
                               anchor="w")
        title_label.pack(anchor="w")
        status_label = tk.Label(titles, textvariable=status_var, bg=theme["bg"], fg=theme["muted"],
                                font=fonts["small"], anchor="w")
        status_label.pack(anchor="w")
        IconButton(header, GLYPH["close"], lambda: close_window(), self).pack(side="right")
        IconButton(header, GLYPH["copy"], lambda: copy_reply(), self).pack(side="right")
        for widget in (header, titles, title_label, status_label, tile):
            rounded.make_draggable(widget)
        tk.Frame(body, bg=theme["border"], height=1).pack(fill="x")

        footer = tk.Frame(body, bg=theme["surface"])
        footer.pack(side="bottom", fill="x")
        tk.Frame(footer, bg=theme["border"], height=1).pack(fill="x")
        footer_inner = tk.Frame(footer, bg=theme["surface"])
        footer_inner.pack(fill="x", padx=(int(16 * scale), int(22 * scale)), pady=int(8 * scale))
        KeyHint(footer_inner, self, "Insert into app", ("Ctrl", "\u21b5"), lambda: insert_reply(),
                emphasis=True).canvas.pack(side="right")
        tk.Frame(footer_inner, bg=theme["border"], width=1, height=int(16 * scale)).pack(side="right",
                                                                                         padx=int(6 * scale))
        KeyHint(footer_inner, self, "Copy", ("Ctrl", "Shift", "C"), lambda: copy_reply()).canvas.pack(side="right")
        follow = FlatInput(footer_inner, self, "Ask a follow-up", GLYPH["builtin"], font_key="base",
                           icon_key="icon_small")
        follow.frame.pack(side="left", fill="x", expand=True, padx=(0, int(12 * scale)))

        output = tk.Text(body, wrap="word", font=fonts["reading"], relief="flat", bd=0, highlightthickness=0,
                         bg=theme["bg"], fg=theme["text"], insertbackground=theme["text"],
                         selectbackground=blend(theme["bg"], theme["accent"], 0.35), selectforeground=theme["text"],
                         padx=int(28 * scale), pady=int(18 * scale), spacing1=int(2 * scale),
                         spacing2=int(2 * scale), spacing3=int(6 * scale), cursor="arrow")
        output.pack(fill="both", expand=True)
        output.tag_configure("thinking", foreground=theme["muted"], font=fonts["italic"])
        output.tag_configure("note", foreground=theme["muted"], font=fonts["small"])
        output.tag_configure("h1", font=fonts["h1"], spacing1=int(12 * scale), spacing3=int(6 * scale))
        output.tag_configure("h2", font=fonts["h2"], spacing1=int(10 * scale), spacing3=int(4 * scale))
        output.tag_configure("h3", font=fonts["h3"], spacing1=int(8 * scale), spacing3=int(2 * scale))
        output.tag_configure("bold", font=fonts["semibold"])
        output.tag_configure("code", font=fonts["mono"], background=theme["surface2"], foreground=theme["accent"])
        output.tag_configure("codeblock", font=fonts["mono"], background=theme["surface"],
                             lmargin1=int(14 * scale), lmargin2=int(14 * scale), rmargin=int(14 * scale),
                             spacing1=0, spacing3=0)
        output.tag_configure("bullet", lmargin1=int(6 * scale), lmargin2=int(26 * scale))
        output.tag_configure("bulletmark", foreground=theme["accent"])
        output.tag_configure("you", foreground=theme["accent"], font=fonts["semibold"], spacing1=int(14 * scale))
        output.tag_configure("error", foreground="#f87171")
        output.configure(state="disabled")
        rounded.add_resize_grip(520, 360)

        system_prompt = build_system_prompt(item, instruction, int(self.config.get("max_context_chars", 60000)))
        conversation = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_user_message(selection, instruction)},
            ],
            "reply": "",
            "stop": threading.Event(),
            "busy": False,
            "queue": queue.Queue(),
            "started": 0.0,
            "thinking": False,
            "tick": 0,
        }
        if images:
            text_part = conversation["messages"][1]["content"]
            conversation["messages"][1]["content"] = [{"type": "text", "text": text_part}] + list(images)

        def editable(function):
            output.configure(state="normal")
            try:
                function()
            finally:
                output.configure(state="disabled")

        def write(text, tags=None):
            editable(lambda: output.insert("end", text, tags))

        def worker():
            try:
                if fake_reply:
                    for word in re.split(r"(\s+)", fake_reply):
                        conversation["queue"].put(("content", word))
                        time.sleep(0.004)
                else:
                    stream_chat(self.config, model_ref, conversation["messages"],
                                lambda piece, kind: conversation["queue"].put((kind, piece)),
                                conversation["stop"])
                conversation["queue"].put(("done", None))
            except Exception as error:
                conversation["queue"].put(("error", str(error)))

        def start_turn():
            conversation.update(reply="", busy=True, started=time.time(), thinking=False)
            conversation["stop"] = threading.Event()
            output.mark_set("turn_start", "end-1c")
            output.mark_gravity("turn_start", "left")
            threading.Thread(target=worker, daemon=True).start()
            window.after(30, drain)

        def finish_thinking():
            if conversation["thinking"]:
                seconds = time.time() - conversation["started"]

                def replace():
                    output.delete("think_start", "end-1c")
                    output.insert("end", f"Thought for {seconds:.0f}s\n\n", "note")

                editable(replace)
                conversation["thinking"] = False

        def drain():
            if not window.winfo_exists():
                conversation["stop"].set()
                return
            try:
                while True:
                    kind, value = conversation["queue"].get_nowait()
                    if kind == "reasoning":
                        if not conversation["thinking"] and not conversation["reply"]:
                            output.mark_set("think_start", "end-1c")
                            output.mark_gravity("think_start", "left")
                            conversation["thinking"] = True
                        write(value, "thinking")
                    elif kind == "content":
                        finish_thinking()
                        if not conversation["reply"]:
                            output.mark_set("reply_start", "end-1c")
                            output.mark_gravity("reply_start", "left")
                        conversation["reply"] += value
                        write(value)
                    elif kind == "error":
                        finish_thinking()
                        write(f"\n{value}\n", "error")
                        conversation["busy"] = False
                        status_var.set(f"{base_status}  \u00b7  Error")
                        return
                    else:
                        finish_thinking()
                        reply = conversation["reply"]
                        if reply:
                            def render_reply():
                                output.delete("reply_start", "end-1c")
                                insert_markdown(output, reply.strip())

                            editable(render_reply)
                        conversation["messages"].append({"role": "assistant", "content": reply})
                        conversation["busy"] = False
                        seconds = time.time() - conversation["started"]
                        status_var.set(f"{base_status}  \u00b7  {seconds:.1f}s")
                        output.see("end")
                        return
                    output.see("end")
            except queue.Empty:
                pass
            conversation["tick"] += 1
            dots = "\u00b7" * (conversation["tick"] // 8 % 3 + 1)
            phase = "Writing" if conversation["reply"] else "Thinking"
            status_var.set(f"{base_status}  \u00b7  {phase} {dots}")
            window.after(30, drain)

        def send_follow_up(*_):
            text = follow.get().strip()
            if not text or conversation["busy"]:
                return "break"
            follow.set("")
            conversation["messages"].append({"role": "user", "content": text})
            write(f"\n\n{text}\n", "you")
            start_turn()
            return "break"

        def last_reply():
            for message in reversed(conversation["messages"]):
                if message["role"] == "assistant":
                    return message["content"]
            return conversation["reply"]

        def copy_reply(*_):
            set_clipboard_text(last_reply())
            status_var.set(f"{base_status}  \u00b7  Copied")
            return "break"

        def insert_reply(*_):
            set_clipboard_text(last_reply())
            user32.SetForegroundWindow(target_hwnd)
            window.destroy()
            self.root.after(200, lambda: tap_ctrl_and("V"))
            return "break"

        def close_window():
            conversation["stop"].set()
            if window.winfo_exists():
                window.destroy()

        def escape(_):
            if conversation["busy"]:
                conversation["stop"].set()
                status_var.set(f"{base_status}  \u00b7  Stopped")
            else:
                close_window()

        follow.entry.bind("<Return>", send_follow_up)
        window.bind("<Escape>", escape)
        window.bind("<Control-Return>", insert_reply)
        window.bind("<Control-C>", copy_reply)
        rounded.present(820, 640)
        follow.entry.focus_force()
        self.last_result = {"item": item.name, "conversation": conversation, "insert": insert_reply,
                            "copy": copy_reply, "window": window}
        start_turn()
        return window

    # ---- settings
    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            force_foreground(int(self.settings_window.wm_frame(), 16))
            return
        if self.popup and self.popup.winfo_exists():
            self.popup.attributes("-topmost", False)
        theme = self.theme
        fonts = self.fonts
        draft = copy.deepcopy(load_json(CONFIG_PATH, {}))
        draft_config = load_config()
        draft.setdefault("ui", {})
        ui = {**DEFAULT_UI, **draft["ui"]}
        rounded = RoundedWindow(self, f"{APP_NAME} Settings", radius=14, header="Settings",
                                on_close=lambda: cancel())
        window = rounded.window
        self.settings_window = window
        shell = tk.Frame(rounded.body, bg=theme["bg"])
        shell.pack(fill="both", expand=True)
        nav = tk.Frame(shell, bg=theme["surface"], width=int(170 * self.scale))
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        tk.Label(nav, text=APP_NAME, bg=theme["surface"], fg=theme["text"], font=fonts["title"]).pack(
            anchor="w", padx=18, pady=(18, 16))
        content = tk.Frame(shell, bg=theme["bg"])
        content.pack(side="left", fill="both", expand=True, padx=24, pady=18)
        pages = {}
        nav_labels = {}
        current = {"page": None}

        def show_page(name):
            for page_name, frame in pages.items():
                frame.pack_forget()
            pages[name].pack(fill="both", expand=True)
            current["page"] = name
            for page_name, label in nav_labels.items():
                active = page_name == name
                label.config(bg=theme["accent_soft"] if active else theme["surface"],
                             fg=theme["accent"] if active else theme["muted"])

        for name in ("Appearance", "Sources", "Models", "Input"):
            label = tk.Label(nav, text=name, bg=theme["surface"], fg=theme["muted"], font=fonts["base"],
                             anchor="w", padx=18, pady=8, cursor="hand2")
            label.pack(fill="x", padx=8, pady=1)
            label.bind("<Button-1>", lambda e, n=name: show_page(n))
            nav_labels[name] = label
            pages[name] = tk.Frame(content, bg=theme["bg"])

        def section(parent, title, subtitle=None):
            tk.Label(parent, text=title, bg=theme["bg"], fg=theme["text"], font=fonts["h3"]).pack(
                anchor="w", pady=(14, 2))
            if subtitle:
                tk.Label(parent, text=subtitle, bg=theme["bg"], fg=theme["muted"], font=fonts["small"],
                         justify="left", wraplength=int(560 * self.scale)).pack(anchor="w", pady=(0, 6))

        def checkbox(parent, text, variable):
            return tk.Checkbutton(parent, text=text, variable=variable, bg=theme["bg"], fg=theme["text"],
                                  selectcolor=theme["surface2"], activebackground=theme["bg"],
                                  activeforeground=theme["text"], font=fonts["base"], bd=0,
                                  highlightthickness=0)

        # --- Appearance
        page = pages["Appearance"]
        section(page, "Theme")
        theme_var = tk.StringVar(value=ui["theme"])
        accent_var = tk.StringVar(value=ui.get("accent", ""))
        grid = tk.Frame(page, bg=theme["bg"])
        grid.pack(anchor="w")
        theme_cards = {}

        def draw_theme_cards():
            for name, canvas in theme_cards.items():
                palette = THEMES[name]
                accent = accent_var.get() or palette["accent"]
                canvas.delete("all")
                width, height = int(118 * self.scale), int(64 * self.scale)
                selected = name == theme_var.get()
                rounded_rect(canvas, 2, 2, width - 2, height - 2, 10, fill=palette["bg"],
                             outline=theme["accent"] if selected else palette["border"], width=2 if selected else 1)
                rounded_rect(canvas, 10, 10, width - 10, 24 * self.scale, 5, fill=palette["surface2"], outline="")
                canvas.create_oval(14, 30 * self.scale, 24 * self.scale, 40 * self.scale, fill=accent, outline="")
                canvas.create_text(30 * self.scale, 35 * self.scale, anchor="w", text=name,
                                   fill=palette["text"], font=fonts["small"])
                rounded_rect(canvas, 14, 46 * self.scale, width * 0.6, 52 * self.scale, 3,
                             fill=palette["muted"], outline="")

        for index, name in enumerate(THEMES):
            canvas = tk.Canvas(grid, width=int(118 * self.scale), height=int(64 * self.scale),
                               bg=theme["bg"], highlightthickness=0, cursor="hand2")
            canvas.grid(row=index // 4, column=index % 4, padx=(0, 10), pady=(0, 10))
            canvas.bind("<Button-1>", lambda e, n=name: (theme_var.set(n), draw_theme_cards()))
            theme_cards[name] = canvas
        draw_theme_cards()

        section(page, "Accent color")
        swatches = tk.Frame(page, bg=theme["bg"])
        swatches.pack(anchor="w")

        def pick_accent(color):
            accent_var.set(color)
            draw_theme_cards()

        def custom_accent():
            chosen = colorchooser.askcolor(color=accent_var.get() or theme["accent"], parent=window)
            if chosen and chosen[1]:
                pick_accent(chosen[1])

        for color in ACCENT_PRESETS:
            dot = tk.Canvas(swatches, width=int(26 * self.scale), height=int(26 * self.scale),
                            bg=theme["bg"], highlightthickness=0, cursor="hand2")
            dot.create_oval(3, 3, int(23 * self.scale), int(23 * self.scale), fill=color, outline="")
            dot.pack(side="left", padx=(0, 6))
            dot.bind("<Button-1>", lambda e, c=color: pick_accent(c))
        FlatButton(swatches, "Custom...", custom_accent, theme, fonts["small"]).pack(side="left", padx=(6, 6))
        FlatButton(swatches, "Theme default", lambda: pick_accent(""), theme, fonts["small"], "subtle").pack(side="left")

        section(page, "Text & layout")
        form = tk.Frame(page, bg=theme["bg"])
        form.pack(anchor="w", fill="x")
        families = set(tkfont.families(self.root))
        font_values = [f for f in FONT_CHOICES if f in families] or ["Segoe UI"]
        font_var = tk.StringVar(value=ui["font"])
        size_var = tk.IntVar(value=int(ui["font_size"]))
        opacity_var = tk.DoubleVar(value=int(float(ui["opacity"]) * 100))
        width_var = tk.IntVar(value=int(ui["width"]))
        height_var = tk.IntVar(value=int(ui["height"]))
        describe_var = tk.BooleanVar(value=bool(ui["show_descriptions"]))

        def form_row(row, label, widget):
            tk.Label(form, text=label, bg=theme["bg"], fg=theme["muted"], font=fonts["base"]).grid(
                row=row, column=0, sticky="w", pady=5, padx=(0, 16))
            widget.grid(row=row, column=1, sticky="w", pady=5)

        form_row(0, "Font", ttk.Combobox(form, textvariable=font_var, values=font_values, state="readonly",
                                         width=26, font=fonts["base"]))
        form_row(1, "Font size", ttk.Spinbox(form, from_=8, to=18, textvariable=size_var, width=6, font=fonts["base"]))
        opacity_frame = tk.Frame(form, bg=theme["bg"])
        opacity_label = tk.Label(opacity_frame, text=f"{opacity_var.get()}%", bg=theme["bg"], fg=theme["muted"],
                                 font=fonts["small"], width=5)
        ttk.Scale(opacity_frame, from_=70, to=100, orient="horizontal", variable=opacity_var,
                  length=int(220 * self.scale), style="Accent.Horizontal.TScale",
                  command=lambda value: opacity_label.config(text=f"{int(float(value))}%")).pack(side="left")
        opacity_label.pack(side="left", padx=(8, 0))
        form_row(2, "Window opacity", opacity_frame)
        size_frame = tk.Frame(form, bg=theme["bg"])
        ttk.Spinbox(size_frame, from_=560, to=1400, increment=20, textvariable=width_var, width=6,
                    font=fonts["base"]).pack(side="left")
        tk.Label(size_frame, text="  x  ", bg=theme["bg"], fg=theme["muted"], font=fonts["base"]).pack(side="left")
        ttk.Spinbox(size_frame, from_=480, to=1200, increment=20, textvariable=height_var, width=6,
                    font=fonts["base"]).pack(side="left")
        form_row(3, "Launcher size", size_frame)
        form_row(4, "", checkbox(form, "Show descriptions in the list", describe_var))

        # --- Sources
        page = pages["Sources"]
        section(page, "Where skills & agents come from",
                f"Folders are scanned for SKILL.md skills, agents/*.md, commands and rules files. "
                f"Imported items go to your library: {LIBRARY_DIR}")
        sources = list(draft_config.get("sources", DEFAULT_SOURCES))
        list_frame = tk.Frame(page, bg=theme["surface"], highlightthickness=1, highlightbackground=theme["border"])
        list_frame.pack(fill="both", expand=True)
        source_list = tk.Listbox(list_frame, bg=theme["surface"], fg=theme["text"], font=fonts["small"],
                                 selectbackground=theme["selection"], selectforeground=theme["text"],
                                 relief="flat", bd=0, highlightthickness=0, activestyle="none")
        source_list.pack(fill="both", expand=True, padx=8, pady=6)
        counts_by_source = {}
        for item in self.items:
            for raw in sources:
                root_path = str(expand(raw)).lower()
                if str(item.path).lower().startswith(root_path):
                    counts_by_source[raw] = counts_by_source.get(raw, 0) + 1
                    break

        def fill_sources():
            source_list.delete(0, "end")
            for raw in sources:
                exists = expand(raw).exists()
                count = counts_by_source.get(raw, 0)
                marker = f"{count:>3}" if exists else "  -"
                source_list.insert("end", f" {marker}   {raw}")
                if not exists:
                    source_list.itemconfig("end", fg=theme["muted"])

        def add_source():
            window.attributes("-topmost", False)
            chosen = filedialog.askdirectory(parent=window, title="Add a folder with skills or agents")
            if chosen and chosen not in sources:
                sources.append(chosen)
                fill_sources()

        def remove_source():
            selection = source_list.curselection()
            if selection:
                sources.pop(selection[0])
                fill_sources()

        def open_source():
            selection = source_list.curselection()
            if selection and expand(sources[selection[0]]).exists():
                target = expand(sources[selection[0]])
                os.startfile(str(target if target.is_dir() else target.parent))

        fill_sources()
        source_buttons = tk.Frame(page, bg=theme["bg"])
        source_buttons.pack(fill="x", pady=(10, 0))
        FlatButton(source_buttons, "Add folder...", add_source, theme, fonts["base"]).pack(side="left")
        FlatButton(source_buttons, "Remove", remove_source, theme, fonts["base"]).pack(side="left", padx=8)
        FlatButton(source_buttons, "Open", open_source, theme, fonts["base"]).pack(side="left")
        FlatButton(source_buttons, "Reset to defaults",
                   lambda: (sources.clear(), sources.extend(DEFAULT_SOURCES), fill_sources()),
                   theme, fonts["base"], "subtle").pack(side="right")

        # --- Models
        page = pages["Models"]
        section(page, "Providers",
                "Leave the key empty to use the environment variable. Keys typed here are stored in plain text "
                "in config.json on this PC. Models: comma-separated (local servers are auto-detected).")
        providers_frame = tk.Frame(page, bg=theme["bg"])
        providers_frame.pack(fill="x")
        provider_fields = {}
        tk.Label(providers_frame, text="Provider", bg=theme["bg"], fg=theme["muted"], font=fonts["small"]).grid(
            row=0, column=0, sticky="w")
        tk.Label(providers_frame, text="API key", bg=theme["bg"], fg=theme["muted"], font=fonts["small"]).grid(
            row=0, column=1, sticky="w", padx=8)
        tk.Label(providers_frame, text="Models", bg=theme["bg"], fg=theme["muted"], font=fonts["small"]).grid(
            row=0, column=2, sticky="w")
        for row, (name, provider) in enumerate(draft_config["providers"].items(), start=1):
            env_name = provider.get("api_key_env", "")
            env_set = bool(env_name and os.environ.get(env_name))
            enabled_var = tk.BooleanVar(value=not provider.get("disabled", False))
            checkbox(providers_frame, name, enabled_var).grid(row=row, column=0, sticky="w", pady=3)
            if provider.get("auto_models"):
                hint_text = "local - no key needed"
            elif env_set:
                hint_text = f"using {env_name}"
            else:
                hint_text = f"paste key or set {env_name}"
            key_box = InputBox(providers_frame, theme, fonts["small"], hint_text, show="\u2022")
            stored_key = draft.get("providers", {}).get(name, {}).get("api_key", "")
            if not provider.get("auto_models"):
                key_box.set(stored_key)
            key_box.frame.grid(row=row, column=1, sticky="we", padx=8, pady=3)
            models_box = InputBox(providers_frame, theme, fonts["small"],
                                  "auto-detected" if provider.get("auto_models") else "model ids")
            models_box.set(", ".join(provider.get("models", [])))
            models_box.frame.grid(row=row, column=2, sticky="we", pady=3)
            provider_fields[name] = (enabled_var, key_box, models_box)
        providers_frame.columnconfigure(1, weight=1)
        providers_frame.columnconfigure(2, weight=2)
        section(page, "Default model")
        default_model_var = tk.StringVar(value=draft_config.get("default_model", ""))
        ttk.Combobox(page, textvariable=default_model_var, values=[""] + self.models, width=40,
                     font=fonts["base"]).pack(anchor="w")

        # --- Input
        page = pages["Input"]
        section(page, "Trigger", "The mouse button is captured globally while SkillMouse runs. "
                "You can also map any button in Logitech / Razer software to the hotkey and choose 'none'.")
        input_form = tk.Frame(page, bg=theme["bg"])
        input_form.pack(anchor="w")
        mouse_var = tk.StringVar(value=draft_config.get("mouse_button", "x2"))
        hotkey_var = tk.StringVar(value=draft_config.get("hotkey", "ctrl+alt+space"))
        autocopy_var = tk.BooleanVar(value=bool(draft_config.get("auto_copy_selection", True)))
        context_var = tk.IntVar(value=int(draft_config.get("max_context_chars", 60000)))
        mouse_labels = {"x2": "Forward side button (x2)", "x1": "Back side button (x1)",
                        "middle": "Middle click", "none": "None (hotkey only)"}
        mouse_display = tk.StringVar(value=mouse_labels.get(mouse_var.get(), mouse_var.get()))
        drag_labels = {"ctrl": "Ctrl + drag", "alt": "Alt + drag", "shift": "Shift + drag", "none": "Off"}
        drag_display = tk.StringVar(value=drag_labels.get(draft_config.get("drag_modifier", "ctrl"), "Ctrl + drag"))

        def input_row(row, label, widget):
            tk.Label(input_form, text=label, bg=theme["bg"], fg=theme["muted"], font=fonts["base"]).grid(
                row=row, column=0, sticky="w", pady=6, padx=(0, 16))
            widget.grid(row=row, column=1, sticky="w", pady=6)

        input_row(0, "Mouse button", ttk.Combobox(input_form, textvariable=mouse_display, state="readonly",
                                                  values=list(mouse_labels.values()), width=28, font=fonts["base"]))
        drag_note = "" if DND_AVAILABLE else "  (needs: pip install tkinterdnd2)"
        input_row(1, "Drag gesture" + drag_note,
                  ttk.Combobox(input_form, textvariable=drag_display, state="readonly",
                               values=list(drag_labels.values()), width=28, font=fonts["base"]))
        hotkey_box = InputBox(input_form, theme, fonts["base"], "e.g. ctrl+alt+space")
        hotkey_box.var = hotkey_var
        hotkey_box.entry.configure(textvariable=hotkey_var)
        input_row(2, "Hotkey", hotkey_box.frame)
        input_row(3, "", checkbox(input_form, "Grab the selected text automatically (sends Ctrl+C)", autocopy_var))
        input_row(4, "Max skill context (chars)", ttk.Spinbox(input_form, from_=8000, to=400000, increment=8000,
                                                              textvariable=context_var, width=10, font=fonts["base"]))

        # --- footer
        footer = tk.Frame(rounded.body, bg=theme["bg"])
        footer.pack(side="bottom", fill="x", padx=24, pady=(8, 14), before=shell)

        def save():
            mouse_reverse = {label: key for key, label in mouse_labels.items()}
            draft["ui"] = {
                **ui,
                "theme": theme_var.get(),
                "accent": accent_var.get(),
                "font": font_var.get(),
                "font_size": int(size_var.get()),
                "opacity": max(0.7, min(1.0, opacity_var.get() / 100)),
                "width": int(width_var.get()),
                "height": int(height_var.get()),
                "show_descriptions": bool(describe_var.get()),
            }
            draft["sources"] = list(sources)
            draft["mouse_button"] = mouse_reverse.get(mouse_display.get(), "x2")
            draft["drag_modifier"] = {v: k for k, v in drag_labels.items()}.get(drag_display.get(), "ctrl")
            draft["hotkey"] = hotkey_var.get().strip() or "ctrl+alt+space"
            draft["auto_copy_selection"] = bool(autocopy_var.get())
            draft["max_context_chars"] = int(context_var.get())
            draft["default_model"] = default_model_var.get()
            draft.setdefault("providers", {})
            for name, (enabled_var, key_box, models_box) in provider_fields.items():
                stored = draft["providers"].setdefault(name, {})
                stored["disabled"] = not enabled_var.get()
                key = key_box.get().strip()
                if key and not draft_config["providers"][name].get("auto_models"):
                    stored["api_key"] = key
                else:
                    stored.pop("api_key", None) if not draft_config["providers"][name].get("auto_models") else None
                if not draft_config["providers"][name].get("auto_models"):
                    stored["models"] = [m.strip() for m in models_box.get().split(",") if m.strip()]
            draft["version"] = CONFIG_VERSION
            save_json(CONFIG_PATH, draft)
            window.destroy()
            self.settings_window = None
            self.apply_settings()

        def cancel():
            window.destroy()
            self.settings_window = None
            if self.popup and self.popup.winfo_exists():
                self.popup.attributes("-topmost", True)

        FlatButton(footer, "Save", save, theme, fonts["bold"], "primary").pack(side="right")
        FlatButton(footer, "Cancel", cancel, theme, fonts["base"]).pack(side="right", padx=(0, 8))
        tk.Label(footer, text=f"Config: {CONFIG_PATH}", bg=theme["bg"], fg=theme["muted"],
                 font=fonts["small"]).pack(side="left")
        window.bind("<Escape>", lambda e: cancel())
        window.protocol("WM_DELETE_WINDOW", cancel)
        show_page("Appearance")
        self.settings_api = {"theme_var": theme_var, "size_var": size_var, "save": save, "cancel": cancel,
                             "window": window}
        rounded.present(880, 680)

    def apply_settings(self):
        old = (self.config.get("hotkey"), self.config.get("mouse_button"), self.config.get("drag_modifier"))
        reopen = self.popup is not None and self.popup.winfo_exists()
        self.close_popup()
        self.config = load_config()
        self.apply_theme()
        self.refresh()
        if (self.config.get("hotkey"), self.config.get("mouse_button"), self.config.get("drag_modifier")) != old:
            self.start_listener()
        if reopen:
            self.root.after(150, lambda: self.show_popup(user32.GetForegroundWindow(), ""))

    # ---- self-test: drives the real UI with injected input against a helper window in another process
    def start_selftest(self):
        threading.Thread(target=self._selftest_worker, daemon=True).start()

    def _selftest_worker(self):
        results = []

        def record(name, passed, detail=""):
            results.append({"test": name, "passed": bool(passed), "detail": str(detail)[:240]})

        temp = Path(tempfile.mkdtemp(prefix="skillmouse_selftest_"))
        config_backup = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
        state_backup = STATE_PATH.read_bytes() if STATE_PATH.exists() else None
        clipboard_backup = get_clipboard_text()
        helper = None
        state_file = temp / "helper_state.json"
        stop_file = temp / "stop"
        imported = LIBRARY_DIR / "agents" / "selftest-agent.md"
        try:
            self.listener.accept_injected = True
            self.fake_reply_for_tests = "SELFTEST REPLY OK"
            helper_script = temp / "helper.py"
            helper_script.write_text(SELFTEST_HELPER, encoding="utf-8")
            helper = subprocess.Popen([sys.executable, str(helper_script), str(state_file), str(stop_file)])
            helper_state = wait_for(lambda: load_json(state_file, None), 12)
            if not helper_state:
                raise RuntimeError("test helper window did not start")
            helper_hwnd = helper_state["hwnd"]

            def activate_helper():
                label_x, label_y, label_w, label_h = load_json(state_file, {})["label"]
                inject_move(label_x + label_w // 2, label_y + label_h // 2)
                time.sleep(0.15)
                inject_mouse(0x0002)   # click the label: activates the window, keeps the text selection
                time.sleep(0.05)
                inject_mouse(0x0004)
                return wait_for(lambda: user32.GetForegroundWindow() == helper_hwnd, 3)

            # 1. mouse forward button + automatic selection grab
            if not activate_helper():
                raise RuntimeError("could not focus the test window - stopped before sending any keys")
            time.sleep(0.3)
            inject_mouse(0x0080, 2)   # XDOWN, XBUTTON2
            inject_mouse(0x0100, 2)   # XUP
            opened = wait_for(lambda: self.ui_call(lambda: bool(self.popup and self.popup.winfo_exists())), 6)
            grabbed = self.ui_call(lambda: self.popup_api["input"].get()) if opened else ""
            record("Mouse forward button opens the launcher", opened)
            record("Selected text is grabbed into the input box", "hello from the test window" in grabbed, grabbed)

            # 2. run from the launcher, then Insert into app
            if opened:
                def run_first():
                    if not self.popup_api["model_var"].get():
                        self.popup_api["model_var"].set("selftest:fake")
                    self.popup_api["run"]()

                self.ui_call(run_first)
                finished = wait_for(lambda: self.ui_call(lambda: bool(self.last_result)
                                                         and not self.last_result["conversation"]["busy"]
                                                         and any(m["role"] == "assistant" for m in
                                                                 self.last_result["conversation"]["messages"])), 10)
                record("Run shows the answer in the result window", finished)
                if finished and self.last_trigger_target != helper_hwnd:
                    record("Insert into app pastes the answer into the source window", False,
                           "skipped: launcher was not opened from the test window")
                elif finished:
                    self.ui_call(lambda: self.last_result["insert"]())
                    inserted = wait_for(lambda: "SELFTEST REPLY OK" in load_json(state_file, {}).get("text", ""), 6)
                    record("Insert into app pastes the answer into the source window", inserted,
                           load_json(state_file, {}).get("text", ""))

            # 3. Settings > Save
            self.ui_call(self.close_popup)
            self.ui_call(self.open_settings)

            def change_and_save():
                self.settings_api["theme_var"].set("Nord")
                self.settings_api["size_var"].set(11)
                self.settings_api["save"]()

            self.ui_call(change_and_save)
            saved_ui = load_json(CONFIG_PATH, {}).get("ui", {})
            applied = self.ui_call(lambda: self.theme["bg"] == THEMES["Nord"]["bg"]
                                   and int(self.fonts["base"].cget("size")) == 11)
            record("Settings > Save writes config.json", saved_ui.get("theme") == "Nord"
                   and saved_ui.get("font_size") == 11, saved_ui)
            record("Saved settings are applied immediately", applied)
            if config_backup is not None:
                CONFIG_PATH.write_bytes(config_backup)

            def reload_config():
                self.close_popup()
                self.config = load_config()
                self.apply_theme()

            self.ui_call(reload_config)

            # 4. Import menu (native file dialog replaced by a fixed answer)
            test_file = temp / "selftest-agent.md"
            test_file.write_text("---\nname: selftest-agent\ndescription: Temporary agent for the self-test.\n"
                                 "mode: subagent\n---\n\nYou are a test agent.\n", encoding="utf-8")
            self.ui_call(lambda: self.show_popup(helper_hwnd, ""))
            labels = self.ui_call(lambda: [entry[0] for entry in self.popup_api["import_entries"] if entry])
            record("Import menu lists its actions", len(labels) == 5, labels)
            original_dialog = filedialog.askopenfilenames
            filedialog.askopenfilenames = lambda **kwargs: (str(test_file),)
            try:
                entry = next(e for e in self.popup_api["import_entries"] if e and e[0].startswith("Import .md"))
                self.ui_call(entry[1])
            finally:
                filedialog.askopenfilenames = original_dialog
            listed = self.ui_call(lambda: "selftest-agent" in self.popup_api["visible_names"]())
            record("Imported agent is copied to the library and listed", listed and imported.exists())
            if imported.exists():
                imported.unlink()

            def refresh_and_close():
                self.refresh()
                self.close_popup()

            self.ui_call(refresh_and_close)

            # 5. Ctrl+drag -> donut -> drop on a slice
            if not self.donut:
                record("Ctrl+drag donut", False, "tkinterdnd2 not installed")
            else:
                if not activate_helper():
                    raise RuntimeError("could not focus the test window before the drag test")
                time.sleep(0.3)
                helper_state = load_json(state_file, {})
                label_x, label_y, label_w, label_h = helper_state["label"]
                start_x, start_y = label_x + label_w // 2, label_y + label_h // 2
                self.last_drop = None
                inject_move(start_x, start_y)
                time.sleep(0.3)
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                time.sleep(0.05)
                inject_mouse(0x0002)   # LEFTDOWN
                time.sleep(0.15)
                for step in range(1, 9):
                    inject_move(start_x + 6 * step, start_y + 2 * step)
                    time.sleep(0.04)
                shown = wait_for(lambda: self.ui_call(lambda: self.donut.visible), 3)
                record("Ctrl+drag shows the skill donut at the cursor", shown)
                hovered = None
                expected = None
                if shown:
                    target_x, target_y = self.ui_call(lambda: self.donut.slice_center_screen(1))
                    expected = self.ui_call(lambda: self.donut.face_items()[1].name)
                    from_x, from_y = start_x + 48, start_y + 16
                    for step in range(1, 21):
                        inject_move(int(from_x + (target_x - from_x) * step / 20),
                                    int(from_y + (target_y - from_y) * step / 20))
                        time.sleep(0.05)
                    time.sleep(0.6)
                    hovered = self.ui_call(lambda: self.donut.hover)
                inject_mouse(0x0004)   # LEFTUP
                time.sleep(0.05)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                if shown:
                    record("Hovering a slice highlights it", hovered == 1, hovered)
                    dropped = wait_for(lambda: self.last_drop, 6)
                    record("Dropping on a slice runs that skill with the dragged content",
                           bool(dropped) and dropped["item"] == expected
                           and "dragged text payload" in dropped["text"], dropped)
                    wait_for(lambda: self.ui_call(lambda: bool(self.last_result)
                                                  and not self.last_result["conversation"]["busy"]), 6)
                    self.ui_call(lambda: self.last_result["window"].destroy()
                                 if self.last_result and self.last_result["window"].winfo_exists() else None)

                # 6. wheel + Tab flip the donut (Tab lands in the focused test window, nowhere else)
                if not activate_helper():
                    raise RuntimeError("could not focus the test window before the Tab test")
                self.ui_call(lambda: self.donut.show(900, 520, None))
                time.sleep(0.3)
                before = self.ui_call(lambda: self.donut.face)
                inject_mouse(0x0800, -120)   # WHEEL down
                flipped = wait_for(lambda: self.ui_call(lambda: self.donut.face) != before, 3)
                record("Mouse wheel flips the donut to the next set", flipped)
                before = self.ui_call(lambda: self.donut.face)
                if user32.GetForegroundWindow() != helper_hwnd:
                    raise RuntimeError("test window lost focus - Tab not sent")
                user32.keybd_event(VK_TAB, 0, 0, 0)
                time.sleep(0.12)
                user32.keybd_event(VK_TAB, 0, KEYEVENTF_KEYUP, 0)
                tabbed = wait_for(lambda: self.ui_call(lambda: self.donut.face) != before, 3)
                record("Tab flips the donut to the next set", tabbed)
                self.ui_call(self.donut.hide)
        except Exception as error:
            record("Self-test harness", False, repr(error))
        finally:
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            stop_file.touch()
            if helper:
                try:
                    helper.wait(timeout=5)
                except Exception:
                    helper.kill()
            if config_backup is not None:
                CONFIG_PATH.write_bytes(config_backup)
            if state_backup is not None:
                STATE_PATH.write_bytes(state_backup)
            if clipboard_backup is not None:
                set_clipboard_text(clipboard_backup)
            if imported.exists():
                imported.unlink()
            self.listener.accept_injected = False
            self.fake_reply_for_tests = None
            shutil.rmtree(temp, ignore_errors=True)
            report = {"passed": sum(1 for r in results if r["passed"]), "total": len(results), "results": results}
            save_json(APP_DIR / "selftest_report.json", report)
            print(json.dumps(report, indent=2), flush=True)
            self.events.put(("call", self.quit, {}, threading.Event()))

    def quit(self):
        if self.listener:
            self.listener.stop()
        self.root.after(100, self.root.destroy)

    def run(self):
        self.root.mainloop()


# =========================================================================== CLI

def find_item(items, name):
    if name.lower() in ("ask", "none", ""):
        return ASK_ITEM
    for item in items:
        if item.name.lower() == name.lower():
            return item
    for item in items:
        if name.lower() in item.name.lower():
            return item
    raise SystemExit(f"Not found: {name}")


DEMO_REPLY = """## Review: `avg(xs)`

**Verdict:** works for normal input, but has one real bug.

### Findings
1. **[P1] Empty list crash** - `avg([])` raises `ZeroDivisionError`.
2. **[P3] Naming** - `xs` is fine for math code; consider `values` in app code.

### Suggested fix
```python
def avg(values):
    if not values:
        raise ValueError("avg() of empty sequence")
    return sum(values) / len(values)
```

- Keeps the original behaviour for non-empty input
- Fails loudly with a clear message instead of a math error
"""


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run Claude/Codex/OpenCode skills and agents with any model.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--prompt")
    parser.add_argument("--ask")
    parser.add_argument("--model")
    parser.add_argument("--text", default="")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--import", dest="import_path")
    parser.add_argument("--demo", choices=["popup", "settings", "result", "donut"], help="open a window immediately")
    parser.add_argument("--selftest", action="store_true", help="drive the real UI with injected input and report")
    args = parser.parse_args()

    if args.import_path:
        print("\n".join(import_into_library(args.import_path)) or "Nothing importable found.")
        return
    if args.list or args.models or args.prompt or args.ask:
        config = load_config()
        items = discover_items(config)
        if args.list:
            for item in items:
                print(f"[{KIND_LABEL[item.kind]:5}] {item.name:32} {item.source:10} {item.path}")
            summary = {label: sum(1 for i in items if i.kind == kind) for kind, label in (("skill", "skills"), ("agent", "agents"), ("command", "commands"), ("rules", "rules"))}
            print(f"\n{len(items)} items: " + ", ".join(f"{v} {k}" for k, v in summary.items()))
        if args.models:
            print("\n".join(available_models(config)) or "No models: add an API key or start Ollama / LM Studio.")
        if args.prompt:
            item = find_item(items, args.prompt)
            print(build_system_prompt(item, args.instruction, int(config["max_context_chars"])))
        if args.ask:
            item = find_item(items, args.ask)
            model = args.model or (available_models(config) or [None])[0]
            if not model:
                raise SystemExit("No model available.")
            messages = [
                {"role": "system", "content": build_system_prompt(item, args.instruction, int(config["max_context_chars"]))},
                {"role": "user", "content": build_user_message(args.text, args.instruction)},
            ]

            def show(piece, kind):
                target = sys.stderr if kind == "reasoning" else sys.stdout
                print(piece, end="", flush=True, file=target)

            stream_chat(config, model, messages, show, threading.Event())
            print()
        return

    mutex = kernel32.CreateMutexW(None, False, "SkillMouse_single_instance")
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        print("SkillMouse is already running.")
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = SkillMouseApp()
    print(f"SkillMouse running: {app.status_line()}", flush=True)
    if args.selftest:
        app.root.after(800, app.start_selftest)
    elif args.demo == "donut" and app.donut:
        def show_demo_donut():
            x, y = app.root.winfo_pointerxy()
            left, top, right, bottom = work_area_at(x, y)
            app.donut.show((left + right) // 2, (top + bottom) // 2, None)
            app.donut.hover = 1
            app.donut.draw()
        app.root.after(800, show_demo_donut)
    elif args.demo == "popup":
        app.root.after(600, lambda: app.show_popup(user32.GetForegroundWindow(), "def avg(xs): return sum(xs)/len(xs)"))
    elif args.demo == "settings":
        app.root.after(600, app.open_settings)
    elif args.demo == "result":
        demo_item = next((i for i in app.items if i.name == "review-agent"), ASK_ITEM)
        app.root.after(600, lambda: app.open_result(demo_item, "ollama:qwen3:8b", "def avg(xs): ...", "",
                                                    user32.GetForegroundWindow(), fake_reply=DEMO_REPLY))
    app.run()
    del mutex


if __name__ == "__main__":
    main()

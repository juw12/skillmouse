"""Unit tests for SkillMouse's pure logic: discovery parsing, prompt building, hotkeys, colours.

SkillMouse loads user32 at import time, so these run on Windows (locally and in CI).
Run: python -m pytest tests -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import skillmouse as sm  # noqa: E402


# ---------------------------------------------------------------- front matter

def test_frontmatter_basic_keys_and_body():
    meta, body = sm.parse_frontmatter("---\nname: Refine\ndescription: \"Loop until done\"\n---\nBody text\n")
    assert meta == {"name": "Refine", "description": "Loop until done"}
    assert body == "Body text\n"


def test_frontmatter_folded_block_and_bom_and_crlf():
    text = "\ufeff---\r\nname: x\r\ndescription: >\r\n  first line\r\n  second line\r\n---\r\nrest"
    meta, body = sm.parse_frontmatter(text)
    assert meta["description"] == "first line second line"
    assert meta["name"] == "x"
    assert body == "rest"


def test_frontmatter_absent_returns_text_unchanged():
    meta, body = sm.parse_frontmatter("# Just a heading\nno front matter")
    assert meta == {}
    assert body == "# Just a heading\nno front matter"


def test_first_meaningful_line_skips_markup():
    assert sm.first_meaningful_line("\n\n## Summary here\nmore") == "Summary here"
    assert sm.first_meaningful_line("> quoted intro\n") == "quoted intro"
    assert sm.first_meaningful_line("- bullet first") == "bullet first"
    assert sm.first_meaningful_line("---\n\n") == ""


# ---------------------------------------------------------------- discovery

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_make_item_skill_uses_frontmatter_name(tmp_path):
    skill = _write(tmp_path / "my-skill" / "SKILL.md", "---\nname: Pretty Name\ndescription: Does a thing\n---\nSteps")
    item = sm.make_item(skill, "skill")
    assert (item.name, item.description, item.kind) == ("Pretty Name", "Does a thing", "skill")
    assert len(item.key) == 40  # sha1 of the file text


def test_make_item_skill_falls_back_to_folder_and_first_line(tmp_path):
    skill = _write(tmp_path / "folder-name" / "SKILL.md", "# Title line\nDetails")
    item = sm.make_item(skill, "skill")
    assert item.name == "folder-name"
    assert item.description == "Title line"


def test_make_item_command_and_agent_names(tmp_path):
    command = _write(tmp_path / "commands" / "review.md", "Review $ARGUMENTS")
    agent = _write(tmp_path / "agents" / "critic.agent.md", "---\ndescription: Harsh critic\n---\nBe harsh")
    assert sm.make_item(command, "command").name == "/review"
    assert sm.make_item(agent, "agent").name == "critic"


def test_classify_markdown(tmp_path):
    agent = _write(tmp_path / "x" / "a.md", "---\ntools: read\n---\nbody")
    command = _write(tmp_path / "y" / "b.md", "Do $ARGUMENTS now")
    skill = _write(tmp_path / "z" / "c.md", "---\nname: c\n---\nplain")
    in_agents_dir = _write(tmp_path / "agents" / "d.md", "plain")
    assert sm.classify_markdown(agent) == "agent"
    assert sm.classify_markdown(command) == "command"
    assert sm.classify_markdown(skill) == "skill"
    assert sm.classify_markdown(in_agents_dir) == "agent"


def test_unique_path_numbers_collisions(tmp_path):
    target = tmp_path / "skill.md"
    assert sm.unique_path(target) == target
    target.write_text("x")
    assert sm.unique_path(target) == tmp_path / "skill-2.md"
    (tmp_path / "skill-2.md").write_text("x")
    assert sm.unique_path(target) == tmp_path / "skill-3.md"


# ---------------------------------------------------------------- prompts

def test_build_user_message():
    assert sm.build_user_message("", "") == "Begin."
    assert sm.build_user_message("  hello ", "") == "Input text:\n<<<\nhello\n>>>"
    assert sm.build_user_message("sel", "Translate") == "Translate\n\nInput text:\n<<<\nsel\n>>>"


def test_build_system_prompt_builtin():
    assert "helpful" in sm.build_system_prompt(sm.ASK_ITEM, "", 1000)


def test_build_system_prompt_command_substitutes_arguments(tmp_path):
    command = _write(tmp_path / "commands" / "fix.md", "---\ndescription: Fix it\n---\nFix $ARGUMENTS then $1 done")
    item = sm.make_item(command, "command")
    prompt = sm.build_system_prompt(item, "the bug", 10000)
    assert "Fix the bug then  done" in prompt
    assert "$ARGUMENTS" not in prompt
    assert "# Slash command: /fix" in prompt


def test_build_system_prompt_skill_respects_budget(tmp_path):
    skill_dir = tmp_path / "budget-skill"
    skill = _write(skill_dir / "SKILL.md", "---\nname: B\ndescription: d\n---\nMain body")
    _write(skill_dir / "reference.md", "R" * 50)
    _write(skill_dir / "huge.md", "H" * 50000)
    item = sm.make_item(skill, "skill")
    prompt = sm.build_system_prompt(item, "", 5000)
    assert "Main body" in prompt
    assert "Bundled file: reference.md" in prompt
    assert "H" * 1000 not in prompt
    assert "context budget reached: huge.md" in prompt


def test_build_system_prompt_agent(tmp_path):
    agent = _write(tmp_path / "agents" / "coach.md", "---\nname: Coach\ndescription: Encourages\n---\nBe kind.")
    prompt = sm.build_system_prompt(sm.make_item(agent, "agent"), "", 1000)
    assert "# Agent: Coach" in prompt
    assert prompt.rstrip().endswith("Be kind.")


# ---------------------------------------------------------------- hotkeys

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Ctrl+Alt+Space", (0x4000 | 0x2 | 0x1, 0x20)),
        ("shift + f5", (0x4000 | 0x4, 0x74)),
        ("win+F24", (0x4000 | 0x8, 0x87)),
        ("ctrl+k", (0x4000 | 0x2, ord("K"))),
        ("ctrl+`", (0x4000 | 0x2, 0xC0)),
    ],
)
def test_parse_hotkey(text, expected):
    assert sm.parse_hotkey(text) == expected


def test_parse_hotkey_without_key():
    assert sm.parse_hotkey("ctrl+alt") == (0x4000 | 0x2 | 0x1, None)


# ---------------------------------------------------------------- colours

def test_colour_helpers():
    assert sm.hex_to_rgb("#ff8000") == (255, 128, 0)
    assert sm.rgb_to_hex((300, -5, 127.6)) == "#ff0080"
    assert sm.blend("#000000", "#ffffff", 0.5) == "#808080"
    assert sm.luminance("#ffffff") == pytest.approx(1.0)
    assert sm.luminance("#000000") == 0

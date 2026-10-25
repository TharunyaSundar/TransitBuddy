"""Load the agent's skills from src/skills/*/SKILL.md and pick the ones relevant to a message.

A SKILL.md has '## Section' headings (Name, Description, Activation conditions, Rules and constraints, ...).
Every skill's one-line description always goes into the prompt; the full rules only for the selected skills,
to keep prompts short for small models.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    id: str
    name: str
    description: str
    sections: dict[str, str]
    keywords: set[str] = field(default_factory=set)

    def full_text(self) -> str:
        keep = ("Rules and constraints", "Tools needed", "Expected outputs", "Steps")
        body = "\n".join(f"{k}:\n{v}" for k, v in self.sections.items() if k in keep)
        return f"### {self.name}\n{self.description}\n{body}"


def parse_skill(skill_id: str, text: str) -> Skill:
    sections: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = m.group(1)
            sections[current] = ""
        elif current:
            sections[current] += line + "\n"
    sections = {k: v.strip() for k, v in sections.items()}
    name = sections.get("Name") or skill_id
    kw_src = " ".join([sections.get("Keywords", ""), sections.get("Activation conditions", ""),
                       sections.get("Example user requests", "")]).lower()
    keywords = {w for w in re.findall(r"[a-z][a-z'-]{2,}", kw_src)} - _STOP
    return Skill(skill_id, name, sections.get("Description", ""), sections, keywords)


_STOP = {"the", "and", "for", "user", "asks", "student", "students", "with", "that", "are", "can", "when", "there",
         "multiple", "requires", "around", "specific", "time", "times", "about", "this", "you", "your", "our",
         "any", "anyone", "who", "what", "here", "into", "same", "wants", "want", "uploads", "appears"}


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    return [parse_skill(p.parent.name, p.read_text()) for p in sorted(Path(skills_dir).glob("*/SKILL.md"))]


def select_skills(skills: list[Skill], message: str, limit: int = 2) -> list[Skill]:
    words = set(re.findall(r"[a-z][a-z'-]{2,}", message.lower()))
    scored = sorted(((len(words & s.keywords), s) for s in skills), key=lambda x: -x[0])
    return [s for score, s in scored[:limit] if score > 0]


def skills_prompt(skills: list[Skill], selected: list[Skill]) -> str:
    lines = ["SKILLS:"] + [f"- {s.name}: {s.description}" for s in skills]
    for s in selected:
        lines.append("\n" + s.full_text())
    return "\n".join(lines)

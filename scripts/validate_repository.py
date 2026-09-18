#!/usr/bin/env python3
"""Validate the structure and local links of the legal knowledge base."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ("法律法规", "实务操作", "案例参考", "参考资料")
IGNORED_TOP_LEVEL = {".git", ".github", "scripts", "drafts"}
LINK_RE = re.compile(r"!?\[[^]]*\]\((?:<([^>]+)>|([^\s)]+))[^)]*\)")
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def topic_directories() -> list[Path]:
    """Return directories that look like knowledge-base topics."""
    return sorted(
        path
        for path in ROOT.iterdir()
        if path.is_dir()
        and path.name not in IGNORED_TOP_LEVEL
        and not path.name.startswith(".")
        and (path / "README.md").is_file()
    )


def links_in(text: str) -> list[str]:
    return [match.group(1) or match.group(2) for match in LINK_RE.finditer(text)]


def markdown_links(path: Path) -> list[str]:
    return links_in(path.read_text(encoding="utf-8"))


def section(text: str, heading: str) -> str | None:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return None
    end = text.find("\n## ", start + len(marker))
    return text[start:] if end < 0 else text[start:end]


def local_target(source: Path, destination: str) -> Path | None:
    if destination.startswith(("http://", "https://", "mailto:", "tel:", "#")):
        return None
    path_part = unquote(destination.split("#", 1)[0].split("?", 1)[0])
    if not path_part:
        return None
    return (source.parent / path_part).resolve()


def validate() -> list[str]:
    errors: list[str] = []
    topics = topic_directories()
    candidate_topics = sorted(
        path
        for path in ROOT.iterdir()
        if path.is_dir()
        and path.name not in IGNORED_TOP_LEVEL
        and not path.name.startswith(".")
    )
    for path in candidate_topics:
        if not (path / "README.md").is_file():
            errors.append(f"顶层目录 {path.name} 缺少 README.md，无法识别为知识库专题")
    if not topics:
        errors.append("未发现知识库专题目录")
        return errors

    markdown_files = sorted(ROOT.rglob("*.md"))
    markdown_files = [path for path in markdown_files if ".git" not in path.parts]

    for path in markdown_files:
        for destination in markdown_links(path):
            target = local_target(path, destination)
            if target is not None and not target.exists():
                errors.append(
                    f"断链：{path.relative_to(ROOT)} -> {destination}"
                )

    root_readme = ROOT / "README.md"
    if not root_readme.is_file():
        errors.append("仓库根目录缺少 README.md")
    else:
        navigation = section(
            root_readme.read_text(encoding="utf-8"), "📖 知识库导航"
        )
        if navigation is None:
            errors.append("根 README.md 缺少“📖 知识库导航”章节")
        else:
            linked_topics = {
                target.parent
                for destination in links_in(navigation)
                if (target := local_target(root_readme, destination)) is not None
                and target.name == "README.md"
                and target.parent.parent == ROOT
            }
            expected_topics = {topic.resolve() for topic in topics}
            for path in sorted(expected_topics - linked_topics):
                errors.append(f"根导航遗漏专题：{path.name}")
            for path in sorted(linked_topics - expected_topics):
                errors.append(f"根导航包含未知专题：{path.name}")

    for topic in topics:
        actual_directories = {
            path.name for path in topic.iterdir() if path.is_dir()
        }
        unexpected = actual_directories - set(CATEGORIES)
        missing = set(CATEGORIES) - actual_directories
        if unexpected:
            errors.append(
                f"{topic.name} 存在非标准分类目录：{', '.join(sorted(unexpected))}"
            )
        if missing:
            errors.append(
                f"{topic.name} 缺少分类目录：{', '.join(sorted(missing))}"
            )

        unexpected_files = {
            path.name
            for path in topic.iterdir()
            if path.is_file() and path.name != "README.md"
        }
        if unexpected_files:
            errors.append(
                f"{topic.name} 根目录存在非 README 文件："
                f"{', '.join(sorted(unexpected_files))}"
            )

        for category in CATEGORIES:
            category_path = topic / category
            if not category_path.is_dir():
                continue
            nested = [path for path in category_path.rglob("*") if path.is_dir()]
            for path in nested:
                errors.append(f"分类目录不应嵌套子目录：{path.relative_to(ROOT)}")
            non_markdown = [
                path
                for path in category_path.iterdir()
                if path.is_file() and path.suffix != ".md"
            ]
            for path in non_markdown:
                errors.append(f"分类目录包含非 Markdown 文件：{path.relative_to(ROOT)}")

        readme = topic / "README.md"
        readme_text = readme.read_text(encoding="utf-8")
        index = section(readme_text, "📁 目录结构")
        if index is None:
            errors.append(f"{topic.name}/README.md 缺少“📁 目录结构”章节")
            indexed_files: set[Path] = set()
        else:
            indexed_files = {
                target
                for destination in links_in(index)
                if (target := local_target(readme, destination)) is not None
                and target.suffix == ".md"
                and target != readme.resolve()
                and topic.resolve() in target.parents
            }

        content_files = {
            path.resolve()
            for category in CATEGORIES
            for path in (topic / category).glob("*.md")
        }
        for path in sorted(content_files - indexed_files):
            errors.append(
                f"索引遗漏：{path.relative_to(ROOT)} 未列入 {topic.name}/README.md"
            )
        for path in sorted(indexed_files - content_files):
            errors.append(
                f"索引异常：{topic.name}/README.md 索引了非内容文件 "
                f"{path.relative_to(ROOT)}"
            )

        required_readme_headings = {"📁 目录结构", "⚠️ 免责声明", "📄 许可"}
        readme_headings = set(H2_RE.findall(readme_text))
        for heading in sorted(required_readme_headings - readme_headings):
            errors.append(f"{topic.name}/README.md 缺少“{heading}”章节")

        for path in sorted(content_files):
            headings = set(H2_RE.findall(path.read_text(encoding="utf-8")))
            for heading in ("🔗 相关文件", "📄 许可"):
                if heading not in headings:
                    errors.append(
                        f"{path.relative_to(ROOT)} 缺少“{heading}”章节"
                    )

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"结构校验失败（{len(errors)} 项）：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    topics = topic_directories()
    content_count = sum(
        1
        for topic in topics
        for category in CATEGORIES
        for _ in (topic / category).glob("*.md")
    )
    print(
        f"结构校验通过：{len(topics)} 个专题，{content_count} 个内容文件，"
        "目录、索引、页脚和本地链接均符合约定。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

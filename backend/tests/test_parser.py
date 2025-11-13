import io
import zipfile
from pathlib import Path

from app.parser import ProjectParser


def build_sample_zip(tmp_path: Path) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "sample/module.py",
            "import os\n\n"
            "def foo():\n"
            "    bar()\n\n"
            "def bar():\n"
            "    pass\n",
        )
        archive.writestr(
            "sample/view.js",
            "import React from 'react';\n"
            "export function View() {\n"
            "  handleClick();\n"
            "}\n"
            "const handleClick = () => {};\n",
        )

    zip_path = tmp_path / "sample.zip"
    zip_path.write_bytes(buffer.getvalue())
    return zip_path


def test_parse_zip(tmp_path: Path) -> None:
    parser = ProjectParser()
    zip_path = build_sample_zip(tmp_path)

    data = parser.parse_zip(zip_path)

    assert "files" in data
    assert len(data["files"]) == 2
    python_file = next(item for item in data["files"] if item["language"] == "python")
    js_file = next(item for item in data["files"] if item["language"] == "javascript")

    assert python_file["functions"][0]["name"] == "foo"
    assert "React from 'react'" in js_file["imports"][0]




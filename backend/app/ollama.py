from __future__ import annotations

import os
import subprocess
from typing import Iterable


class OllamaClient:
    def __init__(self, model: str = "qwen2.5:3b", command: str = "ollama") -> None:
        # Use Phi-3 Mini as the default model
        self.model = model
        self.command = command

    def generate(self, prompt: str) -> str:
        mock_output = os.getenv("OLLAMA_MOCK_OUTPUT")
        if mock_output is not None:
            return mock_output

        print(f"[Ollama] Running model: {self.model}")

        process = subprocess.run(
            [self.command, "run", self.model],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Ollama command failed with exit code {process.returncode}:\n{stderr}"
            )

        return process.stdout.decode("utf-8", errors="ignore")


def stream_lines(output: Iterable[bytes]) -> str:
    return "".join(line.decode("utf-8", errors="ignore") for line in output)


__all__ = ["OllamaClient", "stream_lines"]

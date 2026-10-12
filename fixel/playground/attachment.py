"""The one shape both playground front-ends hand to Fixel: code plus its last run."""

from __future__ import annotations

from dataclasses import dataclass

OUTPUT_TAIL = 4_000  # characters of run output sent to the model


@dataclass(frozen=True)
class CodeAttachment:
    lang: str  # canonical language name (a key of LANGS)
    code: str
    output: str = ""
    exit_code: int | None = None  # None after a timeout
    ran: bool = False  # False: never run, or edited since the last run

    @property
    def failed(self) -> bool:
        return self.ran and self.exit_code != 0

    def default_question(self) -> str:
        return "Why doesn't this work?" if self.failed else "Review this code."

    def to_prompt_text(self) -> str:
        parts = [f"[Code from Fixel playground · {self.lang}]", f"```{self.lang}", self.code.rstrip("\n"), "```"]
        if self.ran:
            status = "timed out" if self.exit_code is None else f"exit {self.exit_code}"
            output = self.output.rstrip() or "(no output)"
            if len(output) > OUTPUT_TAIL:
                output = "…" + output[-OUTPUT_TAIL:]
            parts += [f"[Run output · {status}]", output]
        return "\n".join(parts)

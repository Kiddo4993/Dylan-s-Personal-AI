import json
from datetime import datetime, timedelta, timezone

from fixel import cli
from fixel.__main__ import main
from fixel.brain import ProviderError
from fixel.canvas.items import Assignment, Plan
from fixel.casefile import CaseFile
from fixel.config import Config


async def test_shot_prints_the_png_path_only(tmp_path, capsys):
    async def capture(dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"png")
        return b"png"

    assert await cli.shot(Config(home=tmp_path), str(tmp_path / "s.png"), capture) == 0
    out, err = capsys.readouterr()
    assert out.strip() == str((tmp_path / "s.png").resolve()) and "Drag over" in err


async def test_shot_exits_1_when_you_press_esc(tmp_path, capsys):
    async def cancelled(dest):
        return None

    assert await cli.shot(Config(home=tmp_path), None, cancelled) == 1
    out, err = capsys.readouterr()
    assert out == "" and "Cancelled" in err


def test_cases_json_lists_matches_with_whether_they_worked(tmp_path, capsys):
    casefile = CaseFile(tmp_path / "c.db")
    first = casefile.save(case_id=None, mode="error", key="ModuleNotFoundError: pandas", question="why", answer="pip install pandas", shot_paths=[], screen_text="")
    casefile.save(case_id=None, mode="math", key="related rates", question="ladder", answer="dx/dt", shot_paths=[], screen_text="")
    casefile.mark_worked(first)
    assert cli.cases(Config(home=tmp_path), ["pandas"], True, casefile) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["problem"] == "ModuleNotFoundError: pandas" and row["worked"] is True and row["answer"] == "pip install pandas"


def test_cases_without_words_shows_recent_ones(tmp_path, capsys):
    casefile = CaseFile(tmp_path / "c.db")
    casefile.save(case_id=None, mode="error", key="k", question="q", answer="a", shot_paths=[], screen_text="")
    cli.cases(Config(home=tmp_path), [], False, casefile)
    assert "error: k" in capsys.readouterr().out


class FakeCanvas:
    def __init__(self, cfg, ui, provider):
        self.ui, self.provider = ui, provider

    async def sync(self, *, table=True):
        self.ui.info("Checking Canvas (school)…")  # progress: must not land in the JSON on stdout
        due = datetime(2026, 11, 3, 23, 59, tzinfo=timezone.utc)
        a = Assignment("assignment-1", "Lab 1", "AP CSA", due, "https://x/1", 10, False)
        return [a], {"assignment-1": Plan("High", 1.5, (due - timedelta(days=1)).date(), "Start with part B.")}


async def test_canvas_json_is_clean_json_on_stdout(tmp_path, capsys):
    def no_key(alias, cfg):
        raise ProviderError("No Anthropic API key yet.")

    assert await cli.canvas(Config(home=tmp_path), True, command_factory=FakeCanvas, provider_factory=no_key) == 0
    out, err = capsys.readouterr()
    (row,) = json.loads(out)
    assert row["title"] == "Lab 1" and row["priority"] == "High" and row["start_by"] == "2026-11-02"
    assert "without plans" in err


async def test_canvas_reports_not_connected_with_exit_1(tmp_path, capsys):
    assert await cli.canvas(Config(home=tmp_path), True, provider_factory=lambda a, c: None) == 1
    out, err = capsys.readouterr()
    assert out == "" and "/canvas setup" in err


def test_main_routes_the_one_shot_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FIXEL_HOME", str(tmp_path))
    assert main(["cases", "nothing", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []

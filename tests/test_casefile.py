import sqlite3
from datetime import datetime

from fixel.casefile import CaseFile, tokens

NUMPY = "ModuleNotFoundError: No module named 'numpy'"
SCREEN = "$ python3 app.py\nTraceback (most recent call last):\nModuleNotFoundError: No module named 'numpy'"


def make(tmp_path):
    return CaseFile(tmp_path / "c.db")


def save(cf, key="k", answer="a", case_id=None, **kw):
    return cf.save(
        case_id=case_id, mode=kw.get("mode", "error"), key=key, question="q", answer=answer,
        shot_paths=kw.get("shots", []), now=kw.get("now"), screen_text=kw.get("screen_text", ""),
    )


def test_tokens():
    assert tokens(NUMPY) == {"modulenotfounderror", "no", "module", "named", "numpy"}


def test_save_get_roundtrip(tmp_path):
    cf = make(tmp_path)
    cid = save(cf, key="Boom", shots=[tmp_path / "s.png"], now=datetime(2026, 9, 12, 10, 0), screen_text="Boom!")
    rec = cf.get(cid)
    assert rec.created_at == datetime(2026, 9, 12, 10, 0)
    assert rec.key == "Boom" and rec.shot_paths == [str(tmp_path / "s.png")]
    assert rec.screen_text == "Boom!" and rec.worked is False
    assert cf.get(999) is None


def test_update_replaces_search_text(tmp_path):
    cf = make(tmp_path)
    cid = save(cf, answer="alpha")
    assert save(cf, answer="bravo", case_id=cid) == cid
    assert [r.id for r in cf.search("bravo")] == [cid]
    assert cf.search("alpha") == []


def test_similar_finds_past_key_on_new_screen(tmp_path):
    cf = make(tmp_path)
    old = save(cf, key=NUMPY, answer="pip install numpy")
    save(cf, key="TypeError: cannot read properties of undefined")
    assert [r.id for r in cf.similar(SCREEN)] == [old]


def test_similar_excludes_current_case_and_weak_matches(tmp_path):
    cf = make(tmp_path)
    cid = save(cf, key=NUMPY)
    assert cf.similar(SCREEN, exclude_id=cid) == []
    assert cf.similar("TypeError: x is not a function") == []
    assert cf.similar("") == []


def test_similar_prefers_fixes_that_worked(tmp_path):
    cf = make(tmp_path)
    plain = save(cf, key=NUMPY, answer="try reinstalling")
    proven = save(cf, key=NUMPY, answer="activate the venv")
    cf.mark_worked(proven)
    assert [r.id for r in cf.similar(SCREEN, limit=2)] == [proven, plain]
    assert cf.get(proven).worked is True


def test_reopen_persists(tmp_path):
    cid = save(make(tmp_path))
    assert make(tmp_path).get(cid) is not None


def test_upgrades_a_case_file_from_the_first_version(tmp_path):
    db = sqlite3.connect(tmp_path / "c.db")
    db.executescript("""
        CREATE TABLE cases (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, mode TEXT NOT NULL, key TEXT NOT NULL,
                            question TEXT NOT NULL, answer TEXT NOT NULL, shot_paths TEXT NOT NULL);
        CREATE VIRTUAL TABLE cases_fts USING fts5(key, question, answer);
        INSERT INTO cases VALUES (1, '2026-09-12T10:00:00', 'error', 'ModuleNotFoundError: No module named ''numpy''', 'q', 'old fix', '[]');
        INSERT INTO cases_fts (rowid, key, question, answer) VALUES (1, 'ModuleNotFoundError: No module named ''numpy''', 'q', 'old fix');
    """)
    db.commit()
    db.close()
    cf = make(tmp_path)
    assert cf.get(1).answer == "old fix" and cf.get(1).worked is False
    assert [r.id for r in cf.similar(SCREEN)] == [1]
    assert save(cf, key="new", screen_text="fresh text") == 2
    assert [r.id for r in cf.search("fresh")] == [2]

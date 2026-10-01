from datetime import datetime

from fixel.casefile import CaseFile, tokens

NUMPY = "ModuleNotFoundError: No module named 'numpy'"


def make(tmp_path):
    return CaseFile(tmp_path / "c.db")


def save(cf, key="k", answer="a", case_id=None, **kw):
    return cf.save(case_id=case_id, mode=kw.get("mode", "error"), key=key, question="q", answer=answer, shot_paths=kw.get("shots", []), now=kw.get("now"))


def test_tokens():
    assert tokens(NUMPY) == {"modulenotfounderror", "no", "module", "named", "numpy"}


def test_save_get_roundtrip(tmp_path):
    cf = make(tmp_path)
    cid = save(cf, key="Boom", shots=[tmp_path / "s.png"], now=datetime(2026, 9, 12, 10, 0))
    rec = cf.get(cid)
    assert rec.created_at == datetime(2026, 9, 12, 10, 0)
    assert rec.key == "Boom" and rec.shot_paths == [str(tmp_path / "s.png")]
    assert cf.get(999) is None


def test_update_replaces_search_text(tmp_path):
    cf = make(tmp_path)
    cid = save(cf, answer="alpha")
    assert save(cf, answer="bravo", case_id=cid) == cid
    assert [r.id for r in cf.search("bravo")] == [cid]
    assert cf.search("alpha") == []


def test_recall_similar_key_excluding_self(tmp_path):
    cf = make(tmp_path)
    old = save(cf, key=NUMPY, answer="pip install numpy")
    new = save(cf, key=NUMPY)
    assert cf.recall(NUMPY, exclude_id=new).id == old


def test_recall_threshold_and_empty_key(tmp_path):
    cf = make(tmp_path)
    save(cf, key="TypeError: cannot read properties of undefined")
    assert cf.recall("TypeError: x is not a function", exclude_id=None) is None
    assert cf.recall("", exclude_id=None) is None


def test_reopen_persists(tmp_path):
    cid = save(make(tmp_path))
    assert make(tmp_path).get(cid) is not None

"""저장소·데이터 정규화·입력 검증 단위 테스트 (브라우저 불필요).

실행: python -m pytest tests/test_store.py
"""

import json
import logging
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.getLogger("streamlit").setLevel(logging.ERROR)
import app  # noqa: E402


def make(name, **kw):
    item = {"id": kw.pop("id", None) or app.uuid.uuid4().hex, "name": name, "quantity": 1,
            "memo": "", "checked": False, "created_at": "t", "updated_at": "t"}
    item.update(kw)
    return item


@pytest.fixture
def json_store(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app, "DATA_FILE", tmp_path / "shopping_list.json")
    return app.JsonStore()


@pytest.fixture
def sql_store(tmp_path):
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield app.SqlStore(SimpleNamespace(engine=engine))
    engine.dispose()


@pytest.fixture(params=["json", "sql"])
def store(request):
    return request.getfixturevalue(f"{request.param}_store")


# ---------------------------------------------------------------------------
# 두 저장소 공통 동작
# ---------------------------------------------------------------------------
def test_crud(store):
    a, b, c = make("A"), make("B"), make("C", checked=True)
    for it in (a, b, c):
        store.add(it)
    assert [it["name"] for it in store.all()] == ["A", "B", "C"]
    assert store.update(b["id"], {"name": "B2", "quantity": 3, "checked": True})
    assert not store.update("없는-id", {"name": "x"})
    got = {it["name"]: it for it in store.all()}
    assert got["B2"]["quantity"] == 3 and got["B2"]["checked"] is True
    assert store.delete({a["id"]}) == 1 and store.delete({"없는-id"}) == 0
    assert store.delete(checked_only=True) == 2
    assert store.all() == []
    store.add(make("D"))
    assert store.delete() == 1 and store.all() == []


def test_two_sessions_do_not_overwrite(store):
    """세션 A·B가 각자 추가해도 둘 다 남는다 (이전 버전의 데이터 유실 버그 재발 방지)."""
    store.add(make("탭A"))
    store.add(make("탭B"))
    assert {it["name"] for it in store.all()} == {"탭A", "탭B"}


def test_deleted_item_not_resurrected(store):
    """다른 세션이 전체 삭제한 뒤, 오래된 화면에서 체크해도 되살아나지 않는다."""
    a = make("A")
    store.add(a)
    store.delete()
    assert not store.update(a["id"], {"checked": True})
    assert store.all() == []


def test_concurrent_adds(store):
    """여러 스레드(동시 접속자)가 한꺼번에 추가해도 유실 없음."""
    threads = [threading.Thread(target=store.add, args=(make(f"T{i}"),)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.all()) == 20


# ---------------------------------------------------------------------------
# JSON 파일 처리
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("content", ["{broken", "", '{"a": 1}', "null"])
def test_corrupt_file(json_store, content):
    app.DATA_FILE.write_text(content, encoding="utf-8")
    assert json_store.all() == []


def test_no_temp_files_left(json_store):
    json_store.add(make("A"))
    assert [p.name for p in app.DATA_DIR.iterdir()] == ["shopping_list.json"]


def test_json_saved_format(json_store):
    json_store.add(make("우유", quantity=2))
    data = json.loads(app.DATA_FILE.read_text(encoding="utf-8"))
    assert set(data[0]) == {"id", "name", "quantity", "memo", "checked", "created_at", "updated_at"}
    assert data[0]["name"] == "우유"  # ensure_ascii=False


# ---------------------------------------------------------------------------
# 정규화 (잘못된 데이터로 앱이 죽지 않도록)
# ---------------------------------------------------------------------------
def test_normalize_items():
    raw = [
        {"name": "필드 누락"},
        "문자열 원소",
        None,
        {"id": "x", "name": "  "},  # 빈 이름 → 버림
        {"id": "y", "name": "타입 오류", "quantity": "2", "memo": None, "checked": "yes"},
        {"id": "y", "name": "중복 id"},
        {"id": "z", "name": "가" * 80, "quantity": -5, "checked": 1},
        {"id": "w", "name": "큰 수량", "quantity": 10**12, "checked": True},
    ]
    items = app.normalize_items(raw)
    assert [it["name"][:5] for it in items] == ["필드 누락", "타입 오류", "가" * 5, "큰 수량"]
    for it in items:
        assert set(it) == {"id", "name", "quantity", "memo", "checked", "created_at", "updated_at"}
        assert isinstance(it["quantity"], int) and 1 <= it["quantity"] <= app.MAX_QTY
        assert isinstance(it["checked"], bool) and isinstance(it["memo"], str)
    assert items[1]["quantity"] == 2 and items[1]["checked"] is False
    assert len(items[2]["name"]) == app.MAX_NAME_LEN and items[2]["checked"] is True
    assert app.normalize_items({"not": "list"}) == []


# ---------------------------------------------------------------------------
# 입력 검증 / 이스케이프
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,qty,memo,ok", [
    ("우유", 1, "", True),
    ("  우유  ", 2, "  메모 ", True),
    ("", 1, "", False),
    ("   ", 1, "", False),
    ("가" * 50, 1, "", True),
    ("가" * 51, 1, "", False),
    ("a", 0, "", False),
    ("a", -1, "", False),
    ("a", 1.5, "", False),
    ("a", app.MAX_QTY + 1, "", False),
    ("a", True, "", False),
    ("a", 1, "m" * (app.MAX_MEMO_LEN + 1), False),
])
def test_validate_input(name, qty, memo, ok):
    clean, q, m, err = app.validate_input(name, qty, memo)
    assert (err is None) == ok
    if ok:
        assert clean == name.strip() and m == memo.strip() and q == qty


def test_md_escape_streamlit_directives():
    for s in [":red[빨강]", ":material/home:", ":smile:", "**b**", "[x](y)", "<b>"]:
        esc = app.md_escape(s)
        assert ":" not in esc.replace("\\:", "") and "[" not in esc.replace("\\[", "")


def test_timestamp_has_timezone():
    assert app._now().endswith("+00:00")

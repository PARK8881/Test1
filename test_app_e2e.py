"""쇼핑 리스트 앱 E2E 테스트 (Playwright).

실행:
    pytest tests/test_app_e2e.py                 # 전체
    pytest tests/test_app_e2e.py -k edit         # 일부

- 테스트용 Streamlit 서버를 APP_PORT(기본 8502)에 직접 띄운다. 개발용 8501 서버와 충돌하지 않는다.
- 시작 시 data/shopping_list.json 을 백업하고, 종료 시 원복한다.
- 각 테스트는 데이터 파일을 비운(또는 시드한) 상태에서 새 브라우저 세션으로 시작한다.
- PRD 문서 번호는 테스트 이름/주석에 [PRD x.x] 형태로 표기.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "shopping_list.json"
SHOTS = ROOT / "tests" / "screenshots"
PORT = int(os.environ.get("APP_PORT", "8502"))
BASE = f"http://localhost:{PORT}/"

ROWS = 'div[class*="st-key-row_"]'
IDLE = '[data-testid="stApp"][data-test-script-state="notRunning"]'


# ---------------------------------------------------------------------------
# 서버 / 데이터 fixture
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def server():
    """데이터 백업 → 테스트 서버 기동 → 종료 후 서버 정지·데이터 원복."""
    backup = DATA_FILE.with_suffix(".json.e2e-backup")
    had_data = DATA_FILE.exists()
    if had_data:
        shutil.copy2(DATA_FILE, backup)
    DATA_FILE.unlink(missing_ok=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.headless", "true", "--server.port", str(PORT),
         "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(120):
            try:
                if urllib.request.urlopen(BASE + "_stcore/health", timeout=1).read() == b"ok":
                    break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.fail("Streamlit 서버가 시작되지 않았습니다.")
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        DATA_FILE.unlink(missing_ok=True)
        if had_data:
            shutil.move(backup, DATA_FILE)


def seed(items):
    """데이터 파일을 지정 내용으로 만든다 (None이면 삭제)."""
    if items is None:
        DATA_FILE.unlink(missing_ok=True)
        return
    DATA_FILE.parent.mkdir(exist_ok=True)
    text = items if isinstance(items, str) else json.dumps(items, ensure_ascii=False)
    DATA_FILE.write_text(text, encoding="utf-8")


def make_items(*names, checked=()):
    """시드용 아이템 리스트 생성."""
    return [
        {"id": f"seed-{i}", "name": n, "quantity": 1, "memo": "", "checked": i in checked,
         "created_at": "2026-11-10T10:00:00", "updated_at": "2026-11-10T10:00:00"}
        for i, n in enumerate(names)
    ]


def saved():
    """현재 데이터 파일 내용."""
    return json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else []


@pytest.fixture(autouse=True)
def clean_data():
    """각 테스트는 빈 데이터로 시작."""
    seed(None)
    yield


@pytest.fixture
def errors(page: Page):
    """페이지 JS 오류·alert 수집. 테스트 종료 시 오류/Streamlit 예외가 없어야 한다."""
    errs = []
    page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    page.on("dialog", lambda d: (errs.append(f"dialog: {d.message}"), d.dismiss()))
    yield errs
    exc = page.locator('[data-testid="stException"]')
    assert exc.count() == 0, f"Streamlit 예외: {exc.first.inner_text()}"
    assert errs == []


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def wait_run(page: Page):
    """Streamlit rerun이 끝날 때까지 대기."""
    page.wait_for_timeout(150)
    page.wait_for_selector(IDLE, timeout=15000)


def open_app(page: Page):
    page.goto(BASE)
    page.wait_for_selector('[data-testid="stProgress"]', timeout=30000)
    wait_run(page)


def add(page: Page, name, qty=None, memo=None, enter=False):
    page.locator(".st-key-new_name input").fill(name)
    if qty is not None:
        page.locator(".st-key-new_qty input").fill(str(qty))
    if memo is not None:
        page.locator(".st-key-new_memo input").fill(memo)
    if enter:
        page.locator(".st-key-new_name input").press("Enter")
    else:
        page.locator('[data-testid="stFormSubmitButton"] button').click()
    wait_run(page)


def rows(page: Page):
    return page.locator(ROWS)


def row(page: Page, text: str):
    """이름(또는 메모)이 정확히 text인 행. has_text는 대소문자 무시 부분일치라
    아이콘 리거처("edit", "delete")까지 매칭되므로 정확 일치로 찾는다."""
    return rows(page).filter(has=page.get_by_text(text, exact=True))


def click_check(r):
    r.locator('[data-testid="stCheckbox"] label').click()
    wait_run(r.page)


def click_edit(r):
    r.locator('[class*="st-key-edit_"] button').first.click()
    wait_run(r.page)


def click_delete(r):
    r.locator('[class*="st-key-del_"] button').first.click()
    wait_run(r.page)


def progress_text(page: Page):
    return page.locator('[data-testid="stProgress"]').inner_text()


def row_texts(page: Page):
    return [t.strip() for t in rows(page).all_inner_texts()]


# ---------------------------------------------------------------------------
# 1. 기능 테스트
# ---------------------------------------------------------------------------
def test_empty_state(page, errors):
    """[PRD 4.5] 빈 상태 안내 + 진행률 0."""
    open_app(page)
    expect(page.get_by_text("쇼핑 리스트가 비어 있습니다")).to_be_visible()
    assert "전체 0개 중 0개 완료" in progress_text(page)


def test_add_with_button(page, errors):
    """[PRD 4.1] 버튼으로 추가, 입력 초기화, 리스트 하단 추가, JSON 저장."""
    open_app(page)
    add(page, "우유", qty=2, memo="저지방")
    add(page, "계란")
    expect(rows(page)).to_have_count(2)
    texts = row_texts(page)
    assert "우유" in texts[0] and "x2" in texts[0] and "저지방" in texts[0]
    assert "계란" in texts[1] and "x1" in texts[1], "새 아이템은 하단 + 수량 기본값 1"
    expect(page.locator(".st-key-new_name input")).to_have_value("")
    expect(page.locator(".st-key-new_qty input")).to_have_value("1")
    expect(page.locator(".st-key-new_memo input")).to_have_value("")
    data = saved()
    assert [d["name"] for d in data] == ["우유", "계란"] and data[0]["quantity"] == 2


def test_add_with_enter(page, errors):
    """[PRD 4.1] Enter 키로 추가."""
    open_app(page)
    add(page, "사과", enter=True)
    expect(rows(page)).to_have_count(1)
    assert "사과" in row_texts(page)[0]


@pytest.mark.parametrize("name", ["", "    "], ids=["empty", "spaces"])
def test_reject_blank_name(page, errors, name):
    """[PRD 4.1] 빈/공백 이름 → 추가 안 됨 + 경고."""
    open_app(page)
    add(page, name)
    expect(rows(page)).to_have_count(0)
    expect(page.get_by_text("아이템명을 입력해 주세요.")).to_be_visible()
    assert saved() == []


def test_name_max_length(page, errors):
    """[PRD 4.1] 아이템명 최대 50자: 실제 키 입력으로 51자 입력 시 50자까지만 들어감.
    (fill()은 maxlength를 우회하므로 사용하지 않음)"""
    open_app(page)
    box = page.locator(".st-key-new_name input")
    box.press_sequentially("a" * 51)
    expect(box).to_have_value("a" * 50)
    page.locator('[data-testid="stFormSubmitButton"] button').click()
    wait_run(page)
    data = saved()
    assert len(data) == 1 and len(data[0]["name"]) == 50


def test_strip_whitespace(page, errors):
    """[PRD 4.1] 앞뒤 공백 제거."""
    open_app(page)
    add(page, "   바나나   ")
    assert saved()[0]["name"] == "바나나"


@pytest.mark.parametrize("qty", ["0", "-3"])
def test_reject_invalid_quantity(page, errors, qty):
    """[PRD 4.1] 수량 1 이상 정수: 0/음수는 저장되지 않아야 한다."""
    open_app(page)
    add(page, "양파", qty=qty)
    data = saved()
    assert all(d["quantity"] >= 1 for d in data), f"잘못된 수량이 저장됨: {data}"


def test_edit_save(page, errors):
    """[PRD 4.2] 편집 모드 → 저장 반영, updated_at 갱신."""
    seed(make_items("우유"))
    open_app(page)
    click_edit(row(page, "우유"))
    page.locator('[class*="st-key-edit_name_"] input').fill("두유")
    page.locator('[class*="st-key-edit_qty_"] input').fill("3")
    page.locator('[class*="st-key-edit_memo_"] input').fill("무가당")
    page.get_by_role("button", name="저장").click()
    wait_run(page)
    expect(page.locator('[class*="st-key-edit_name_"]')).to_have_count(0)
    t = row_texts(page)[0]
    assert "두유" in t and "x3" in t and "무가당" in t
    d = saved()[0]
    assert (d["name"], d["quantity"], d["memo"]) == ("두유", 3, "무가당")
    assert d["updated_at"] != "2026-11-10T10:00:00"


def test_edit_cancel(page, errors):
    """[PRD 4.2] 취소 시 원상태."""
    seed(make_items("우유"))
    open_app(page)
    click_edit(row(page, "우유"))
    page.locator('[class*="st-key-edit_name_"] input').fill("바뀐이름")
    page.get_by_role("button", name="취소").click()
    wait_run(page)
    assert "우유" in row_texts(page)[0] and saved()[0]["name"] == "우유"


def test_edit_reject_blank(page, errors):
    """[PRD 4.2] 수정 시에도 검증: 빈 이름 거부, 편집 모드 유지."""
    seed(make_items("우유"))
    open_app(page)
    click_edit(row(page, "우유"))
    page.locator('[class*="st-key-edit_name_"] input').fill("  ")
    page.get_by_role("button", name="저장").click()
    wait_run(page)
    expect(page.get_by_text("아이템명을 입력해 주세요.")).to_be_visible()
    expect(page.locator('[class*="st-key-edit_name_"]')).to_have_count(1)
    assert saved()[0]["name"] == "우유"


def test_edit_save_with_enter(page, errors):
    """[PRD 4.2] 편집 모드에서 Enter 키로 저장 (추가 폼과 동작 일치)."""
    seed(make_items("우유"))
    open_app(page)
    click_edit(row(page, "우유"))
    box = page.locator('[class*="st-key-edit_name_"] input')
    box.fill("두유")
    box.press("Enter")
    wait_run(page)
    expect(page.locator('[class*="st-key-edit_name_"]')).to_have_count(0)
    assert saved()[0]["name"] == "두유"


def test_edit_one_at_a_time(page, errors):
    """[PRD 4.2] 한 번에 하나만 편집."""
    seed(make_items("우유", "계란"))
    open_app(page)
    click_edit(row(page, "우유"))
    click_edit(row(page, "계란"))
    expect(page.locator('[class*="st-key-edit_name_"]')).to_have_count(1)
    expect(page.locator('[class*="st-key-edit_name_"] input')).to_have_value("계란")


def test_delete(page, errors):
    """[PRD 4.3] 개별 삭제."""
    seed(make_items("우유", "계란", "사과"))
    open_app(page)
    click_delete(row(page, "계란"))
    expect(rows(page)).to_have_count(2)
    assert [d["name"] for d in saved()] == ["우유", "사과"]


def test_check_toggle(page, errors):
    """[PRD 4.4] 체크 → 취소선·진행률 갱신·하단 이동, 해제 → 복원."""
    seed(make_items("우유", "계란"))
    open_app(page)
    click_check(row(page, "우유"))
    expect(row(page, "우유").locator("del")).to_have_count(1)
    assert "전체 2개 중 1개 완료" in progress_text(page)
    assert "우유" in row_texts(page)[-1], "완료 항목은 하단"
    assert saved()[0]["checked"] is True
    click_check(row(page, "우유"))
    expect(row(page, "우유").locator("del")).to_have_count(0)
    assert "전체 2개 중 0개 완료" in progress_text(page)
    assert saved()[0]["checked"] is False


def test_delete_middle_keeps_check_state(page, errors):
    """체크 상태가 index가 아니라 id에 묶여 있는지 (중간 삭제 후 밀림 없음)."""
    seed(make_items("A", "B", "C", "D", checked=(2,)))
    open_app(page)
    click_delete(row(page, "B"))
    states = {d["name"]: d["checked"] for d in saved()}
    assert states == {"A": False, "C": True, "D": False}
    expect(row(page, "C").locator('input[type="checkbox"]')).to_be_checked()
    expect(row(page, "D").locator('input[type="checkbox"]')).not_to_be_checked()


def test_duplicate_names_independent(page, errors):
    """같은 이름 여러 개: 체크/삭제가 해당 항목에만 적용."""
    open_app(page)
    add(page, "우유", memo="첫째")
    add(page, "우유", memo="둘째")
    click_check(row(page, "둘째"))
    data = saved()
    assert [d["checked"] for d in data] == [False, True]
    click_delete(row(page, "첫째"))
    data = saved()
    assert len(data) == 1 and data[0]["memo"] == "둘째" and data[0]["checked"]


def test_clear_checked(page, errors):
    """[PRD 4.5] 구매 완료 항목 일괄 삭제 (완료 없으면 비활성)."""
    seed(make_items("A", "B", "C"))
    open_app(page)
    btn = page.get_by_role("button", name="구매 완료 항목 지우기")
    expect(btn).to_be_disabled()
    click_check(row(page, "A"))
    click_check(row(page, "C"))
    expect(btn).to_be_enabled()
    btn.click()
    wait_run(page)
    assert [d["name"] for d in saved()] == ["B"]


def test_clear_all_confirm_and_cancel(page, errors):
    """[PRD 4.5] 전체 삭제는 확인 절차 후 실행."""
    seed(make_items("A", "B"))
    open_app(page)
    page.get_by_role("button", name="전체 삭제").click()
    wait_run(page)
    expect(page.get_by_text("모두 삭제할까요")).to_be_visible()
    assert len(saved()) == 2, "확인 전에는 삭제되면 안 됨"
    page.locator(".st-key-cancel_clear_all button").click()
    wait_run(page)
    expect(page.get_by_text("모두 삭제할까요")).to_have_count(0)
    page.get_by_role("button", name="전체 삭제").click()
    wait_run(page)
    page.get_by_role("button", name="삭제 확인").click()
    wait_run(page)
    expect(page.get_by_text("쇼핑 리스트가 비어 있습니다")).to_be_visible()
    assert saved() == []


def test_persistence_after_reload(page, errors):
    """[PRD 4.6 / 10장] 새로고침 후 유지 + JSON이 PRD 5장 데이터 모델과 일치."""
    open_app(page)
    add(page, "우유", qty=2, memo="저지방")
    click_check(row(page, "우유"))
    page.reload()
    open_app(page)
    expect(row(page, "우유").locator('input[type="checkbox"]')).to_be_checked()
    d = saved()[0]
    assert set(d) == {"id", "name", "quantity", "memo", "checked", "created_at", "updated_at"}
    assert isinstance(d["quantity"], int) and isinstance(d["checked"], bool)


# ---------------------------------------------------------------------------
# 2. 엣지 케이스 / 버그 탐색
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "<script>alert(1)</script>",
    "<b>굵게</b>",
    "<img src=x onerror=alert(1)>",
    "**별표** _밑줄_ ~~취소~~",
    "괄호]닫기 :red[빨강]",
    "🍎🥛 이모지",
    "가" * 50,
], ids=["script", "b-tag", "img-onerror", "markdown", "bracket-directive", "emoji", "hangul50"])
def test_special_text_rendered_literally(page, errors, text):
    """특수문자/HTML/마크다운 입력은 글자 그대로 표시 (XSS·서식 주입 없음). 메모에도 동일 적용."""
    open_app(page)
    add(page, text, memo=text)
    r = rows(page).first
    md = r.locator('[data-testid="stMarkdown"]')
    assert md.inner_text().count(text) == 2, f"표시 텍스트 불일치: {md.inner_text()!r}"
    assert md.locator("b, img, script, em").count() == 0
    # 체크(취소선) 상태에서도 동일
    click_check(r)
    assert rows(page).first.locator('[data-testid="stMarkdown"]').inner_text().count(text) == 2


def test_performance_100_items(page, errors):
    """[PRD 7] 아이템 100개 기준 조작 후 화면 갱신 1초 이내."""
    seed(make_items(*[f"아이템{i:03d}" for i in range(100)]))
    open_app(page)
    expect(rows(page)).to_have_count(100)
    timings = {}
    t = time.perf_counter(); click_check(row(page, "아이템050")); timings["check"] = time.perf_counter() - t
    t = time.perf_counter(); add(page, "새아이템"); timings["add"] = time.perf_counter() - t
    t = time.perf_counter(); click_delete(row(page, "아이템010")); timings["delete"] = time.perf_counter() - t
    print("timings:", {k: round(v, 3) for k, v in timings.items()})
    assert all(v < 1.0 for v in timings.values()), timings


def test_rapid_checkbox_clicks(page, errors):
    """체크박스 연속 클릭 시 화면과 저장 상태가 일치."""
    seed(make_items("A"))
    open_app(page)
    label = row(page, "A").locator('[data-testid="stCheckbox"] label')
    for _ in range(5):
        label.click()
    wait_run(page)
    page.wait_for_timeout(500)
    wait_run(page)
    ui_checked = row(page, "A").locator('input[type="checkbox"]').is_checked()
    assert saved()[0]["checked"] == ui_checked
    page.reload(); open_app(page)
    assert row(page, "A").locator('input[type="checkbox"]').is_checked() == ui_checked


def test_rapid_double_delete(page, errors):
    """삭제 버튼 더블클릭 시 다른 아이템이 함께 지워지지 않음."""
    seed(make_items("A", "B", "C"))
    open_app(page)
    row(page, "A").locator('[class*="st-key-del_"] button').first.dblclick()
    wait_run(page)
    page.wait_for_timeout(500)
    wait_run(page)
    assert [d["name"] for d in saved()] == ["B", "C"]


def test_delete_other_row_while_editing(page, errors):
    """편집 중 다른 행 삭제 → 편집 상태 유지, 상태 꼬임 없음."""
    seed(make_items("A", "B"))
    open_app(page)
    click_edit(row(page, "A"))
    click_delete(row(page, "B"))
    expect(page.locator('[class*="st-key-edit_name_"] input')).to_have_value("A")
    page.locator('[class*="st-key-edit_name_"] input').fill("A2")
    page.get_by_role("button", name="저장").click()
    wait_run(page)
    assert [d["name"] for d in saved()] == ["A2"]


def test_check_while_editing_other(page, errors):
    """편집 중 다른 행 체크 → 입력 중이던 편집값이 유지되어야 함."""
    seed(make_items("A", "B"))
    open_app(page)
    click_edit(row(page, "A"))
    page.locator('[class*="st-key-edit_name_"] input').fill("A-수정중")
    page.locator('[class*="st-key-edit_name_"] input').blur()
    click_check(row(page, "B"))
    expect(page.locator('[class*="st-key-edit_name_"] input')).to_have_value("A-수정중")


@pytest.mark.parametrize("content", [
    "{broken json",
    "",
    '{"not": "a list"}',
], ids=["broken", "empty-file", "object"])
def test_corrupt_data_file(page, errors, content):
    """[PRD 4.6] 깨진 JSON → 오류 없이 빈 리스트로 시작."""
    seed(content)
    open_app(page)
    expect(page.get_by_text("쇼핑 리스트가 비어 있습니다")).to_be_visible()


@pytest.mark.parametrize("content", [
    '[{"name": "필드 누락"}]',
    '["문자열 원소"]',
    '[{"id": "x", "name": "수량 문자열", "quantity": "2", "memo": null, "checked": "no",'
    ' "created_at": "", "updated_at": ""}]',
], ids=["missing-fields", "non-dict", "wrong-types"])
def test_malformed_items_in_file(page, errors, content):
    """JSON 문법은 맞지만 아이템 구조가 잘못된 경우에도 앱이 죽지 않아야 함."""
    seed(content)
    open_app(page)
    page.wait_for_timeout(500)


def test_clear_all_prompt_not_stale(page, errors):
    """전체 삭제 확인창을 띄운 뒤 개별 삭제로 리스트를 비우면,
    다음에 아이템을 추가했을 때 확인창이 다시 저절로 뜨면 안 됨."""
    seed(make_items("A"))
    open_app(page)
    page.get_by_role("button", name="전체 삭제").click()
    wait_run(page)
    click_delete(row(page, "A"))
    add(page, "B")
    expect(page.get_by_text("모두 삭제할까요")).to_have_count(0)


def test_two_tabs_no_data_loss(browser):
    """두 탭(또는 두 사용자)이 동시에 쓰면 서로의 변경을 덮어쓰지 않아야 함.
    배포 시 모든 접속자가 같은 JSON 파일을 공유하므로 중요."""
    ctx_a, ctx_b = browser.new_context(), browser.new_context()
    a, b = ctx_a.new_page(), ctx_b.new_page()
    try:
        open_app(a)
        open_app(b)
        add(a, "탭A-아이템")
        add(b, "탭B-아이템")
        names = [d["name"] for d in saved()]
        assert {"탭A-아이템", "탭B-아이템"} <= set(names), f"저장된 데이터: {names}"
    finally:
        ctx_a.close(); ctx_b.close()


def test_stale_tab_resurrects_deleted(browser):
    """탭 B에서 전체 삭제 후, 오래 열려 있던 탭 A에서 조작하면 삭제된 아이템이 되살아나면 안 됨."""
    seed(make_items("A", "B"))
    ctx_a, ctx_b = browser.new_context(), browser.new_context()
    a, b = ctx_a.new_page(), ctx_b.new_page()
    try:
        open_app(a)
        open_app(b)
        b.get_by_role("button", name="전체 삭제").click(); wait_run(b)
        b.get_by_role("button", name="삭제 확인").click(); wait_run(b)
        assert saved() == []
        click_check(row(a, "A"))
        names = [d["name"] for d in saved()]
        assert names == [], f"삭제된 아이템이 되살아남: {names}"
        # 오래된 탭도 조작 후에는 최신 상태(빈 리스트)를 보여줌
        expect(a.get_by_text("쇼핑 리스트가 비어 있습니다")).to_be_visible()
    finally:
        ctx_a.close(); ctx_b.close()


def test_stale_tab_check_uses_what_user_sees(browser):
    """탭 B가 체크한 아이템을, 아직 미체크로 보고 있던 탭 A가 체크해도 '체크됨'으로 남아야 함
    (단순 반전이면 오히려 해제되어 버림)."""
    seed(make_items("A"))
    ctx_a, ctx_b = browser.new_context(), browser.new_context()
    a, b = ctx_a.new_page(), ctx_b.new_page()
    try:
        open_app(a)
        open_app(b)
        click_check(row(b, "A"))
        click_check(row(a, "A"))
        assert saved()[0]["checked"] is True
        expect(row(a, "A").locator('input[type="checkbox"]')).to_be_checked()
    finally:
        ctx_a.close(); ctx_b.close()


def test_other_tab_changes_visible_after_action(browser):
    """다른 탭에서 추가한 아이템이, 내 탭에서 아무 조작이나 하면 함께 보인다."""
    ctx_a, ctx_b = browser.new_context(), browser.new_context()
    a, b = ctx_a.new_page(), ctx_b.new_page()
    try:
        open_app(a)
        open_app(b)
        add(b, "B가-추가")
        add(a, "A가-추가")
        expect(row(a, "B가-추가")).to_have_count(1)
        expect(rows(a)).to_have_count(2)
    finally:
        ctx_a.close(); ctx_b.close()


# ---------------------------------------------------------------------------
# 3. UI / 반응형 / 접근성
# ---------------------------------------------------------------------------
UI_SEED = make_items("우유", "계란", "가" * 50,
                     "Supercalifragilisticexpialidociouslylongproductname", checked=(1,))


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("vp", [(1280, 1200), (390, 1400)], ids=["desktop", "mobile"])
def test_layout_screenshots(browser, vp, scheme):
    """데스크톱/모바일 × 라이트/다크: 가로 스크롤 없음, 행 내부 버튼이 카드 밖으로 안 넘침, 스크린샷 저장."""
    seed(UI_SEED)
    SHOTS.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(viewport={"width": vp[0], "height": vp[1]}, color_scheme=scheme)
    page = ctx.new_page()
    try:
        open_app(page)
        page.wait_for_timeout(500)
        name = f"{'desktop' if vp[0] > 600 else 'mobile'}_{scheme}.png"
        page.screenshot(path=str(SHOTS / name), full_page=True)
        assert not page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth"
        ), "가로 스크롤 발생"
        overflow = page.evaluate("""() => [...document.querySelectorAll('div[class*="st-key-row_"]')]
            .filter(r => [...r.querySelectorAll('button')].some(b => {
                const rb = r.getBoundingClientRect(), bb = b.getBoundingClientRect();
                return bb.width > 0 && (bb.right > rb.right + 1 || bb.left < rb.left - 1);
            })).length""")
        assert overflow == 0, f"버튼이 카드 밖으로 넘친 행: {overflow}"
    finally:
        ctx.close()


def test_mobile_touch_targets(browser):
    """[PRD 6] 모바일에서 수정/삭제 버튼이 터치하기 쉬운 크기인지 (권장 최소 44×44px, WCAG 2.5.5)."""
    seed(make_items("우유"))
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    try:
        open_app(page)
        sizes = page.evaluate("""() => ['edit_', 'del_'].map(k => {
            const b = [...document.querySelectorAll(`[class*="st-key-${k}"] button`)]
                .find(b => b.getBoundingClientRect().width > 0).getBoundingClientRect();
            return [k, Math.round(b.width), Math.round(b.height)];
        })""")
        print("touch targets:", sizes)
        small = [s for s in sizes if s[1] < 44 or s[2] < 44]
        assert not small, f"44px 미만 버튼: {small}"
    finally:
        ctx.close()


def test_icon_buttons_have_accessible_name(page, errors):
    """수정/삭제 아이콘 버튼에 접근 가능한 이름(화면 낭독기용)이 있어야 함."""
    seed(make_items("우유"))
    open_app(page)
    r = row(page, "우유")
    expect(r.get_by_role("button", name="수정")).to_have_count(1)
    expect(r.get_by_role("button", name="삭제")).to_have_count(1)
    expect(r.get_by_role("checkbox", name="우유 구매 완료")).to_have_count(1)
    # 라벨 글자는 화면에는 보이지 않아야 함 (아이콘만 표시)
    for key in ["edit_", "del_"]:
        label = r.locator(f'[class*="st-key-{key}"] button [data-testid="stMarkdownContainer"]').first
        assert label.bounding_box()["width"] <= 1


def test_vertical_alignment(page, errors):
    """한 줄짜리 행에서 체크박스·텍스트·버튼의 세로 중심이 맞아야 함 (±4px)."""
    seed(make_items("우유"))
    open_app(page)
    centers = page.evaluate("""() => {
        const r = document.querySelector('div[class*="st-key-row_"]');
        const c = el => { const b = el.getBoundingClientRect(); return b.top + b.height / 2; };
        return {
            checkbox: c(r.querySelector('[data-testid="stCheckbox"] label > span, [data-testid="stCheckbox"] label')),
            text: c(r.querySelector('[data-testid="stMarkdown"] [data-testid="stMarkdownContainer"] p')),
            button: c([...r.querySelectorAll('[class*="st-key-del_"] button')].find(b => b.offsetWidth)),
        };
    }""")
    print("centers:", centers)
    assert max(centers.values()) - min(centers.values()) <= 4, centers

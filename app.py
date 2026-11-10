"""쇼핑 리스트 앱 (Streamlit).

구조: 저장소(JSON 또는 SQL DB) → 아이템 조작(CRUD) → 입력 검증 → UI 콜백 → 렌더링.

- 저장소가 유일한 원본(source of truth)이다. 세션(탭)마다 리스트 사본을 들고 있지 않고,
  매 렌더링·매 조작마다 저장소에서 다시 읽는다. 그래서 여러 탭·여러 사용자가 동시에 써도
  서로의 변경을 덮어쓰지 않는다.
- 기본 저장소는 data/shopping_list.json (잠금 + 원자적 교체).
- st.secrets 에 [connections.shopping_db] url 이 있으면 SQL DB(예: PostgreSQL)를 사용한다.
  Streamlit Community Cloud 처럼 재시작 시 로컬 파일이 지워지는 환경에서 데이터를 보존하려면 DB를 설정한다.
- 상태 변경은 모두 위젯 콜백에서 처리하고, 위젯 key는 아이템 id 기반이다.

요구사항은 PRD.md 참조.
"""

import hmac
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "shopping_list.json"
DB_CONNECTION = "shopping_db"  # st.secrets 의 [connections.shopping_db]
MAX_NAME_LEN = 50
MAX_MEMO_LEN = 100
MAX_QTY = 9999


def _now() -> str:
    """현재 시각(UTC, 시간대 포함) ISO 8601 문자열."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _secret(*path):
    """st.secrets 값을 안전하게 읽는다. secrets 파일이 없거나 키가 없으면 None."""
    try:
        node = st.secrets
        for key in path:
            node = node[key]
        return node
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 데이터 정규화 (저장소에서 읽은 값이 잘못되어도 앱이 죽지 않도록)
# ---------------------------------------------------------------------------
def normalize_item(raw) -> dict | None:
    """저장소에서 읽은 아이템 1개를 PRD 5장 구조로 정리한다. 쓸 수 없는 값이면 None."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    qty = raw.get("quantity")
    if isinstance(qty, bool) or not isinstance(qty, (int, float, str)):
        qty = 1
    try:
        qty = int(qty)
    except ValueError:
        qty = 1
    memo = raw.get("memo")
    checked = raw.get("checked")
    created = raw.get("created_at") if isinstance(raw.get("created_at"), str) else ""
    updated = raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else created
    return {
        "id": str(raw["id"]) if raw.get("id") else str(uuid.uuid4()),
        "name": name.strip()[:MAX_NAME_LEN],
        "quantity": min(max(qty, 1), MAX_QTY),
        "memo": memo.strip()[:MAX_MEMO_LEN] if isinstance(memo, str) else "",
        # DB에 따라 bool 대신 1/0 으로 돌아오기도 한다 (예: SQLite). 문자열 등은 False.
        "checked": checked is True or (type(checked) is int and checked == 1),
        "created_at": created,
        "updated_at": updated,
    }


def normalize_items(raw) -> list[dict]:
    """아이템 목록 정리. 리스트가 아니면 빈 리스트, id 중복은 첫 번째만 유지."""
    if not isinstance(raw, list):
        return []
    items, seen = [], set()
    for r in raw:
        item = normalize_item(r)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# 저장소: JSON 파일
# ---------------------------------------------------------------------------
@st.cache_resource
def _file_lock() -> threading.Lock:
    """서버 프로세스 전체에서 공유하는 잠금 (스크립트가 다시 실행되어도 같은 객체)."""
    return threading.Lock()


def load_items() -> list[dict]:
    """JSON 파일에서 아이템 리스트를 읽는다. 파일이 없거나 손상되었으면 빈 리스트."""
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    return normalize_items(data)


def save_items(items: list[dict]) -> None:
    """아이템 리스트를 JSON 파일에 저장한다. 고유한 임시 파일에 쓴 뒤 교체해 손상을 방지."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / f".{DATA_FILE.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        tmp.replace(DATA_FILE)
    finally:
        tmp.unlink(missing_ok=True)


class JsonStore:
    """JSON 파일 저장소. 모든 변경은 잠금 안에서 '파일 읽기 → 수정 → 저장'으로 처리한다."""

    def all(self) -> list[dict]:
        with _file_lock():
            return load_items()

    def _mutate(self, fn):
        with _file_lock():
            items = load_items()
            result = fn(items)
            save_items(items)
            return result

    def add(self, item: dict) -> None:
        self._mutate(lambda items: items.append(item))

    def update(self, item_id: str, fields: dict) -> bool:
        def fn(items):
            for it in items:
                if it["id"] == item_id:
                    it.update(fields)
                    return True
            return False
        return self._mutate(fn)

    def delete(self, item_ids: set[str] | None = None, *, checked_only=False) -> int:
        """item_ids 가 None 이면 전체(또는 checked_only 면 체크된 것) 대상."""
        def fn(items):
            keep = [
                it for it in items
                if not ((item_ids is None or it["id"] in item_ids)
                        and (not checked_only or it["checked"]))
            ]
            removed = len(items) - len(keep)
            items[:] = keep
            return removed
        return self._mutate(fn)


# ---------------------------------------------------------------------------
# 저장소: SQL DB (선택)
# ---------------------------------------------------------------------------
class SqlStore:
    """SQL DB 저장소 (st.connection 사용). 각 조작은 단일 SQL 문이라 동시 접근에 안전하다."""

    COLUMNS = "id, name, quantity, memo, checked, created_at, updated_at"

    def __init__(self, conn):
        from sqlalchemy import text

        self.text = text
        self.engine = conn.engine
        with self.engine.begin() as c:
            c.execute(text(
                "CREATE TABLE IF NOT EXISTS shopping_items ("
                " id VARCHAR(36) PRIMARY KEY, name VARCHAR(200) NOT NULL,"
                " quantity INTEGER NOT NULL, memo VARCHAR(400) NOT NULL DEFAULT '',"
                " checked BOOLEAN NOT NULL DEFAULT FALSE, created_at VARCHAR(40) NOT NULL,"
                " updated_at VARCHAR(40) NOT NULL, sort_key BIGINT NOT NULL)"
            ))

    def _exec(self, sql, **params):
        with self.engine.begin() as c:
            return c.execute(self.text(sql), params)

    def all(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(self.text(
                f"SELECT {self.COLUMNS} FROM shopping_items ORDER BY sort_key"
            )).mappings().all()
        return normalize_items([dict(r) for r in rows])

    def add(self, item: dict) -> None:
        self._exec(
            f"INSERT INTO shopping_items ({self.COLUMNS}, sort_key) VALUES"
            " (:id, :name, :quantity, :memo, :checked, :created_at, :updated_at, :sort_key)",
            **item, sort_key=time.time_ns(),
        )

    def update(self, item_id: str, fields: dict) -> bool:
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        res = self._exec(f"UPDATE shopping_items SET {sets} WHERE id = :item_id",
                         **fields, item_id=item_id)
        return res.rowcount > 0

    def delete(self, item_ids: set[str] | None = None, *, checked_only=False) -> int:
        where, params = ["1=1"], {}
        if checked_only:
            where.append("checked = :t")
            params["t"] = True
        if item_ids is not None:
            names = [f":id{i}" for i in range(len(item_ids))]
            if not names:
                return 0
            where.append(f"id IN ({', '.join(names)})")
            params.update({f"id{i}": v for i, v in enumerate(item_ids)})
        return self._exec(f"DELETE FROM shopping_items WHERE {' AND '.join(where)}",
                          **params).rowcount


@st.cache_resource
def _sql_store():
    """secrets 에 DB 설정이 있을 때 SqlStore 를 1회 생성."""
    return SqlStore(st.connection(DB_CONNECTION, type="sql"))


def store():
    """현재 사용할 저장소."""
    if _secret("connections", DB_CONNECTION, "url") or _secret("connections", DB_CONNECTION, "dialect"):
        return _sql_store()
    return JsonStore()


# ---------------------------------------------------------------------------
# 아이템 조작 (PRD 8.3)
# ---------------------------------------------------------------------------
def _find(item_id: str) -> dict | None:
    """id로 아이템을 찾는다 (저장소 최신 상태 기준). 없으면 None."""
    return next((it for it in store().all() if it["id"] == item_id), None)


def add_item(name: str, quantity: int = 1, memo: str = "") -> dict:
    """새 아이템을 리스트 끝에 추가하고, 추가된 아이템을 반환한다."""
    now = _now()
    item = {"id": str(uuid.uuid4()), "name": name, "quantity": quantity, "memo": memo,
            "checked": False, "created_at": now, "updated_at": now}
    store().add(item)
    return item


def update_item(item_id: str, name: str, quantity: int, memo: str) -> bool:
    """아이템의 이름·수량·메모를 수정한다. 대상이 없으면 False."""
    ok = store().update(item_id, {"name": name, "quantity": quantity, "memo": memo,
                                  "updated_at": _now()})
    return ok


def delete_item(item_id: str) -> bool:
    """아이템을 삭제한다. 대상이 없으면 False."""
    removed = store().delete({item_id})
    return removed > 0


def toggle_item(item_id: str, checked: bool | None = None) -> bool:
    """체크 상태를 설정한다. checked 가 None 이면 반전. 대상이 없으면 False.
    화면의 체크박스 값(checked)을 그대로 쓰면, 다른 탭에서 바뀐 상태와 엇갈려도 사용자가 본 대로 저장된다."""
    if checked is None:
        item = _find(item_id)
        if item is None:
            return False
        checked = not item["checked"]
    ok = store().update(item_id, {"checked": bool(checked), "updated_at": _now()})
    return ok


def clear_checked() -> int:
    """체크된 아이템을 모두 삭제하고 삭제한 개수를 반환한다."""
    removed = store().delete(checked_only=True)
    return removed


def clear_all() -> int:
    """모든 아이템을 삭제하고 삭제한 개수를 반환한다."""
    removed = store().delete()
    return removed


# ---------------------------------------------------------------------------
# 입력 검증
# ---------------------------------------------------------------------------
def validate_input(name, quantity, memo="") -> tuple[str, int, str, str | None]:
    """이름·수량·메모를 정리하고 검증한다. (이름, 수량, 메모, 오류 메시지 또는 None)."""
    clean = (name or "").strip()
    clean_memo = (memo or "").strip()
    if not clean:
        return clean, 1, clean_memo, "아이템명을 입력해 주세요."
    if len(clean) > MAX_NAME_LEN:
        return clean, 1, clean_memo, f"아이템명은 {MAX_NAME_LEN}자 이하로 입력해 주세요."
    if len(clean_memo) > MAX_MEMO_LEN:
        return clean, 1, clean_memo, f"메모는 {MAX_MEMO_LEN}자 이하로 입력해 주세요."
    if isinstance(quantity, bool):
        quantity = None
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        return clean, 1, clean_memo, "수량은 1 이상의 정수로 입력해 주세요."
    if qty != quantity or not 1 <= qty <= MAX_QTY:
        return clean, 1, clean_memo, f"수량은 1~{MAX_QTY} 사이의 정수로 입력해 주세요."
    return clean, qty, clean_memo, None


def md_escape(text: str) -> str:
    """사용자 입력이 마크다운·Streamlit 서식(:red[..], :material/..:, 이모지 코드 등)으로
    해석되지 않도록 특수문자를 이스케이프한다."""
    specials = "\\`*_{}[]()<>#+-.!|~$:"
    return "".join("\\" + ch if ch in specials else ch for ch in text)


# ---------------------------------------------------------------------------
# UI 콜백 (위젯 상호작용 → 상태 변경은 모두 여기서 처리)
# ---------------------------------------------------------------------------
def _toast(message: str, icon: str = ":material/check_circle:") -> None:
    """다음 렌더링에서 보여줄 토스트 메시지를 등록한다."""
    st.session_state.setdefault("toasts", []).append((message, icon))


def _gone() -> None:
    """다른 탭에서 이미 삭제된 아이템을 조작했을 때 안내."""
    _toast("다른 곳에서 이미 삭제된 아이템입니다.", ":material/info:")


def _close_confirm() -> None:
    """다른 조작을 하면 열려 있던 전체 삭제 확인창을 닫는다."""
    st.session_state["confirm_clear_all"] = False


def on_add() -> None:
    """추가 폼 제출."""
    ss = st.session_state
    _close_confirm()
    name, qty, memo, error = validate_input(ss.get("new_name"), ss.get("new_qty", 1),
                                            ss.get("new_memo"))
    if error:
        ss["add_error"] = error
        return
    add_item(name, qty, memo)
    # 성공했을 때만 입력 필드 초기화 (검증 실패 시에는 입력값 유지)
    ss["new_name"], ss["new_qty"], ss["new_memo"] = "", 1, ""
    _toast(f"'{md_escape(name)}' 추가")


def on_toggle(item_id: str) -> None:
    """체크박스 변경 → 화면에 보이는 값 그대로 저장."""
    _close_confirm()
    if not toggle_item(item_id, st.session_state.get(f"chk_{item_id}")):
        _gone()


def on_start_edit(item_id: str) -> None:
    """편집 모드 진입. 편집 위젯 초기값을 세션 상태에 채운다."""
    _close_confirm()
    item = _find(item_id)
    if item is None:
        _gone()
        return
    ss = st.session_state
    ss["editing_id"] = item_id
    ss[f"edit_name_{item_id}"] = item["name"]
    ss[f"edit_qty_{item_id}"] = item["quantity"]
    ss[f"edit_memo_{item_id}"] = item["memo"]


def on_save_edit(item_id: str) -> None:
    """편집 저장. 검증 실패 시 편집 모드를 유지한다."""
    ss = st.session_state
    name, qty, memo, error = validate_input(
        ss.get(f"edit_name_{item_id}"), ss.get(f"edit_qty_{item_id}", 1),
        ss.get(f"edit_memo_{item_id}"),
    )
    if error:
        ss["edit_error"] = error
        return
    ss["editing_id"] = None
    if update_item(item_id, name, qty, memo):
        _toast(f"'{md_escape(name)}' 수정")
    else:
        _gone()


def on_cancel_edit() -> None:
    """편집 취소."""
    st.session_state["editing_id"] = None


def on_delete(item_id: str) -> None:
    """개별 삭제. 편집 중인 아이템이면 편집 모드도 해제."""
    _close_confirm()
    if st.session_state.get("editing_id") == item_id:
        st.session_state["editing_id"] = None
    item = _find(item_id)
    if item and delete_item(item_id):
        _toast(f"'{md_escape(item['name'])}' 삭제")


def on_clear_checked() -> None:
    """구매 완료 항목 일괄 삭제."""
    _close_confirm()
    removed = clear_checked()
    _toast(f"구매 완료 항목 {removed}개 삭제")


def on_request_clear_all() -> None:
    """전체 삭제 확인 단계 표시."""
    st.session_state["confirm_clear_all"] = True


def on_confirm_clear_all() -> None:
    """전체 삭제 실행."""
    removed = clear_all()
    st.session_state["editing_id"] = None
    _close_confirm()
    _toast(f"전체 {removed}개 삭제")


def on_cancel_clear_all() -> None:
    """전체 삭제 취소."""
    _close_confirm()


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------
# 정적 CSS만 사용 (사용자 입력은 절대 여기에 넣지 않는다).
CSS = """
<style>
/* 아이템 행: 체크박스·텍스트·버튼이 항상 한 줄에 있도록 (줄바꿈 금지) */
div[class*="st-key-row_"] {
    flex-wrap: nowrap !important;
}
/* 텍스트 영역이 남은 폭을 차지하고, 넘치면 그 안에서 줄바꿈 */
div[class*="st-key-row_"] > div:has([data-testid="stMarkdown"]) {
    flex: 1 1 0 !important;
    min-width: 0 !important;
}
.st-key-item_list [data-testid="stMarkdownContainer"] p {
    overflow-wrap: anywhere;
    margin: 0;
}
/* Streamlit 기본 음수 하단 여백(-1rem) 제거 → 텍스트 박스가 실제 높이를 가져 세로 중앙 정렬됨 */
div[class*="st-key-row_"] [data-testid="stMarkdown"] [data-testid="stMarkdownContainer"] {
    margin-bottom: 0 !important;
}
/* 체크박스 자체 여백 제거 → 텍스트와 세로 중앙 정렬 */
div[class*="st-key-row_"] [data-testid="stCheckbox"] label {
    margin: 0;
    padding: 0;
    min-height: 0;
}
/* 수정/삭제 아이콘 버튼: 터치 영역 44×44px 이상 (WCAG 2.5.5) */
div[class*="st-key-edit_"] button,
div[class*="st-key-del_"] button {
    min-width: 44px;
    min-height: 44px;
    justify-content: center;
}
/* 아이콘 버튼의 글자 라벨은 화면에서 숨기고 화면 낭독기에만 제공 */
div[class*="st-key-edit_"] button [data-testid="stMarkdownContainer"],
div[class*="st-key-del_"] button [data-testid="stMarkdownContainer"] {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
"""


def render_header(items: list[dict]) -> None:
    """제목과 진행 현황 (전체 N개 중 M개 완료 + 진행률 바)."""
    total = len(items)
    done = sum(1 for it in items if it["checked"])
    st.title("🛒 쇼핑 리스트")
    label = f"전체 {total}개 중 {done}개 완료"
    if total and done == total:
        label += " 🎉"
    st.progress(done / total if total else 0.0, text=label)


def render_add_form() -> None:
    """아이템 추가 폼 (한 줄: 아이템명 / 수량 / 메모 / 추가)."""
    st.session_state.setdefault("new_qty", 1)
    with st.form("add_form"):
        c1, c2, c3, c4 = st.columns([3, 1.4, 2.2, 1.2], vertical_alignment="bottom")
        c1.text_input("아이템명", key="new_name", max_chars=MAX_NAME_LEN,
                      placeholder="예: 우유")
        c2.number_input("수량", key="new_qty", min_value=1, max_value=MAX_QTY, step=1)
        c3.text_input("메모", key="new_memo", max_chars=MAX_MEMO_LEN, placeholder="선택")
        c4.form_submit_button("추가", icon=":material/add:", type="primary",
                              on_click=on_add, width="stretch")
    error = st.session_state.pop("add_error", None)
    if error:
        st.warning(error, icon=":material/warning:")


def render_toasts() -> None:
    """등록된 토스트를 표시하고 비운다."""
    for message, icon in st.session_state.pop("toasts", []):
        st.toast(message, icon=icon)


def item_markdown(item: dict) -> str:
    """아이템 표시용 마크다운. 사용자 입력은 모두 이스케이프한다."""
    name = md_escape(item["name"])
    qty = f":gray-badge[x{item['quantity']}]"
    if item["checked"]:
        text = f":gray[~~{name}~~] {qty}"
    else:
        text = f"**{name}** {qty}"
    if item["memo"]:
        text += f"  \n:small[:gray[{md_escape(item['memo'])}]]"
    return text


def render_item_row(item: dict) -> None:
    """아이템 한 줄(보기 모드): 체크박스 | 이름·수량·메모 | 수정 | 삭제."""
    item_id = item["id"]
    # 체크박스는 항상 저장소의 최신 값으로 맞춘다 (다른 탭에서 바뀐 경우 반영)
    st.session_state[f"chk_{item_id}"] = item["checked"]
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      gap="small", key=f"row_{item_id}"):
        st.checkbox(
            f"{md_escape(item['name'])} 구매 완료",
            key=f"chk_{item_id}",
            on_change=on_toggle,
            args=(item_id,),
            label_visibility="collapsed",
            width="content",
        )
        st.markdown(item_markdown(item), width="stretch")
        st.button("수정", icon=":material/edit:", key=f"edit_{item_id}", help="수정",
                  type="tertiary", on_click=on_start_edit, args=(item_id,))
        st.button("삭제", icon=":material/delete:", key=f"del_{item_id}", help="삭제",
                  type="tertiary", on_click=on_delete, args=(item_id,))


def render_edit_row(item: dict) -> None:
    """아이템 한 줄(편집 모드). 폼이라 Enter 키로 저장된다."""
    item_id = item["id"]
    with st.container(key=f"row_{item_id}"):
        with st.form(f"edit_form_{item_id}"):
            c1, c2, c3 = st.columns([3, 1.4, 2.2])
            c1.text_input("아이템명", key=f"edit_name_{item_id}", max_chars=MAX_NAME_LEN)
            c2.number_input("수량", key=f"edit_qty_{item_id}", min_value=1,
                            max_value=MAX_QTY, step=1)
            c3.text_input("메모", key=f"edit_memo_{item_id}", max_chars=MAX_MEMO_LEN)
            error = st.session_state.pop("edit_error", None)
            if error:
                st.warning(error, icon=":material/warning:")
            with st.container(horizontal=True, horizontal_alignment="right"):
                # Enter 키는 첫 번째 제출 버튼(저장)을 누른 것으로 처리된다
                st.form_submit_button("저장", key=f"save_{item_id}", type="primary",
                                      icon=":material/check:",
                                      on_click=on_save_edit, args=(item_id,))
                st.form_submit_button("취소", key=f"cancel_{item_id}",
                                      on_click=on_cancel_edit)


def render_list(items: list[dict]) -> None:
    """아이템 목록(미완료 → 완료 순) 또는 빈 상태 안내."""
    if not items:
        st.caption("🧺 쇼핑 리스트가 비어 있습니다. 위에서 살 물건을 추가해 보세요.",
                   text_alignment="center")
        return
    editing_id = st.session_state.get("editing_id")
    if editing_id and not any(it["id"] == editing_id for it in items):
        st.session_state["editing_id"] = editing_id = None  # 다른 곳에서 삭제됨
    ordered = sorted(items, key=lambda it: it["checked"])  # 안정 정렬: 추가 순서 유지
    with st.container(gap="small", key="item_list"):
        for item in ordered:
            if item["id"] == editing_id:
                render_edit_row(item)
            else:
                render_item_row(item)


def render_bulk_actions(items: list[dict]) -> None:
    """구매 완료 항목 지우기 / 전체 삭제(확인 단계 포함)."""
    if not items:
        _close_confirm()  # 리스트가 비면 열려 있던 확인창도 닫는다
        return
    has_checked = any(it["checked"] for it in items)
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.button("구매 완료 항목 지우기", icon=":material/playlist_remove:",
                  disabled=not has_checked, on_click=on_clear_checked)
        st.button("전체 삭제", icon=":material/delete_sweep:",
                  on_click=on_request_clear_all)
    if st.session_state.get("confirm_clear_all"):
        with st.container(border=True):
            st.warning(f"아이템 {len(items)}개를 모두 삭제할까요? 되돌릴 수 없습니다.",
                       icon=":material/warning:")
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.button("취소", key="cancel_clear_all", on_click=on_cancel_clear_all)
                st.button("삭제 확인", type="primary", on_click=on_confirm_clear_all)


# ---------------------------------------------------------------------------
# 접근 제한 (선택)
# ---------------------------------------------------------------------------
def check_password() -> bool:
    """secrets 에 app_password 가 설정되어 있으면 비밀번호를 확인한다. 없으면 통과."""
    expected = _secret("app_password")
    if not expected:
        return True
    if st.session_state.get("authenticated"):
        return True
    st.title("🛒 쇼핑 리스트")
    with st.form("login"):
        pw = st.text_input("비밀번호", type="password")
        if st.form_submit_button("들어가기", type="primary"):
            if hmac.compare_digest(pw.encode(), str(expected).encode()):
                st.session_state["authenticated"] = True
                st.rerun()
            st.error("비밀번호가 올바르지 않습니다.")
    return False


# ---------------------------------------------------------------------------
# 앱
# ---------------------------------------------------------------------------
def init_state() -> None:
    """세션 상태 초기화 (아이템 목록은 세션에 보관하지 않는다)."""
    ss = st.session_state
    ss.setdefault("editing_id", None)
    ss.setdefault("confirm_clear_all", False)


def main() -> None:
    """앱 진입점."""
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    if not check_password():
        return
    st.html(CSS)
    init_state()
    items = store().all()  # 렌더링마다 저장소에서 최신 상태를 읽는다
    render_header(items)
    render_add_form()
    render_list(items)
    render_bulk_actions(items)
    render_toasts()


if __name__ == "__main__":
    main()

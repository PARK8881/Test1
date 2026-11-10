# 쇼핑 리스트 앱 단계별 개발 프롬프트

> `PRD.md`를 바탕으로 단계별로 Claude Code에 그대로 붙여 넣어 사용하는 프롬프트입니다.
> 각 단계가 끝나면 직접 `streamlit run app.py`로 실행해 확인한 뒤 다음 단계로 넘어가세요.

---

## 1단계: 기본 뼈대 작성

```
PRD.md를 읽고, 쇼핑 리스트 앱의 기본 뼈대를 만들어줘.

[만들 파일]
- app.py, requirements.txt, .gitignore, README.md
- data/ 폴더 (shopping_list.json은 앱이 자동 생성)

[app.py 요구사항]
- PRD 8.3의 함수들을 모두 정의: load_items, save_items, add_item, update_item,
  delete_item, toggle_item, clear_checked
- 이번 단계에서는 데이터 계층만 실제로 구현하고, UI는 최소한으로만 둬:
  - 데이터 모델은 PRD 5장 구조(id, name, quantity, memo, checked, created_at, updated_at)를 그대로 따름
  - id는 uuid4, 시간은 ISO 8601 문자열
  - st.session_state["items"]로 상태를 관리하고, 앱 시작 시 load_items()로 1회만 초기화
  - 데이터 경로는 pathlib로 app.py 기준 상대경로 처리, 파일/폴더가 없거나 JSON이 깨졌으면 빈 리스트로 시작
- 화면에는 제목 "🛒 쇼핑 리스트"와 현재 아이템을 st.write로 출력하는 정도만
- main() 함수와 if __name__ == "__main__" 구조 사용, 함수마다 짧은 docstring

[requirements.txt]
- streamlit (최소 버전 명시)

[README.md]
- 설치, 실행 방법(streamlit run app.py) 간단히

완료 후 streamlit run app.py로 실행해서 오류 없이 뜨는지 확인하고, 만든 파일과 구조를 요약해줘.
아직 2단계 기능(입력 폼, 수정·삭제 버튼 등)은 만들지 마.
```

---

## 2단계: 기능 추가

```
PRD.md의 4장 기능 요구사항을 app.py에 구현해줘. 1단계에서 만든 데이터 함수를 재사용해.

[P0 필수 기능]
1. 아이템 추가 (PRD 4.1)
   - st.form(clear_on_submit=True)으로 아이템명(필수), 수량(기본 1, 최소 1 정수), 메모(선택)
   - Enter 또는 "추가" 버튼으로 등록
   - 검증: 공백 이름 → st.warning, 50자 초과 → 경고, 앞뒤 공백 strip
2. 아이템 수정 (PRD 4.2)
   - 각 행의 ✏️ 버튼 → 해당 행만 편집 모드 (session_state["editing_id"]로 관리)
   - 편집 모드에서 이름/수량/메모 수정 후 "저장"/"취소", 저장 시 4.1과 같은 검증
   - 한 번에 하나만 편집 가능, updated_at 갱신
3. 아이템 삭제 (PRD 4.3)
   - 각 행의 🗑️ 버튼으로 즉시 삭제
4. 아이템 체크 (PRD 4.4)
   - 체크박스로 checked 토글, 체크된 항목은 이번 단계에선 간단히 취소선(~~)만 표시

[P1 부가 기능]
5. "구매 완료 항목 지우기" 버튼 (체크된 항목이 없으면 비활성화)
6. "전체 삭제" 버튼 → 확인 단계(예: 확인 체크 또는 2단계 버튼) 후 초기화
7. 진행 현황: "전체 N개 중 M개 완료" + st.progress (아이템 0개일 때 0으로 나누기 방지)
8. 빈 상태 안내: "쇼핑 리스트가 비어 있습니다"
9. 모든 변경 직후 save_items() 호출해서 JSON에 저장

[구현 시 주의]
- 모든 위젯 key는 아이템 id 기반으로 고유하게 (예: f"chk_{id}", f"del_{id}")
- 버튼 콜백(on_click/on_change)을 사용해서 상태 변경 → 반복 문 안에서 리스트를 직접 수정하다 생기는 버그 방지
- 사용자 입력을 unsafe_allow_html로 렌더링하지 말 것

완료 후 실행해서 PRD 10장 Acceptance Criteria 항목을 하나씩 직접 확인하고 결과를 표로 알려줘.
디자인(CSS, 색상, 레이아웃 다듬기)은 3단계에서 할 거니 지금은 기능에만 집중해.
```

---

## 3단계: UI 디자인

```
PRD.md 6장 화면 구성을 기준으로 app.py의 UI를 다듬어줘. 기능 동작은 바꾸지 마.

[레이아웃]
- st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
- 상단: 제목 + 진행 현황(텍스트 + 진행률 바)
- 중간: 입력 폼을 한 줄로 (st.columns로 아이템명 / 수량 / 메모 / 추가 버튼 비율 조정)
- 리스트: 각 행을 [체크박스 | 이름·수량·메모 | ✏️ | 🗑️] 열로 정렬, 행 사이 구분선 또는 카드 형태
- 하단: "구매 완료 항목 지우기", "전체 삭제" 버튼

[스타일]
- 체크된 항목: 취소선 + 회색(흐린 색)으로 표시
- 수량은 "x2" 형태의 작은 배지, 메모는 작은 회색 글씨
- 미완료 항목을 위, 완료 항목을 아래로 정렬 (PRD 6장 P2)
- 필요하면 st.markdown + <style> 로 최소한의 CSS만 추가. 단, 사용자 입력(이름/메모)을
  HTML에 넣을 때는 반드시 html.escape() 처리
- 라이트/다크 테마 모두에서 글자가 잘 보이도록 고정 색 대신 투명도나 테마 변수 활용
- 추가/삭제/수정 완료 시 st.toast로 짧은 피드백

[모바일 대응]
- 폭 400px 화면에서도 버튼이 잘리거나 겹치지 않게, 터치하기 쉬운 크기
- 긴 아이템명(50자)이 줄바꿈되어도 레이아웃이 깨지지 않게

완료 후 데스크톱 폭과 모바일 폭(약 400px)에서 화면이 어떻게 보이는지 확인하고, 변경한 내용을 요약해줘.
```

---

## 4단계: PRD 준수 여부 및 버그 검토 (Playwright)

```
Playwright를 사용해서 app.py가 PRD.md대로 개발됐는지, 버그나 문제가 없는지 자세하게 검토해줘.

[준비]
- pip install pytest playwright pytest-playwright 후 playwright install chromium
- 테스트 전에 data/shopping_list.json을 백업하고 빈 상태로 시작, 테스트 후 원복
- streamlit run app.py --server.headless true --server.port 8501 을 백그라운드로 띄우고
  준비될 때까지 대기
- 테스트 코드는 tests/test_app_e2e.py 에 작성 (Streamlit은 rerun이 있으므로 각 동작 후
  요소가 나타날 때까지 expect로 기다리고, 고정 sleep은 피할 것)

[1. 기능 테스트 - PRD 10장 Acceptance Criteria + 4장 요구사항]
- 추가: 정상 추가, Enter 키 추가, 입력 필드 초기화 여부, 수량 기본값 1
- 검증: 빈 이름 / 공백만 / 51자 이름 / 수량 0 또는 음수 → 추가되지 않고 경고
- 수정: 편집 모드 진입, 저장 시 반영, 취소 시 원상태, 두 아이템 동시 편집 불가, 수정 시 빈 이름 거부
- 삭제: 개별 삭제 후 다른 아이템에 영향 없음 (특히 중간 아이템 삭제 시 체크 상태가 밀리지 않는지)
- 체크: 토글 시 취소선 표시, 진행률/카운트 갱신, 해제 시 복원
- 부가: 구매 완료 항목 일괄 삭제, 전체 삭제 확인 절차, 빈 상태 안내 문구
- 저장: 새로고침 후 리스트와 체크 상태 유지, JSON 파일 내용이 PRD 5장 데이터 모델과 일치

[2. 엣지 케이스 / 버그 탐색]
- 같은 이름 아이템 여러 개 추가 후 각각 수정·삭제·체크가 정확히 그 항목에만 적용되는지
- 특수문자/HTML 입력 (<script>alert(1)</script>, <b>굵게</b>, 이모지, 한글 50자) → 그대로 텍스트로 보이는지(XSS 없음)
- 아이템 100개 추가 후 조작 시 응답 시간 (PRD 7장: 1초 이내)
- 버튼 빠르게 연속 클릭, 편집 중 다른 행 삭제 등 상태 꼬임
- JSON 파일이 깨졌거나 없을 때 앱이 오류 없이 뜨는지
- 브라우저 콘솔 에러, Streamlit 예외 메시지(st.exception 박스) 발생 여부

[3. UI / 반응형]
- 1280px 데스크톱, 390px 모바일 뷰포트에서 각각 스크린샷을 tests/screenshots/ 에 저장
- 버튼 겹침, 가로 스크롤, 텍스트 잘림 여부 확인
- 다크 테마에서 글자 가독성 확인

[4. 코드 리뷰]
- app.py를 직접 읽고 PRD 8.3 함수 구조 준수 여부, 위젯 key 충돌 가능성, 예외 처리,
  unsafe_allow_html 사용 시 escape 처리, 배포(Streamlit Community Cloud) 시 문제 될 부분 점검

[결과 보고]
- 테스트 실행 결과(통과/실패 수)와 실패 로그
- 아래 형식의 표로 정리:
  | 번호 | 구분(PRD 미준수/버그/UX/보안/성능) | 심각도(높음/중간/낮음) | 내용 | 재현 방법 | 수정 제안 |
- PRD 10장 Acceptance Criteria 체크리스트별 충족 여부
- 이번 단계에서는 코드를 수정하지 말고 검토 결과만 보고해줘. 수정은 내가 확인한 뒤 요청할게.
```

---

## (선택) 5단계: 수정 및 배포

```
4단계 검토 결과 중 심각도 "높음", "중간" 항목을 수정하고, 4단계 Playwright 테스트를 다시 돌려서
모두 통과하는지 확인해줘. 이후 GitHub 업로드와 Streamlit Community Cloud 배포 절차를 PRD 9장에 맞게 안내해줘.
```

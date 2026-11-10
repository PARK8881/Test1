# 🛒 쇼핑 리스트

아이템 추가·수정·삭제·체크 기능을 가진 간단한 Streamlit 웹 앱입니다. 요구사항은 [PRD.md](PRD.md)를 참고하세요.

## 설치 / 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다.

## 데이터 저장

| 설정 | 저장 위치 | 비고 |
|---|---|---|
| 기본 (설정 없음) | `data/shopping_list.json` | 로컬 실행용. Streamlit Community Cloud 에서는 앱 재시작 시 **지워집니다**. |
| DB 설정 | PostgreSQL 등 SQL DB | 배포 시 권장. 재시작해도 데이터가 유지됩니다. |

여러 탭·여러 사용자가 동시에 사용해도 서로의 변경을 덮어쓰지 않습니다(매 조작마다 저장소에서 최신 상태를 읽고 바로 반영).

### 외부 DB 연결 (배포 시 데이터 보존)

1. 무료 PostgreSQL 을 만듭니다 (예: [Neon](https://neon.tech), [Supabase](https://supabase.com)) → 접속 URL 복사
2. 로컬은 `.streamlit/secrets.toml`, Cloud 는 앱 설정의 **Secrets** 에 입력:

```toml
[connections.shopping_db]
url = "postgresql+psycopg2://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

테이블(`shopping_items`)은 앱이 처음 실행될 때 자동으로 만들어집니다.

### 접근 비밀번호 (선택)

공개 URL 에 아무나 들어와 리스트를 바꾸지 못하게 하려면 secrets 에 추가:

```toml
app_password = "원하는-비밀번호"
```

## 테스트

```bash
pip install pytest pytest-playwright && playwright install chromium
python -m pytest tests/                                # 전체
python -m pytest tests/test_store.py                   # 저장소·검증 단위 테스트
python -m pytest tests/test_app_e2e.py -k two_tabs     # E2E 일부
```

E2E 테스트는 8502 포트(`APP_PORT` 로 변경 가능)에 테스트 서버를 직접 띄우고, `data/shopping_list.json` 을 백업했다가 끝나면 원복합니다.

# Obsidian Scheduler Bot

Obsidian Tasks를 기반으로 한 텔레그램 일정 관리 봇입니다.

## 기능

- 📅 **정기 알림**: 지정된 시간(9, 12, 15, 18, 21, 24시)에 자동으로 일정 알림
- 🔄 **자동 동기화**: 알림 전 Obsidian 레포 자동 pull
- 📋 **일정 파싱**: Obsidian Tasks 형식 지원 (due, scheduled, start, recurs)
- 🎛️ **버튼 메뉴**: 텔레그램 인라인 버튼으로 편리한 조작

## 사용 가능한 명령어

| 명령어   | 설명              |
| -------- | ----------------- |
| `/start` | 봇 시작           |
| `/today` | 오늘 일정 보기    |
| `/week`  | 이번 주 마감 일정 |
| `/all`   | 미완료 전체 목록  |
| `/sync`  | 수동 동기화       |
| `/help`  | 도움말            |

## 설정

### 1. 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 값을 설정하세요:

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
NOTIFICATION_HOURS=9,12,15,18,21,0
TIMEZONE=Asia/Seoul
```

### 2. Obsidian 서브모듈

```bash
git submodule update --init --recursive
```

## 실행 방법

### Docker (권장)

```bash
# 빌드 및 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
```

### 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 실행
python scheduler.py
```

## Obsidian Tasks 형식

지원하는 메타데이터:

```markdown
- [ ] 작업명 [due:: 2026-01-05] # 마감일
- [ ] 작업명 [scheduled:: 2025-12-20] # 예정일
- [ ] 작업명 [start:: 2025-12-01] # 시작일
- [ ] 작업명 🔁 every week # 반복
- [x] 완료 [completion:: 2025-12-22] # 완료일
```

## 폴더 구조

```
00-Scheduler-Bot/
├── .env                 # 환경 변수 (git 무시)
├── .env.example         # 환경 변수 템플릿
├── docker-compose.yml   # Docker Compose 설정
├── Dockerfile           # Docker 이미지 정의
├── requirements.txt     # Python 의존성
├── scheduler.py         # 메인 봇 코드
└── obsidian/            # Obsidian 서브모듈
    └── Todo Lists/      # 일정 파일들
```

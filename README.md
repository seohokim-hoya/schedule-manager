# Obsidian Scheduler Bot

Obsidian Tasks를 기반으로 한 텔레그램 일정 관리 봇입니다.

## 기능

- **정기 알림**: 설정된 시간에 자동으로 일정 알림 (텔레그램에서 설정 가능)
- **자동 동기화**: 알림 전 Obsidian 레포 자동 pull
- **일정 파싱**: Obsidian Tasks 형식 지원 (due, scheduled, start, recurs)
- **인라인 버튼**: Today / Week / Incomplete / Settings 메뉴
- **설정 관리**: 텔레그램 봇에서 알림 시간 추가/삭제, 테스트 모드 토글

## 사용 가능한 명령어

| 명령어      | 설명                 |
| ----------- | -------------------- |
| `/start`    | 메인 메뉴 표시       |
| `/today`    | 오늘 일정 보기       |
| `/week`     | 이번 주 일정 (월~일) |
| `/all`      | 미완료 전체 목록     |
| `/sync`     | 수동 동기화          |
| `/settings` | 설정 메뉴            |
| `/help`     | 도움말               |

## 설정

### 1. 환경 변수 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 값을 설정하세요:

```bash
cp .env.example .env
```

필수 설정:

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰 ([@BotFather](https://t.me/BotFather)에서 발급)
- `TELEGRAM_CHAT_ID`: 알림 받을 채팅 ID

Docker 환경에서 private 레포 사용 시:

- `GITHUB_TOKEN`: GitHub Personal Access Token
- `GITHUB_REPO`: HTTPS 형식의 레포 URL

### 2. 알림 설정 (config.yml)

`config.yml`에서 알림 시간, 타임존, 테스트 모드를 설정합니다.  
**텔레그램 봇의 Settings 메뉴에서도 수정 가능합니다.**

```yaml
notification_times:
  - "09:00"
  - "12:00"
  - "15:00"
  - "18:00"
  - "21:00"
  - "00:00"
timezone: Asia/Seoul
test_mode: false
```

### 3. Obsidian 서브모듈

```bash
git submodule update --init --recursive
```

## 실행 방법

### Docker (권장)

```bash
# 빌드 및 실행
docker compose up -d --build

# 로그 확인
docker compose logs -f

# 중지
docker compose down
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
- [ ] 작업명 [due:: 2026-01-05]                    # 마감일
- [ ] 작업명 [due:: 2026-01-05 14:00]              # 마감일 + 시간
- [ ] 작업명 [scheduled:: 2025-12-20]              # 예정일
- [ ] 작업명 [start:: 2025-12-01]                  # 시작일
- [ ] 작업명 [recurs:: every week]                 # 반복
- [x] 완료된 작업                                   # 완료 표시
```

### 시간/장소 형식 (확장)

`@[시간]/[장소]` 형식으로 시간 범위와 장소를 지정할 수 있습니다:

```markdown
- [ ] @[14:00-16:00]/[E3-1 3444] 그룹미팅 [scheduled:: 2026-01-07]
- [ ] @[09:00]/[온라인] 아침회의 [due:: 2026-01-08]
- [ ] @/[카페] 커피미팅 [due:: 2026-01-09]           # 시간 없이 장소만
- [ ] @[10:00] 발표 준비 [scheduled:: 2026-01-10]   # 장소 없이 시간만
```

### 메시지 표시 예시

```
14:00-16:00 · E3-1 3444 · PLRG
┃ 그룹미팅

all-day · Scspace  
┃ 일반 작업
```

## 폴더 구조

```
00-Scheduler-Bot/
├── .env                 # 환경 변수 (git 무시)
├── .env.example         # 환경 변수 템플릿
├── config.yml           # 알림 설정 (봇에서 수정 가능)
├── docker-compose.yml   # Docker Compose 설정
├── Dockerfile           # Docker 이미지 정의
├── requirements.txt     # Python 의존성
├── scheduler.py         # 메인 봇 코드
└── obsidian/            # Obsidian 서브모듈
    └── Todo Lists/      # 일정 파일들
```

## 라이선스

MIT License

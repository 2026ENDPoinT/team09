# AST 학습 창

SYNESIS 작업본에서 분리한 Swing 학습 창이에요. 복제 기준 커밋은 `c8b5c8b52088ab93f01f63de572e3ed0baeae843`이며, 당시 작업 폴더의 K1.2.5 엔진과 학습 화면 변경도 포함해요.

부모 저장소의 [설치 순서](../README.md#실행)에 따라 JDK 21과 Python 3.12로 빌드해요. 이 폴더에서 단독으로 열려면 다음 명령을 실행해요.

```sh
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
python3.12 -m venv .venv-pdf
.venv-pdf/bin/python -m pip install -r requirements-pdf.txt
./gradlew installDist
./run-study
```

**PDF 열기**를 누르거나 `./run-study "/absolute/path/강의자료.pdf"`로 파일을 지정해요. 단독 실행에서 AI 해설, 멘토, N제에 필요한 OpenAI 키는 이 폴더의 `.env` 또는 실행 환경에 설정해요. 생성 결과와 풀이 기록은 `.ast-study-data`에 저장돼요.

AST 앱에서는 **집중 모드 → 내 파일**에서 PDF를 열어요. 앱이 루트 `.env`에서 읽은 키를 전달하며 학습 기록은 AST의 계정별 `study/`에 저장돼요. 저장된 해설을 불러오거나 새 PDF의 강의 해설과 개념 정리를 K1.2.5로 생성해요.

학습 창을 변경한 뒤 `./gradlew installDist`로 다시 빌드해요. 숨김 창 검증은 `./gradlew astStudySmokeTest`로 실행해요.

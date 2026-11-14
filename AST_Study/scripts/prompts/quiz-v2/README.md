# SYNESIS 퀴즈 프롬프트 v4.12

최초 배분 1회에서 문항별 판단 목표를 만들고, 해당 목표를 공유하는 최대 10개 병렬 생성 호출로 문제집을 만든다. AI 검토·자동 보충·재배분·재생성은 호출하지 않는다. 모델은 gpt-6-luna로 고정하며 실제 사용량으로 크레딧을 정산한다.

## 프롬프트와 계약

- 배분: planner.md와 profilePolicy, 예산 내 완전한 planningEvidence를 사용한다. 전체 outline과 catalog의 제목·분량으로 관련 단락을 묶고 각 문항의 type/conceptIds/goal을 targets에 적는다. 별도 counts/focus/문항 ID는 출력하지 않는다. 문항 ID는 로컬에서 붙이고 형식별 수는 목표 목록에서 계산한다. planningEvidence에서 빠진 본문은 제목만 보고 세부 사실·특정 제작 절차를 추정하지 않는다.
- 생성: common.md + quality.md + 선택한 테마 파일 하나이다. 공통 범위·입출력 계약은 common, 정확성·문체는 quality, 테마별 판단 방식은 각 테마에 둔다. 프로필 목표와 실제 적합성은 구분한다. 참고 링크·README·다른 테마는 전송하지 않는다. 학습자료와 사용자 추가 요청은 사용자 메시지의 JSON으로만 전송한다.
- planner.schema.json은 새 묶음과 문항별 목표를 받는다. questions.schema.json은 runtime에서 배정된 목표 ID를 키로 갖는 questions 객체로 변환한다. 공통 문항 정의는 $defs/question 한 개이며 type/unitId/targetId/conceptIds는 모델이 다시 생성하지 않고 원래 배정값을 앱이 연결한다. 정답 본문·해설·distractors·calculations 및 인용 구간 ID만 생성한다. 저장·화면에서는 기존 보기 A~D와 정답 ID 형식을 유지한다.
- 테마 매핑: concept_completion → concept-completion.md, understanding → understanding.md, practice_set → practice-set.md, recall → recall.md.
- 배분은 high, 생성은 low 추론이며 두 호출 모두 service_tier=default를 명시한다. region_plan 등 다른 작업의 tier 정책은 그대로다. quiz_plan/quiz_questions에만 적용하고 다른 작업 설정은 유지한다. effort는 실제 wire·캐시 해시·사용량 원장에 포함되어 이전 effort 및 Fast 정책의 캐시와 구분된다. 두 호출의 출력 상한은 Luna가 지원하는 128,000토큰이다. 요청된 500,000토큰은 모델 한도를 넘어 사용할 수 없다. 상한은 목표 길이가 아니며 실제 사용량만 정산한다. 비용·크레딧 예약에는 최대 사용량이 반영된다. 출력 상한과 별도로 호출당 최대 4문항·최대 10병렬은 유지한다.

## 목표 공유와 유형 분포

assignment.tasks에는 이번 호출의 문항별 targetId/unitId/type/conceptIds/goal을 한 번씩 넣는다. sharedTargets에는 다른 호출의 `[목표ID, 유형, 개념ID들, 평가 초점]`만 남긴다. 자기 목표가 두 곳에 중복되지 않는다. 공통 본문은 최대 4문항 안에서 재사용하며, 실제 입력 한도를 초과하면 출처를 자르지 않고 더 나눈다. JSON 구분자 공백만 제거하고 원문·문자열 값은 보존한다. 다른 응답을 기다리지 않아 최대 10병렬을 유지한다. 실제 본문은 배정된 개념의 출처만 전달한다.

기본 typeCounts는 선택 유형의 수 차이가 최대 1인 배분이다. 문항이 충분하면 선택한 유형을 모두 사용하고, 나머지 문항은 테마에 맞는 유형부터 배정한다. 상·최상의 서답형도 미지 중간 결과를 사용해 최종 답을 구하며 답의 길이만 짧게 한다. 추가 요청에 유형별 수·비율이 명시된 경우만 최초 배분의 customTypeRatio=true로 해당 비율을 유지한다. ‘해설을 짧게’ 같은 일반 요구는 균등 배분을 해제하지 않는다. 생성 결과는 로컬에서 유형별로 교차 배치하며 모델의 형식별 수 이탈을 이유로 버리거나 다시 호출하지 않는다.

사용자 추가 요청은 주제 제한·제외·강조·질문 방식·표현·해설 길이를 포함하며 배분과 생성에 동일하게 전달한다. ‘A만/B 제외’는 범위 제한이고 ‘A 위주’는 비중이다. 유효한 요구를 구조화 설정·근거·정확성·출력 계약 안에서 반영한다. 원래 catalog와 허용 형식 밖의 요청이나 사실을 만들어야 하는 부분만 적용하지 않는다.

goal은 given/judgment/confusion 객체이다. given은 학생에게 제공할 필수 자료·조건의 짧은 명세이며, judgment는 학생이 답할 판단, confusion은 구별할 잘못된 이해이다. 별도 Blueprint나 추가 호출은 없다. 문자열·judgment/confusion·예전 given/derive/ask 목표는 계속 읽는다. 역할 구분은 계약상 보존하되 문자열 비교로 정답 누출을 판정하거나 문항을 탈락시키지 않는다. 원문 근거·표시 계약 검사는 의미적 품질 인증이 아니다.

## 생성 구조

고난도 서답형에 과제 유형을 순환 배정한 실험과 관측·추론·후속 질문을 별도 필드로 강제한 실험은 실제 난도 개선을 입증하지 못했다. 정의 회상·직접 대입 문항이 남고 해설이 중복되어 두 구조를 제거했다. 모든 유형은 표준 stem·answer·explanation을 사용한다. 고난도 지침은 관측에서 미지 조건·관계를 추론한 뒤 변경 상황에 적용하는 짧은 문단으로 유지한다. 형식 준수만으로 추론 깊이·계산 모델링·실제 난이도가 보장되지 않으며, 이 한계를 숨기거나 난도 미달 문항을 탈락시키지 않는다.

calculations는 name/expression 목록이다. 숫자는 정확한 유리수로 계산하고 제곱근의 무리수는 근삿값 표시를 붙인다. 본문·정답·해설·선지의 {{name}}을 같은 계산값으로 표시한다. 별도 목록 없이 {{=3/2}}처럼 쓴 제한된 인라인 식도 같은 해석기로 표시한다. 이름을 재사용할 때만 calculations 목록이 필요하다. eval/exec, 속성 접근, 임의 함수·코드 실행은 허용하지 않는다. 길이·노드·깊이·정수 크기·지수에 한도를 둔다. 계산 불가 시 원문 슬롯과 안내를 보존하며 문항을 버리거나 재호출하지 않는다. 계산식 선택·단위 모델링·조건 충분성은 자동 보증하지 않는다. 기존 저장 문항은 재계산하지 않는다.

## 범위와 출처

앱 개념 탭의 실제 상위·하위 구조를 outline으로 재사용하고 선택 페이지 범위의 개념만 catalog에 넣는다. 고정 개념 수·글자 수 대신 실제 입력·출력 한도에서 나누고 여러 논리 배정을 한 요청에 담아 공통 본문을 재사용한다. 개별 targets는 분할 후에도 정확히 한 배정에 속하며 필요한 개념을 함께 유지한다. 한 문항의 통합 근거 자체가 입력 한도를 넘으면 내용을 자르거나 목표를 복제하지 않고 미생성 사유를 남긴다.

sourceKind=ai_transcription은 저장된 PDF 영역 전사이고 saved_concept는 재서술된 개념 설명이다. visual region과 page-analysis의 ID가 달라도 같은 문서·선택 페이지·겹치는 영역(IoU ≥ 0.25)의 완료된 전사를 연결한다. ready 분석과 complete 요소이며 불확실 표시가 없는 경우만 사용한다. OCR·시각적 추론 설명이나 페이지 전체를 영역 전사로 승격하지 않는다.

항목의 모든 근거를 연결하면 재서술 대신 전사를 보내고 개념 전체를 연결하면 제목도 전사 요소 제목으로 구성한다. 일부만 연결되면 전사와 저장된 설명을 구별해 함께 보내고 전사를 우선한다. 전사가 없으면 기존 저장 설명을 유지한다. 쉬운 설명·추가 비유는 제외한다. 본문은 잘라 버리지 않고 연속된 quoteId 구간으로 전송한다. 원본 PDF·저장 개념·기존 문제집은 덮어쓰지 않는다. 정책 버전과 실제 출제 근거도 studySignature에 포함한다.

객관식 정답 본문과 해설은 한 번만 생성하고 앱이 정답 보기와 ID를 조립한다. explanation을 answer 앞에 강제한 실험은 계산 오류 감소가 입증되지 않아 제거했다. 이 조립 방식은 의미·계산 정확성을 보장하지 않는다. 서답형·서술형은 자동 정오 판정 없이 모범답안과 비교한다. 난이도 정책은 quality.md에서 배분과 생성이 공유한다. 튜터에는 문제·사용자 답·정답/모범답안·출처를 전달한다.

## 표시·저장·사용량

생성된 questions의 모든 항목을 표시한다. 기존 구조·배정 범위·출처 확인에서 문제가 생기면 warnings와 rawQuestion을 보존한다. 확인되지 않은 인용은 PDF 링크로 꾸미지 않는다. 선택지/정답 형식을 표시할 수 없으면 원래 선택지를 본문에 남기고 모범답안 비교 방식으로 표시한다. 답을 임의로 복구하거나 새 보기를 만들지 않는다. 같은 지문·초과 문항도 보존하며 의미 검증·AI 검토·재호출은 없다. 응답 자체가 파싱 불가능해 questions 배열을 얻을 수 없는 실패는 문항을 만들어내지 않는다.

난이도 부족으로 미생성을 지시하지 않는다. 근거 범위에서 조건·질문을 조정해 배정 수를 최대한 채운다. 모델이 실제로 반환하지 않은 문항은 추가 호출로 보충하지 않으며, actual/requested를 구분한다. 주어·목적어·대상 및 전후 상태를 명시하는 문장 규칙은 모든 과목에 적용한다.

각 응답의 완료 문항을 즉시 questions에 저장하고 candidateQuestions는 빈 배열, quality.status는 disabled이다. 문항·문제집 ID 및 이미 보인 객관식 보기 순서를 유지해 늦게 도착한 응답으로 기존 답변을 초기화하지 않는다. 부족하면 unfilled·completionStatus=partial과 ‘추가 호출 없이 보관’ 사유를 기록하고 완료로 가장하지 않는다. refillRounds는 호환을 위해 0으로 보존한다.

generated/quiz-v2/runs/실행ID.json, last-attempt.json 및 latest.json에 배분 결과·문항·미생성 사유·시간·runUsage를 저장한다. 0문항 실패가 이전 유효한 latest를 지우지 않는다. generationAudit은 표시 안내 기록이며 AI 품질 보증이 아니다. 이미 있는 문제집의 열기·답변·진도 저장은 모델을 호출하지 않는다.

취소·크레딧/비용 한도 시 미전송 호출을 멈추고 완료된 응답과 사용량을 보관한다. 비용·응답이 불명확하면 0원으로 처리하지 않는다. 자동 보충 비용은 더 발생하지 않는다. 기존 reviewer/completion 모듈과 과거 output/quiz-quality 기록은 과거 분석 호환용으로만 남는다.

## 참고한 GitHub 지침

전문 시험 전용 내용을 SYNESIS에 맞게 재구성했다. 다음 설계 참고가 실제 문항 품질을 입증하는 것은 아니다.

- [question-engine / generator](https://github.com/jimmyleepruitt/question-engine/blob/main/skills/generator.md): 학습 목표·근거 → 정답 풀이 → 오답 → 해설 순서, 명확한 질문 대상.
- [question-engine / distractor-validator](https://github.com/jimmyleepruitt/question-engine/blob/main/skills/distractor-validator.md): 오답별 타당성, 정답과 동시 성립하는 선지, 조건 부족의 구별.
- [question-engine / calibration-anchors](https://github.com/jimmyleepruitt/question-engine/blob/main/skills/calibration-anchors.md): 실제 사고 수준, 선지 단서, 이유 없는 해설의 배제.
- [exam-generator / generate](https://github.com/datmit2007/exam-generator/blob/main/references/generate.md): 출제 구성 선행, 방법 선택·조건 처리, 숫자·이름만 바꾸지 않는 변형.
- [exam-generator / review](https://github.com/datmit2007/exam-generator/blob/main/references/review.md): 가정·수치·단위·복수 정답·문항 간 의존성, 열린 답안의 다양성.

2026-10-23 추가 조사: Microsoft prompts-for-edu의 진단 퀴즈, SkillMedev quiz-generator, Hamburg HUL의 사례형 문항, Reddit WGU 학습 프롬프트를 비교했다. 학습목표·오개념별 오답·새 상황 적용을 반영하되 다중 검수·재생성·상담 단계는 가져오지 않았다. X 재게시 자료의 출제 확률 추정은 채택하지 않았다. Threads는 검색했으나 비교에 사용할 원문을 확인하지 못했다. 외부 프롬프트의 존재나 사용자 추천은 효과가 검증됐다는 뜻이 아니다.

전수 검토 범위는 활성 planner/common/quality/4개 테마와 schema, 비활성 reviewer 및 legacy quiz.md이다. reviewer/completion은 운영 생성 경로에 연결하지 않는다. v4.6의 실제 비교 결과와 원문 링크는 output/quiz-quality/20261023-luna-construction에 기록한다.


v4.7 비교: output/quiz-quality/20261023-scoped-generation/report.html에 4개 PDF의 분할 크기·목표·응답 구조·수치 표기·난도 실험을 기록한다. 1문항씩 호출하기와 의존성을 더 강하게 지시한 문장은 기본값으로 채택하지 않았다. 상·최상 서답형의 실제 난도와 관계식 선택 오류는 여전히 남으며 형식 스키마가 이를 보증하지 않는다. 추가 AI 검증·재생성·필터링은 없다.

## v4.11 계획 일관성

목표의 원문 근거·관점과 모드 수행이 수량보다 우선한다. 생성자는 같은 개념 범위·모드 안에서 잘못된 계획 전제를 바로잡을 수 있고, 유효한 질문을 만들 수 없으면 기존 unfilled로 남긴다. 새 검수/재시도 호출은 없다. rawPlan과 targetGoal을 보존하고 targetExecution에 실제 질문을 나란히 저장한다. comparisonStatus는 not_semantically_evaluated이며 코드가 의미 조정 여부를 자동 인증하지 않는다.

배정은 원래 type/profile/goal을 변경하지 않는 최대 조합을 선택한다. 목표 수·유형 quota·general/advanced 상한 안에서 선택하며 불가능한 부분은 unallocated, 제외 목표는 targetSelection에 원래 인덱스와 함께 남긴다. 레거시 profile 없는 목표는 unspecified로 읽는다. 목표 선택은 데이터 계약 처리이지 의미 품질 평가가 아니다.

## v4.12 개념완성 및 OX 계약

개념완성의 profilePolicy는 general=전체수, advanced=0이다. 같은 policy를 목표 선택의 프로필 상한과 advancedShortfall 계산에서 사용하므로 기본 확인 목표를 심화 비율 때문에 자르지 않는다. 생성에는 원래 개념완성 theme과 general 목표를 전달한다. 다른 세 모드는 기존 혼합 목표를 유지한다. 저장 문항을 재분류하지 않는다.

실제 keyed 생성 스키마의 question_ox.answer는 enum [O,X]이며 explanation은 별도이다. 기존 배열 응답·원본 및 잘못된 OX의 경고/비교 표시를 유지한다. 형식 실패를 문자열 자르기로 고치거나 정상 서술형 계약 통과로 간주하지 않는다.

## v4.13 제시문과 질문 표시

기존 생성 호출에서 passage(필요한 제시문·조건, 없으면 빈 문자열)와 stem(질문 또는 OX 판단 진술)을 분리한다. 계산값을 두 필드에 적용한 뒤 `### 제시문`·`### 문제/판단할 진술` 경계가 있는 기존 stem 문자열로 저장한다. 추가 AI 호출·검수·재생성은 없고 이전 문자열 형식도 읽는다. OX 선택 안내는 앱이 항상 표시한다. ‘자료’라는 모호한 주어와 본문 속 객관식 선지 중복은 출제 지침에서 피한다.

이전 문항의 배경/판단을 추측해 분리하거나 정답을 변경하지 않는다. 저장된 객관식의 본문 끝에 실제 보기 네 개가 완전히 일치하는 중복 목록이 있을 때만 표시 순서를 현재 options 순서에 맞춘다. 보기 ID·정답 ID·저장한 선택은 유지하며, 코드·수식·조건 목록이나 모호한 일치는 고치지 않는다.

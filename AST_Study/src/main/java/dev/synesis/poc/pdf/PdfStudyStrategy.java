package dev.synesis.poc.pdf;

/** Shared default for interactive and queued summary/concept generation. */
final class PdfStudyStrategy {
    static final String DEFAULT = "newest-k1-2-5";
    static final String VER02_PROMPT = "new-concept-study-ver0.2";
    static final String VER99_PROMPT = "new-concept-study-ver.99";

    static final String K1_PROMPT = "Newest_K1-v1";
    static final String K11_PROMPT = "Newest_K1.1-v1";
    static final String K1_1_1_PROMPT = "Newest_K1.1.1-v1";
    static final String K1_1_2_PROMPT = "Newest_K1.1.2-v1";
    static final String K1_1_3_PROMPT = "Newest_K1.1.3-v1";
    static final String K1_2_0_PROMPT = "Newest_K1.2.0-v1";
    static final String K1_2_1_PROMPT = "Newest_K1.2.1-v1";
    static final String K1_2_2_PROMPT = "Newest_K1.2.2-v1";
    static final String K1_2_4_PROMPT = "Newest_K1.2.4-v1";
    static final String K1_2_3_PROMPT = "Newest_K1.2.3-v1";
    static final String K1_2_5_PROMPT = "Newest_K1.2.5-v1";
    static final String K111_PROMPT = "Newest_K1.11-v1";
    static final String[] ENGINE_IDS = {"new-concept-v99","newest-m1","newest-k1","newest-k1-1","newest-k1-11","newest-k1-1-1","newest-k1-1-2","newest-k1-1-3","newest-k1-2-0","newest-k1-2-1","newest-k1-2-2","newest-k1-2-3","newest-k1-2-4","newest-k1-2-5"};
    static final String[] ENGINE_LABELS = {
        "ver.99_기존 개념 해설",
        "m1_강의해설 실험",
        "K1_원문 중심 / 병렬 생성",
        "K1.1_앞부분 우선 / 목차 위계",
        "K1.11_주제 구조화",
        "K1.1.1_단일 묶음 / 병렬 생성",
        "K1.1.2_분류 묶음 / 응답 복구",
        "K1.1.3_선별 검토 / 범위 점검",
        "1.2.0_실시간 응답 / 복구",
        "1.2.1_수식·코드 검산",
        "1.2.2_근거 축약 / 캐시 최적화",
        "1.2.3_기본 안정형 / 예제 일부",
        "1.2.4_예제 제거 실험 / 누락 가능",
        "1.2.5_선별 예제 축약 / 원리 우선"
    };
    static boolean selectable(String value){return java.util.Arrays.asList(ENGINE_IDS).contains(value);}
    private PdfStudyStrategy() {}
}

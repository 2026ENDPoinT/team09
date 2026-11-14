package dev.synesis.poc.pdf;

import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/** Immutable question data shared by generated questions and explicit local previews. */
record QuizQuestion(String id, String documentId, Type type, String concept, String stem,
                    List<Option> options, String answer, String explanation,
                    List<String> keyPoints, List<Evidence> evidence, boolean preview, List<String> conceptIds, List<String> warnings, String answerContractVersion, String profile) {
    QuizQuestion(String id,String documentId,Type type,String concept,String stem,List<Option> options,
                 String answer,String explanation,List<String> keyPoints,List<Evidence> evidence,boolean preview,List<String> conceptIds,List<String> warnings) {
        this(id,documentId,type,concept,stem,options,answer,explanation,keyPoints,evidence,preview,conceptIds,warnings,"","");
    }
    QuizQuestion(String id,String documentId,Type type,String concept,String stem,List<Option> options,
                 String answer,String explanation,List<String> keyPoints,List<Evidence> evidence,boolean preview,List<String> conceptIds) {
        this(id,documentId,type,concept,stem,options,answer,explanation,keyPoints,evidence,preview,conceptIds,List.of());
    }
    // Keep existing previews and saved-question callers source/binary compatible.
    QuizQuestion(String id,String documentId,Type type,String concept,String stem,List<Option> options,
                 String answer,String explanation,List<String> keyPoints,List<Evidence> evidence,boolean preview) {
        this(id,documentId,type,concept,stem,options,answer,explanation,keyPoints,evidence,preview,List.of());
    }
    enum Type {
        OX("OX"), MCQ("4지선다"), SHORT_ANSWER("서답형"), ESSAY("서술형");
        private final String label;
        Type(String label) { this.label = label; }
        String label() { return label; }
        String displayName() { return label; }
        boolean selfComparison() { return this == SHORT_ANSWER || this == ESSAY; }
    }

    record Option(String id, String text, String explanation, String optionId) {
        Option(String id,String text,String explanation) { this(id,text,explanation,""); }
        Option {
            optionId = optional(optionId);
            id = required(id, "선지 ID").strip();
            text = required(text, "선지 내용");
            explanation = optional(explanation);
        }
    }

    record Evidence(String sourceId, int page, String quote, String sourceKind,
                    List<String> originalSourceIds, boolean standardKnowledgeUsed) {
        Evidence(String sourceId, int page, String quote) {
            this(sourceId,page,quote,"pdf",List.of(),false);
        }
        Evidence {
            sourceId = optional(sourceId).strip();
            if (page < 0) throw new IllegalArgumentException("근거 쪽수는 음수일 수 없어요.");
            quote = optional(quote);
            sourceKind = optional(sourceKind).strip();
            originalSourceIds = List.copyOf(originalSourceIds == null ? List.of() : originalSourceIds);
        }
    }

    QuizQuestion {
        profile = optional(profile);
        answerContractVersion = optional(answerContractVersion);
        id = required(id, "문항 ID").strip();
        documentId = optional(documentId).strip();
        type = Objects.requireNonNull(type, "문제 형식이 필요해요.");
        concept = optional(concept);
        stem = required(stem, "문제 본문");
        options = List.copyOf(options == null ? List.of() : options);
        answer = required(answer, "정답 또는 모범답안");
        explanation = optional(explanation);
        keyPoints = List.copyOf(keyPoints == null ? List.of() : keyPoints);
        evidence = List.copyOf(evidence == null ? List.of() : evidence);
        conceptIds = List.copyOf(conceptIds == null ? List.of() : conceptIds);
        warnings = List.copyOf(warnings == null ? List.of() : warnings);
        if (!preview && documentId.isBlank())
            throw new IllegalArgumentException("문제의 PDF 문서 ID가 필요해요.");
        if (type == Type.MCQ) {
            if (options.size() != 4) throw new IllegalArgumentException("4지선다는 선지가 4개여야 해요.");
            var ids = new HashSet<String>();
            for (Option option : options)
                if (!ids.add(option.id())) throw new IllegalArgumentException("선지 ID는 서로 달라야 해요.");
            answer = answer.strip();
            if (!ids.contains(answer)) throw new IllegalArgumentException("정답이 실제 선지 ID와 일치해야 해요.");
            stem = QuizStemPresentation.alignOptions(stem,options);
        } else {
            if (!options.isEmpty()) throw new IllegalArgumentException("선지는 4지선다에만 사용할 수 있어요.");
            if (type == Type.OX) {
                answer = answer.strip().toUpperCase(Locale.ROOT);
                if (!answer.equals("O") && !answer.equals("X"))
                    throw new IllegalArgumentException("OX 정답은 O 또는 X여야 해요.");
            }
        }
        for (String point : keyPoints) Objects.requireNonNull(point, "핵심 요소는 null일 수 없어요.");
    }

    boolean selfComparison() { return type.selfComparison(); }

    private static String required(String value, String name) {
        if (value == null || value.isBlank()) throw new IllegalArgumentException(name + "이 필요해요.");
        return value;
    }
    private static String optional(String value) { return value == null ? "" : value; }
}

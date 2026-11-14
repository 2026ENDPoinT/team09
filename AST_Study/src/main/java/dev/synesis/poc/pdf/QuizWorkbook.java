package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;

/** One generated set and its metadata; opening it never generates more questions. */
record QuizWorkbook(String id,String documentId,String title,QuizPanel.Theme theme,String difficulty,
                    int requestedCount,long createdAtMs,double elapsedSeconds,Double totalUsd,
                    String note,List<QuizQuestion> questions) {
    private static final DateTimeFormatter TITLE_DATE=DateTimeFormatter.ofPattern("MM.dd HH:mm:ss")
        .withZone(ZoneId.of("Asia/Seoul"));

    record Answer(String answer,boolean revealed,boolean bookmarked,boolean skipped) {
        Answer(String answer,boolean revealed) {this(answer,revealed,false,false);}
        Answer { answer=answer==null?"":answer; }
    }

    QuizWorkbook {
        if(id==null||id.isBlank()||documentId==null||documentId.isBlank())
            throw new IllegalArgumentException("문제집 식별자가 필요해요.");
        theme=Objects.requireNonNull(theme);
        if(!QuizPanel.LEVELS.contains(difficulty))throw new IllegalArgumentException("문제집 난이도를 확인해 주세요.");
        questions=List.copyOf(questions);
        if(questions.isEmpty()||requestedCount<1||requestedCount>120)
            throw new IllegalArgumentException("문제집의 문항 수가 올바르지 않아요.");
        Set<String> ids=new HashSet<>();
        for(QuizQuestion question:questions)
            if(question.preview()||!documentId.equals(question.documentId())||!ids.add(question.id()))
                throw new IllegalArgumentException("현재 PDF의 생성 문제만 문제집에 담을 수 있어요.");
        if(createdAtMs<0||!Double.isFinite(elapsedSeconds)||elapsedSeconds<0
                ||totalUsd!=null&&(!Double.isFinite(totalUsd)||totalUsd<0))
            throw new IllegalArgumentException("문제집 생성 정보를 확인해 주세요.");
        title=title==null||title.isBlank()?theme.title+" 문제집":title.strip();
        note=note==null?"":note;
    }

    String levelDescription() {
        // Purpose is neutral about the distribution of legacy concept books.
        if(theme==QuizPanel.Theme.CONCEPT)return "기본 개념 확인";
        long general=questions.stream().filter(q->q.profile().equals("general")).count();
        long advanced=questions.stream().filter(q->q.profile().equals("advanced")).count();
        if(general+advanced==0)return "난이도 "+difficulty;
        long unspecified=questions.size()-general-advanced;
        return "일반 "+general+" · 심화 "+advanced
            +(unspecified>0?" · 미지정 "+unspecified:"")+" (적합성 미확인)";
    }

    QuizWorkbook withTitle(String name) {
        return new QuizWorkbook(id,documentId,name,theme,difficulty,requestedCount,createdAtMs,elapsedSeconds,totalUsd,note,questions);
    }

    static QuizWorkbook fromResult(JsonObject value) {
        String documentId=text(value,"documentId");
        QuizGenerationData.Result parsed=QuizGenerationData.parse(value,documentId);
        JsonObject setup=value.has("quiz")&&value.get("quiz").isJsonObject()?value.getAsJsonObject("quiz"):new JsonObject();
        QuizPanel.Theme theme=switch(text(setup,"theme")) {
            case "understanding"->QuizPanel.Theme.UNDERSTANDING;
            case "practice_set"->QuizPanel.Theme.PRACTICE;
            case "recall"->QuizPanel.Theme.RECALL;
            default->QuizPanel.Theme.CONCEPT;
        };
        String difficulty=text(setup,"difficulty");
        if(!QuizPanel.LEVELS.contains(difficulty))difficulty="중";
        String id=text(value,"quizRunId");
        if(id.isBlank()) {
            // Stable for legacy latest/request copies; file names never define
            // workbook identity and repeated opens never make a new workbook.
            String identity=documentId+"\n"+String.join("\n",parsed.questions().stream().map(QuizQuestion::id).toList());
            id="legacy-"+UUID.nameUUIDFromBytes(identity.getBytes(StandardCharsets.UTF_8));
        }
        long created=positiveLong(value,"startedAtMs");
        if(created==0)created=positiveLong(value,"completedAtMs");
        String title=theme.title+" 문제집"+(created>0?" · "+TITLE_DATE.format(Instant.ofEpochMilli(created)):"");
        return new QuizWorkbook(id,documentId,title,theme,difficulty,parsed.requestedCount(),created,
            parsed.elapsedSeconds(),parsed.totalUsd(),parsed.note(),parsed.questions());
    }

    private static String text(JsonObject value,String key) {
        JsonElement field=value==null?null:value.get(key);
        return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isString()?field.getAsString():"";
    }
    private static long positiveLong(JsonObject value,String key) {
        try {
            JsonElement field=value.get(key);
            return field!=null&&field.isJsonPrimitive()&&field.getAsJsonPrimitive().isNumber()
                ?Math.max(0,field.getAsBigDecimal().longValueExact()):0;
        } catch(ArithmeticException invalid){return 0;}
    }
}

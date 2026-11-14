package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** The desktop/worker boundary for quiz requests and completed results. */
final class QuizGenerationData {
    record Result(List<QuizQuestion> questions,double elapsedSeconds,Double totalUsd,int requestedCount,String note) {
        Result { questions=List.copyOf(questions); }
    }

    private QuizGenerationData() {}

    static boolean ready(JsonObject study) {
        if(study==null)return false;
        try {validateStudy(study,text(study,"documentId"));return true;}
        catch(IllegalArgumentException invalid){return false;}
    }

    static JsonObject request(QuizPanel.GenerationRequest setup,JsonObject study,String strategy,String documentId) {
        Objects.requireNonNull(setup,"문제 설정이 필요해요.");
        JsonArray concepts=validateStudy(study,documentId);
        if(setup.totalCount()<1 || setup.totalCount()>120)throw invalid("총 문제 수는 1~120개로 설정해 주세요.");
        QuizPanel.Configuration configuration=Objects.requireNonNull(setup.configuration());
        if(configuration.instructions().length()>2000)throw invalid("추가 요청은 2,000자 이내로 입력해 주세요.");
        JsonObject quiz=new JsonObject();
        quiz.addProperty("theme",theme(setup.theme()));quiz.addProperty("totalCount",setup.totalCount());
        quiz.addProperty("difficulty",configuration.difficulty());
        JsonArray formats=new JsonArray();
        for(QuizQuestion.Type type:QuizQuestion.Type.values())if(configuration.types().contains(type))formats.add(type(type));
        quiz.add("allowedTypes",formats);quiz.addProperty("instructions",configuration.instructions());
        JsonObject request=new JsonObject();request.add("quiz",quiz);request.add("studyContent",study.deepCopy());
        request.addProperty("documentId",documentId);request.addProperty("strategy",strategy);
        request.addProperty("startPage",configuration.start());request.addProperty("endPage",configuration.end());
        JsonArray groups=new JsonArray();
        for(ConceptOutline.Group group:ConceptOutline.groups(study)) {
            JsonObject section=new JsonObject();section.addProperty("id",group.id());section.addProperty("title",group.title());
            JsonArray indexes=new JsonArray();group.concepts().forEach(indexes::add);section.add("conceptIndexes",indexes);
            JsonArray path=new JsonArray();
            for(ConceptOutline.Heading heading:group.path()) {
                JsonObject item=new JsonObject();item.addProperty("id",heading.id());item.addProperty("title",heading.title());path.add(item);
            }
            section.add("path",path);groups.add(section);
        }
        // Old saved products can have useful concept cards without a hierarchy.
        if(groups.isEmpty()) {
            JsonObject section=new JsonObject();section.addProperty("id","concepts");section.addProperty("title","전체 개념");
            JsonArray indexes=new JsonArray();for(int i=0;i<concepts.size();i++)indexes.add(i);
            section.add("conceptIndexes",indexes);section.add("path",new JsonArray());groups.add(section);
        }
        request.add("studyGroups",groups);
        return request;
    }

    private static JsonArray validateStudy(JsonObject study,String documentId) {
        if(documentId==null || documentId.isBlank() || study==null || !documentId.equals(text(study,"documentId")))
            throw invalid("현재 PDF의 개념 정리가 필요해요.");
        if(bool(study,"livePreview") || "partial".equals(text(study,"kind")) || bool(study,"integrationPending")
            || study.has("processingComplete")&&!bool(study,"processingComplete"))
            throw invalid("개념 정리가 완료된 뒤 문제를 출제해 주세요.");
        JsonArray concepts=array(study,"concepts");
        if(concepts.isEmpty())throw invalid("개념 탭에 정리된 개념이 필요해요.");
        boolean hasContent=false;
        for(JsonElement value:concepts) {
            JsonObject concept=object(value,"개념 데이터");
            if(text(concept,"name").isBlank())throw invalid("개념 이름을 확인할 수 없어요.");
            JsonArray entries=concept.has("entries")?array(concept,"entries"):new JsonArray();
            if(entries.isEmpty())entries.add(concept);
            for(JsonElement item:entries) {
                JsonObject entry=object(item,"개념 본문");
                if(!text(entry,"definition").isBlank() || !text(entry,"explanation").isBlank())hasContent=true;
            }
        }
        if(!hasContent)throw invalid("제목만 있는 개념으로는 출제할 수 없어요. 개념 본문을 먼저 생성해 주세요.");
        return concepts;
    }

    static Result parse(JsonObject value,String expectedDocumentId) {
        if(value==null || expectedDocumentId==null || expectedDocumentId.isBlank()
            || !expectedDocumentId.equals(text(value,"documentId")))throw invalid("현재 PDF와 다른 문제 결과예요.");
        int requested=integer(value,"requestedCount",1,120),unfilled=integer(value,"unfilled",0,120);
        double elapsed=number(value,"elapsedSeconds");
        if(elapsed<0)throw invalid("문제 생성 시간을 확인할 수 없어요.");
        List<QuizQuestion> questions=new ArrayList<>();Set<String> ids=new HashSet<>();
        for(JsonElement raw:array(value,"questions")) {
            JsonObject item=object(raw,"문제");String id=required(item,"id");
            if(!ids.add(id))throw invalid("중복된 문제 ID가 있어요.");
            if(item.has("documentId")&&!expectedDocumentId.equals(text(item,"documentId")))
                throw invalid("다른 PDF의 문제가 포함되어 있어요.");
            QuizQuestion.Type type=type(required(item,"type"));
            List<QuizQuestion.Option> options=new ArrayList<>();Set<String> optionIds=new HashSet<>();
            for(JsonElement rawOption:array(item,"options")) {
                JsonObject option=object(rawOption,"선지");String optionId=required(option,"id");
                if(!Set.of("A","B","C","D").contains(optionId)||!optionIds.add(optionId))throw invalid("선지 ID가 올바르지 않아요.");
                options.add(new QuizQuestion.Option(optionId,required(option,"text"),required(option,"explanation"),text(option,"optionId")));
            }
            List<String> points=strings(item,"keyPoints");
            if(type!=QuizQuestion.Type.ESSAY&&!points.isEmpty())throw invalid("핵심 요소는 서술형에만 표시할 수 있어요.");

            List<QuizQuestion.Evidence> evidence=new ArrayList<>();
            for(JsonElement rawEvidence:array(item,"evidence")) {
                JsonObject source=object(rawEvidence,"근거");
                String sourceKind=text(source,"sourceKind");if(sourceKind.isBlank())sourceKind="unknown";
                evidence.add(new QuizQuestion.Evidence(required(source,"sourceId"),integer(source,"page",0,Integer.MAX_VALUE),
                    required(source,"quote"),sourceKind,source.has("originalSourceIds")?strings(source,"originalSourceIds"):List.of(),bool(source,"standardKnowledgeUsed")));
            }

            List<String> conceptIds=new ArrayList<>();
            // Optional navigation metadata must never invalidate a legacy question.
            if(item.has("conceptIds")&&item.get("conceptIds").isJsonArray())
                for(JsonElement conceptId:item.getAsJsonArray("conceptIds"))
                    if(conceptId.isJsonPrimitive()&&conceptId.getAsJsonPrimitive().isString()) {
                        String key=conceptId.getAsString().strip();
                        if(key.matches("c[1-9][0-9]*")&&!conceptIds.contains(key))conceptIds.add(key);
                    }
            questions.add(new QuizQuestion(id,expectedDocumentId,type,text(item,"concept"),required(item,"stem"),options,
                required(item,"answer"),required(item,"explanation"),points,evidence,false,conceptIds,item.has("warnings")?strings(item,"warnings"):List.of(),text(item,"answerContractVersion"),text(item,"profile")));
        }
        if(Math.max(0,requested-questions.size())!=unfilled)throw invalid("요청한 문제 수와 생성 결과가 맞지 않아요.");
        Double usd=null;boolean unknown=false;
        if(value.has("runUsage")&&!value.get("runUsage").isJsonNull()) {
            JsonObject usage=object(value.get("runUsage"),"비용");
            int unknownCount=usage.has("unknownUsageRequests")?integer(usage,"unknownUsageRequests",0,Integer.MAX_VALUE):0;
            unknown=unknownCount>0;
            if(usage.has("usageBasedUsd")&&!usage.get("usageBasedUsd").isJsonNull()) {
                double measured=number(usage,"usageBasedUsd");
                if(measured<0)throw invalid("문제 생성 비용을 확인할 수 없어요.");
                if(!unknown)usd=measured;
            }
        }
        List<String> notes=new ArrayList<>();
        if(unfilled>0)notes.add("요청 "+requested+"문제 중 "+questions.size()+"문제 생성");
        if(bool(value,"cancelled"))notes.add("출제를 취소했어요. 완료된 문제는 보관했어요.");
        else if(bool(value,"creditStopped"))notes.add("크레딧이 부족해서 문제집 생성을 중단했어요.");
        else if(bool(value,"budgetStopped"))notes.add("이번 출제의 사용 한도에 도달해 중단했어요.");
        else if(unfilled>0) {
            String notice=text(value,"completionStopReason").strip();
            if(notice.isBlank()&&value.has("errors")&&value.get("errors").isJsonArray())
                for(JsonElement entry:value.getAsJsonArray("errors"))
                    if(entry.isJsonObject()&&!text(entry.getAsJsonObject(),"message").isBlank()) {
                        notice=text(entry.getAsJsonObject(),"message").strip();break;
                    }
            if(notice.isBlank()) {
                String reason=text(value,"reason").strip();
                // Older saved results can contain the model's bookkeeping
                // commentary. Keep concise useful causes, not internal plans.
                boolean internal=reason.contains("assignment")||reason.contains("이번 배정")
                    ||reason.contains("배분 수량")||reason.contains("응답 수량");
                notice=!reason.isBlank()&&reason.length()<=100&&!internal?reason
                    :"생성 응답이 요청한 문항 수를 채우지 못했어요.";
            }
            notes.add(notice.length()>160?notice.substring(0,159)+"…":notice);
        }
        if(unknown)notes.add("일부 요청의 사용 크레딧을 확인하고 있어요.");
        return new Result(questions,elapsed,usd,requested,String.join(" · ",notes));
    }

    private static String theme(QuizPanel.Theme theme) {
        return switch(Objects.requireNonNull(theme)) {
            case CONCEPT -> "concept_completion";case UNDERSTANDING -> "understanding";
            case PRACTICE -> "practice_set";case RECALL -> "recall";
        };
    }
    private static String type(QuizQuestion.Type type) {
        return switch(type) {case OX->"ox";case MCQ->"mcq";case SHORT_ANSWER->"word";case ESSAY->"essay";};
    }
    private static QuizQuestion.Type type(String type) {
        return switch(type) {
            case "ox"->QuizQuestion.Type.OX;case "mcq"->QuizQuestion.Type.MCQ;
            case "word"->QuizQuestion.Type.SHORT_ANSWER;case "essay"->QuizQuestion.Type.ESSAY;
            default->throw invalid("알 수 없는 문제 형식이에요.");
        };
    }
    private static JsonObject object(JsonElement value,String name) {
        if(value==null||!value.isJsonObject())throw invalid(name+" 데이터가 올바르지 않아요.");return value.getAsJsonObject();
    }
    private static JsonArray array(JsonObject value,String key) {
        if(!value.has(key)||!value.get(key).isJsonArray())throw invalid(key+" 목록을 확인할 수 없어요.");return value.getAsJsonArray(key);
    }
    private static List<String> strings(JsonObject value,String key) {
        List<String> out=new ArrayList<>();
        for(JsonElement item:array(value,key)) {
            if(!item.isJsonPrimitive()||!item.getAsJsonPrimitive().isString()||item.getAsString().isBlank())throw invalid(key+" 항목이 올바르지 않아요.");
            out.add(item.getAsString());
        }
        return List.copyOf(out);
    }
    private static String text(JsonObject value,String key) {
        JsonElement item=value.get(key);
        return item!=null&&item.isJsonPrimitive()&&item.getAsJsonPrimitive().isString()?item.getAsString():"";
    }
    private static String required(JsonObject value,String key) {
        String text=text(value,key);if(text.isBlank())throw invalid(key+" 내용이 없어요.");return text;
    }
    private static boolean bool(JsonObject value,String key) {
        JsonElement item=value.get(key);return item!=null&&item.isJsonPrimitive()&&item.getAsJsonPrimitive().isBoolean()&&item.getAsBoolean();
    }
    private static double number(JsonObject value,String key) {
        JsonElement item=value.get(key);
        if(item==null||!item.isJsonPrimitive()||!item.getAsJsonPrimitive().isNumber())throw invalid(key+" 값이 올바르지 않아요.");
        double number=item.getAsDouble();if(!Double.isFinite(number))throw invalid(key+" 값이 올바르지 않아요.");return number;
    }
    private static int integer(JsonObject value,String key,int minimum,int maximum) {
        number(value,key);
        try {int result=value.get(key).getAsBigDecimal().intValueExact();if(result<minimum||result>maximum)throw invalid(key+" 범위를 확인해 주세요.");return result;}
        catch(ArithmeticException error){throw invalid(key+" 값은 정수여야 해요.");}
    }
    private static IllegalArgumentException invalid(String message){return new IllegalArgumentException(message);}
}

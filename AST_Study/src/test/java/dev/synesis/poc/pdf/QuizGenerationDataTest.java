package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Offline wire-boundary checks; no PDF, UI window or paid request is opened. */
public final class QuizGenerationDataTest {
    private static final String DOC="quiz-generation-fixture";

    public static void main(String[] args) {
        requestUsesWholeOutlineAndOneSharedConfiguration();
        resultRetainsQuestionAndSourceIdentity();
        separatedAnswerContractRemainsCompatible();
        costsAndPartialResults();
        duplicateStemsAndSurplusRemainPlayable();
        malformedResultsAreRejected();
        System.out.println("QuizGenerationDataTest passed: full concept outline, shared settings, immutable snapshots, question contracts, source provenance, partial counts and honest costs. No paid calls.");
    }

    private static void requestUsesWholeOutlineAndOneSharedConfiguration() {
        JsonObject study=study();
        require(QuizGenerationData.ready(study),"completed concepts enable the same request validator");
        require(!QuizGenerationData.ready(null),"missing concepts disable generation");
        QuizPanel.Configuration common=new QuizPanel.Configuration(2,5,"중상",EnumSet.allOf(QuizQuestion.Type.class),"조건 비교");
        Map<QuizPanel.Theme,String> themes=Map.of(QuizPanel.Theme.CONCEPT,"concept_completion",QuizPanel.Theme.UNDERSTANDING,"understanding",
            QuizPanel.Theme.PRACTICE,"practice_set",QuizPanel.Theme.RECALL,"recall");
        for(var theme:themes.entrySet()) {
            JsonObject request=QuizGenerationData.request(new QuizPanel.GenerationRequest(theme.getKey(),common,8),study,"new-concept-v99",DOC);
            JsonObject quiz=request.getAsJsonObject("quiz");
            equal(quiz.get("theme").getAsString(),theme.getValue(),"theme mapping");
            equal(quiz.get("totalCount").getAsInt(),8,"total question count");
            equal(quiz.get("difficulty").getAsString(),"중상","shared difficulty");
            equal(quiz.get("instructions").getAsString(),"조건 비교","additional instruction");
            equal(quiz.getAsJsonArray("allowedTypes").toString(),"[\"ox\",\"mcq\",\"word\",\"essay\"]","all type mapping");
            equal(request.get("startPage").getAsInt(),2,"range start");equal(request.get("endPage").getAsInt(),5,"range end");
            equal(request.getAsJsonObject("studyContent").getAsJsonArray("concepts").size(),2,"whole concept list remains available for outline");
            JsonArray groups=request.getAsJsonArray("studyGroups");equal(groups.size(),2,"same groups as concept display");
            equal(groups.get(0).getAsJsonObject().get("title").getAsString(),"첫 단원","first heading");
            equal(groups.get(1).getAsJsonObject().getAsJsonArray("conceptIndexes").get(0).getAsInt(),1,"exact concept card membership");
        }
        JsonObject request=QuizGenerationData.request(new QuizPanel.GenerationRequest(QuizPanel.Theme.CONCEPT,common,8),study,"new-concept-v99",DOC);
        study.getAsJsonArray("concepts").get(0).getAsJsonObject().addProperty("name","나중 수정");
        equal(request.getAsJsonObject("studyContent").getAsJsonArray("concepts").get(0).getAsJsonObject().get("name").getAsString(),"개념 A","request snapshot is independent");
        JsonObject legacy=study();legacy.remove("hierarchy");
        JsonObject fallback=QuizGenerationData.request(new QuizPanel.GenerationRequest(QuizPanel.Theme.RECALL,common,2),legacy,"page-v1",DOC);
        equal(fallback.getAsJsonArray("studyGroups").get(0).getAsJsonObject().getAsJsonArray("conceptIndexes").size(),2,"hierarchy-free saved concepts remain usable");
        JsonObject wrong=study();wrong.addProperty("documentId","another");fail(()->request(wrong),"foreign study");
        JsonObject partial=study();partial.addProperty("kind","partial");fail(()->request(partial),"partial study");
        require(!QuizGenerationData.ready(partial),"partial study must keep the button disabled");
        JsonObject incomplete=study();incomplete.addProperty("processingComplete",false);fail(()->request(incomplete),"incomplete study");
        JsonObject empty=study();empty.add("concepts",new JsonArray());fail(()->request(empty),"empty concepts");
        JsonObject titles=study();for(JsonElement c:titles.getAsJsonArray("concepts"))c.getAsJsonObject().add("entries",new JsonArray());
        fail(()->request(titles),"titles alone must not authorize a paid call");
        require(!QuizGenerationData.ready(titles),"title-only concepts keep the button disabled");
        QuizPanel.Configuration tooLong=new QuizPanel.Configuration(1,10,"중",Set.of(QuizQuestion.Type.OX),"가".repeat(2001));
        fail(()->QuizGenerationData.request(new QuizPanel.GenerationRequest(QuizPanel.Theme.CONCEPT,tooLong,1),study(),"new-concept-v99",DOC),"oversized extra request");
    }

    private static void resultRetainsQuestionAndSourceIdentity() {
        QuizGenerationData.Result parsed=QuizGenerationData.parse(result(),DOC);
        equal(parsed.questions().size(),4,"all question formats");
        equal(parsed.elapsedSeconds(),12.5,"elapsed time");equal(parsed.totalUsd(),0.012,"complete run costs");
        require(parsed.questions().stream().noneMatch(QuizQuestion::preview),"real results cannot masquerade as examples");
        require(parsed.questions().get(2).selfComparison()&&parsed.questions().get(3).selfComparison(),"word and essay retain comparison mode");
        require(!parsed.questions().get(0).selfComparison()&&!parsed.questions().get(1).selfComparison(),"OX and MCQ remain objective");
        QuizQuestion.Evidence evidence=parsed.questions().get(0).evidence().get(0);
        equal(evidence.sourceKind(),"saved_concept","saved prose must not become a PDF quote");
        equal(evidence.originalSourceIds(),List.of("region-1"),"original source identity");
        require(evidence.standardKnowledgeUsed(),"supplemental background provenance");
        equal(evidence.page(),2,"source page");
        equal(parsed.questions().get(1).evidence().get(0).sourceKind(),"native","original PDF source kind remains original");
        require(!parsed.questions().get(1).evidence().get(0).standardKnowledgeUsed(),"original PDF quote does not inherit supplemental status");
        equal(parsed.questions().get(1).options().get(2).explanation(),"C는 조건을 놓쳤다.","distractor explanation survives");
        try {parsed.questions().clear();throw new AssertionError("result list was mutable");}catch(UnsupportedOperationException expected) {}
    }

    private static void separatedAnswerContractRemainsCompatible() {
        JsonObject value=result();
        JsonObject mcq=value.getAsJsonArray("questions").get(1).getAsJsonObject();
        for(JsonElement entry:mcq.getAsJsonArray("options")) {
            JsonObject option=entry.getAsJsonObject();
            option.addProperty("optionId","O0"+(option.get("id").getAsString().charAt(0)-'A'+1));
        }
        JsonObject essay=value.getAsJsonArray("questions").get(3).getAsJsonObject();
        essay.addProperty("answerContractVersion","study-answer-v1");
        essay.addProperty("exampleAnswer",essay.get("answer").getAsString());
        JsonArray points=new JsonArray();points.add("공통 판단");points.add("조건: 방법 B → 요구: B의 전제");essay.add("keyPoints",points);
        String original=value.toString();
        var parsed=QuizGenerationData.parse(value,DOC);
        equal(parsed.questions().get(1).options().get(2).optionId(),"O03","source identity survives display parsing");
        equal(parsed.questions().get(3).answerContractVersion(),"study-answer-v1","example label version");
        equal(parsed.questions().get(3).keyPoints().get(1),"조건: 방법 B → 요구: B의 전제","conditional requirement not flattened");
        equal(value.toString(),original,"saved original not mutated");
    }

    private static void duplicateStemsAndSurplusRemainPlayable() {
        JsonObject surplus=result();surplus.addProperty("requestedCount",2);
        JsonArray questions=surplus.getAsJsonArray("questions");
        questions.get(1).getAsJsonObject().addProperty("stem",questions.get(0).getAsJsonObject().get("stem").getAsString());
        QuizGenerationData.Result parsed=QuizGenerationData.parse(surplus,DOC);
        equal(parsed.questions().size(),4,"generated surplus must not be hidden");
        equal(parsed.requestedCount(),2,"requested count must not be rewritten as generated count");
        equal(QuizWorkbook.fromResult(surplus).questions().size(),4,"surplus workbook remains openable");
        equal(parsed.questions().get(0).stem(),parsed.questions().get(1).stem(),"duplicate stems are retained with distinct IDs");
    }

    private static void costsAndPartialResults() {
        JsonObject partial=result();partial.getAsJsonArray("questions").remove(3);partial.addProperty("unfilled",1);partial.addProperty("reason","근거 부족");
        QuizGenerationData.Result parsed=QuizGenerationData.parse(partial,DOC);
        equal(parsed.questions().size(),3,"completed questions preserved");
        require(parsed.note().contains("4문제 중 3문제")&&parsed.note().contains("근거 부족"),"partial result is explicit");
        partial.getAsJsonObject("runUsage").addProperty("unknownUsageRequests",1);
        parsed=QuizGenerationData.parse(partial,DOC);
        require(parsed.totalUsd()==null&&parsed.note().contains("사용 크레딧을 확인"),"uncertain requests cannot yield a final cost or unit price");
        JsonObject missing=result();missing.remove("runUsage");require(QuizGenerationData.parse(missing,DOC).totalUsd()==null,"missing costs are not zero");
        JsonObject zero=result();zero.getAsJsonObject("runUsage").addProperty("usageBasedUsd",0);
        equal(QuizGenerationData.parse(zero,DOC).totalUsd(),0.0,"measured zero stays zero");
        JsonObject pageUnknown=result();pageUnknown.getAsJsonArray("questions").get(0).getAsJsonObject().getAsJsonArray("evidence").get(0).getAsJsonObject().addProperty("page",0);
        equal(QuizGenerationData.parse(pageUnknown,DOC).questions().get(0).evidence().get(0).page(),0,"legacy unknown page does not invent a page number");
        JsonObject noQuestions=result();noQuestions.add("questions",new JsonArray());noQuestions.addProperty("unfilled",4);
        equal(QuizGenerationData.parse(noQuestions,DOC).questions().size(),0,"zero completed questions is a valid partial outcome");
        JsonObject cancelled=partial.deepCopy();cancelled.addProperty("cancelled",true);
        cancelled.addProperty("reason","이번 assignment 배정은 객관식 1개이다. ".repeat(30));
        String cancelledNote=QuizGenerationData.parse(cancelled,DOC).note();
        require(cancelledNote.contains("취소")&&!cancelledNote.contains("assignment")&&cancelledNote.length()<180,"cancelled runs show a concise cause, not model bookkeeping");
        JsonObject budget=partial.deepCopy();budget.addProperty("budgetStopped",true);
        require(QuizGenerationData.parse(budget,DOC).note().contains("한도"),"provider budget stop is distinct from insufficient evidence");
        JsonObject creditStop=budget.deepCopy();creditStop.addProperty("creditStopped",true);
        require(QuizGenerationData.parse(creditStop,DOC).note().contains("크레딧이 부족"),"credit stop must explain the depleted balance");
        JsonObject complete=result();complete.addProperty("reason","배분 수량 12개를 10개로 보정했어요. 이번 배정은 1문항이다.");
        equal(QuizGenerationData.parse(complete,DOC).note(),"","complete runs do not display internal allocation commentary");
        JsonObject error=partial.deepCopy();JsonArray errors=new JsonArray();JsonObject cause=new JsonObject();
        cause.addProperty("message","출제 배분의 개념 범위가 올바르지 않아요.");errors.add(cause);error.add("errors",errors);
        require(QuizGenerationData.parse(error,DOC).note().contains("개념 범위"),"actionable validation errors remain visible");
        error.addProperty("completionStopReason","일부 응답·비용이 확인되지 않아 추가 호출을 멈췄어요.");
        String completionNote=QuizGenerationData.parse(error,DOC).note();
        require(completionNote.contains("추가 호출을 멈췄어요")&&!completionNote.contains("개념 범위"),
            "current completion stop reason takes precedence over a recovered generation error");
    }

    private static void malformedResultsAreRejected() {
        JsonObject wrong=result();wrong.addProperty("documentId","other");fail(()->QuizGenerationData.parse(wrong,DOC),"foreign result");
        JsonObject count=result();count.addProperty("unfilled",1);fail(()->QuizGenerationData.parse(count,DOC),"count mismatch");
        JsonObject decimal=result();decimal.addProperty("requestedCount",4.5);fail(()->QuizGenerationData.parse(decimal,DOC),"fractional count");
        JsonObject duplicate=result();duplicate.getAsJsonArray("questions").get(1).getAsJsonObject().addProperty("id","q1");
        fail(()->QuizGenerationData.parse(duplicate,DOC),"duplicate id");
        JsonObject unknown=result();unknown.getAsJsonArray("questions").get(0).getAsJsonObject().addProperty("type","unknown");
        fail(()->QuizGenerationData.parse(unknown,DOC),"unknown type");
        JsonObject ungrounded=result();ungrounded.getAsJsonArray("questions").get(0).getAsJsonObject().add("evidence",new JsonArray());
        equal(QuizGenerationData.parse(ungrounded,DOC).questions().size(),4,"ungrounded question remains visible");
        JsonArray notices=new JsonArray();notices.add("출처를 확인해 주세요.");
        ungrounded.getAsJsonArray("questions").get(0).getAsJsonObject().add("warnings",notices);
        equal(QuizGenerationData.parse(ungrounded,DOC).questions().get(0).warnings(),List.of("출처를 확인해 주세요."),"warning survives parser");
        JsonObject options=result();options.getAsJsonArray("questions").get(1).getAsJsonObject().getAsJsonArray("options").remove(3);
        fail(()->QuizGenerationData.parse(options,DOC),"missing MCQ option");
        JsonObject badAnswer=result();badAnswer.getAsJsonArray("questions").get(1).getAsJsonObject().addProperty("answer","E");
        fail(()->QuizGenerationData.parse(badAnswer,DOC),"invalid answer identity");
        JsonObject negative=result();negative.getAsJsonObject("runUsage").addProperty("usageBasedUsd",-.01);
        fail(()->QuizGenerationData.parse(negative,DOC),"negative cost");
        JsonObject infinite=result();infinite.addProperty("elapsedSeconds",Double.POSITIVE_INFINITY);
        fail(()->QuizGenerationData.parse(infinite,DOC),"infinite time");
    }

    private static JsonObject request(JsonObject study) {
        return QuizGenerationData.request(new QuizPanel.GenerationRequest(QuizPanel.Theme.CONCEPT,QuizPanel.Configuration.defaults(10),5),study,"new-concept-v99",DOC);
    }
    private static JsonObject study() {
        return JsonParser.parseString("""
            {"kind":"ai_generated","processingComplete":true,"documentId":"quiz-generation-fixture","concepts":[
              {"name":"개념 A","entries":[{"definition":"A 정의","explanation":"A 설명","evidence":[{"sourceId":"s1"}]}]},
              {"name":"개념 B","entries":[{"definition":"B 정의","explanation":"B 설명","evidence":[{"sourceId":"s2"}]}]}],
             "hierarchy":{"nodes":[{"id":"h1","parentId":"","title":"첫 단원","sourceHeading":true},
                                       {"id":"h2","parentId":"","title":"다음 단원","sourceHeading":true}]},
             "sections":[{"parts":[{"nodeId":"h1","title":"개념 A","evidence":[{"sourceId":"s1"}]},
                                     {"nodeId":"h2","title":"개념 B","evidence":[{"sourceId":"s2"}]}]}]}
            """).getAsJsonObject();
    }
    private static JsonObject result() {
        JsonObject result=new JsonObject();result.addProperty("documentId",DOC);result.addProperty("requestedCount",4);
        result.addProperty("unfilled",0);result.addProperty("reason","");result.addProperty("elapsedSeconds",12.5);
        JsonObject usage=new JsonObject();usage.addProperty("usageBasedUsd",.012);usage.addProperty("unknownUsageRequests",0);result.add("runUsage",usage);
        JsonArray questions=new JsonArray();String[] types={"ox","mcq","word","essay"};
        for(int i=0;i<types.length;i++) {
            JsonObject question=new JsonObject();question.addProperty("id","q"+(i+1));question.addProperty("type",types[i]);
            question.addProperty("concept","개념 A");question.addProperty("stem","조건에 맞게 판단하시오 "+i);
            question.addProperty("answer",i==0?"O":i==1?"A":"모범답안");question.addProperty("explanation","자료의 조건에 따른 해설이다.");
            JsonArray options=new JsonArray();
            if(i==1)for(String id:List.of("A","B","C","D")) {
                JsonObject option=new JsonObject();option.addProperty("id",id);option.addProperty("text",id+"의 조건");
                option.addProperty("explanation",id+"는 조건을 놓쳤다.");options.add(option);
            }
            question.add("options",options);JsonArray points=new JsonArray();if(i==3)points.add("핵심 조건");question.add("keyPoints",points);
            JsonObject evidence=new JsonObject();evidence.addProperty("sourceId","concept-1");evidence.addProperty("page",2);
            evidence.addProperty("quote","저장된 개념 정의");evidence.addProperty("sourceKind","saved_concept");
            evidence.addProperty("standardKnowledgeUsed",true);JsonArray sourceIds=new JsonArray();sourceIds.add("region-1");evidence.add("originalSourceIds",sourceIds);
            if(i==1) {evidence.addProperty("sourceKind","native");evidence.addProperty("standardKnowledgeUsed",false);}
            JsonArray citations=new JsonArray();citations.add(evidence);question.add("evidence",citations);questions.add(question);
        }
        result.add("questions",questions);return result;
    }
    private static void fail(Runnable action,String message) {
        try {action.run();throw new AssertionError("Accepted "+message);}catch(IllegalArgumentException expected) {}
    }
    private static void equal(Object actual,Object expected,String message){if(!Objects.equals(actual,expected))throw new AssertionError(message+": "+actual+" != "+expected);}
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}

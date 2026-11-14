package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;

/** Host boundary replay for independent semantic intent decisions; no paid model calls. */
public final class AssistantRecoveryIntentTest {
    static JsonObject context(AssistantLocal local){return ok(call(local,"context.get",new JsonObject(),""));}
    static JsonObject classify(AssistantLocal local,String question,String intent,boolean clear,String evidence){
        JsonObject args=new JsonObject();args.add("id",context(local).getAsJsonObject("undo").get("id"));
        args.addProperty("question",question);args.addProperty("intent",intent);args.addProperty("clear",clear);args.addProperty("evidence",evidence);
        return call(local,"internal.recoveryIntent",args,"");
    }
    static void seed(AssistantLocal local,String turn){
        String question="내일 시험 일정 오후 3시부터 5시까지 추가해줘";local.begin("s",turn,question);authorize(local,question,"planner","create");long rev=query(local).get("revision").getAsLong();
        ok(call(local,"planner.apply",patch(rev,array(change("event","create",null,json("{\"title\":\"시험\",\"start\":\"2026-10-26T15:00\",\"end\":\"2026-10-26T17:00\"}")))),question));local.finish("등록했어요.");
    }
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("assistant-recovery-");PlannerStore store=new PlannerStore(dir.resolve("planner.json"));
        AssistantLocal local=new AssistantLocal(store,dir.resolve("memory.json"),JsonObject::new);seed(local,"seed");
        String question="야 잘못했잖아. 다시 바꿔서 다시해";local.begin("s","redo",question);
        check(context(local).get("recoveryInterpretationEligible").getAsBoolean(),"same conversation actual commit offers interpretation, no keyword required");
        ok(classify(local,question,"redo",true,"다시 바꿔서 다시해"));JsonObject c=context(local);
        check(c.get("mutationScope").getAsString().equals("undo,planner"),"bounded previous domain granted after independent intent");
        String grant=c.get("authorizationQuote").getAsString();JsonObject undo=new JsonObject();undo.add("id",c.getAsJsonObject("undo").get("id"));
        ok(call(local,"actions.undo",undo,grant));check(store.load().events().isEmpty(),"restored before retry");
        long rev=query(local).get("revision").getAsLong();ok(call(local,"planner.apply",patch(rev,array(change("event","create",null,json("{\"title\":\"시험 재작업\",\"start\":\"2026-10-26T15:00\",\"end\":\"2026-10-26T17:00\"}")))),grant));
        check(store.load().events().size()==1,"one corrected replacement, no duplicate");
        // A short correction updates only the actual most recent row, not every queried row.
        question="아니 4시라니까";local.begin("s","revise",question);ok(classify(local,question,"revise",true,question));c=context(local);grant=c.get("authorizationQuote").getAsString();rev=query(local).get("revision").getAsLong();
        String id=store.load().events().get(0).id();
        denied(call(local,"planner.apply",patch(rev,array(change("task","create",null,json("{\"title\":\"무관한 추가\",\"date\":\"2026-10-26\"}")))),grant));
        ok(call(local,"planner.apply",patch(rev,array(change("event","update",id,json("{\"start\":\"2026-10-26T16:00\"}")))),grant));
        check(store.load().events().get(0).start().getHour()==16&&store.load().events().get(0).end().getHour()==17,"targeted correction preserves unchanged end");
        question="되돌리지 말고 그대로 둬";local.begin("s","negative",question);ok(classify(local,question,"none",true,""));check(!context(local).get("mutationScope").getAsString().contains("undo"),"negation does not restore");
        question="“다시 바꿔서 다시해”를 번역해줘";local.begin("s","quoted",question);denied(classify(local,question,"redo",true,"다시 바꿔서 다시해"));
        local.begin("different","other-session","다시해");check(!context(local).get("recoveryInterpretationEligible").getAsBoolean(),"no cross-conversation inherited authority");denied(classify(local,"다시해","redo",true,"다시해"));
        local.begin("s","ambiguous","다시 다르게 해줘");ok(classify(local,"다시 다르게 해줘","redo",false,"다시 다르게 해줘"));check(context(local).get("mutationScope").getAsString().isEmpty()&&context(local).get("recoveryDecision").getAsString().equals("clarify"),"missing condition grants no writes");
        System.out.println("AssistantRecoveryIntentTest OK");
    }
}

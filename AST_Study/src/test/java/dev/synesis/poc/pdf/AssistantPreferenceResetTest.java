package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import dev.synesis.poc.planner.PlannerStore;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;

/** Actual screenshot wording against disposable storage; never changes real preferences. */
public final class AssistantPreferenceResetTest {
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("assistant-preference-reset-");
        AssistantLocal local=new AssistantLocal(new PlannerStore(dir.resolve("planner.json")),dir.resolve("memory.json"),JsonObject::new);
        String seed="앞으로 나를 민준이라고 불러. 반말로 해줘. 메모리에 저장해줘";
        for(String request:new String[]{"너 이름 데이먼으로 지정한다는건 취소할겡","너 이름 데이먼이라고 안 부르고 그냥 기본값으로 되돌려줘.","저장한 별명 설정 해제해줘","말투를 기본값으로 초기화해줘"}){
            long rev=local.preferencesSnapshot().get("revision").getAsLong();local.begin("s","seed-"+request,seed);authorize(local,seed,"memory");
            JsonObject original=json("{\"set\":{\"preferredName\":\"민준\",\"tone\":\"casual\",\"communicationStyle\":\"친구처럼 편하게 말하기\",\"notes\":[\"어시스턴트를 데이먼이라고 부르기\",\"코드 예시는 C++ 선호\"]},\"remove\":[]}");original.addProperty("expectedRevision",rev);
            ok(call(local,"memory.update",original,seed));
            local.begin("s","reset-"+request,request);authorize(local,request,"memory",true,false,"");JsonObject context=ok(call(local,"context.get",new JsonObject(),""));
            check(context.get("mutationScope").getAsString().equals("memory"),"reset is a memory write, not undo: "+request);
            check(context.get("personalizationResetThisTurn").getAsBoolean(),"reset context");
            check(!context.get("recoveryInterpretationEligible").getAsBoolean(),"do not misclassify personal reset as transaction rollback");
            JsonObject reset=json("{\"set\":{\"notes\":[\"코드 예시는 C++ 선호\"]},\"remove\":[]}");reset.addProperty("expectedRevision",rev+1);
            ok(call(local,"memory.update",reset,request));JsonObject values=local.preferencesSnapshot().getAsJsonObject("values");
            check(values.getAsJsonArray("notes").size()==1&&values.get("tone").getAsString().equals("casual")&&values.get("preferredName").getAsString().equals("민준")&&values.get("communicationStyle").getAsString().contains("친구"),"selective removal preserves user name and unrelated style");
        }
        for(String request:new String[]{"'너 이름 데이먼으로 지정한다는건 취소할게' 이 문장 번역해줘","호칭 설정 삭제하지 마","기억 초기화 방법 설명해줘"}){
            local.begin("s","negative-"+request,request);check(ok(call(local,"context.get",new JsonObject(),"")).get("mutationScope").getAsString().isEmpty(),"explanation/negation not a reset grant");
        }
        System.out.println("AssistantPreferenceResetTest OK");
    }
}

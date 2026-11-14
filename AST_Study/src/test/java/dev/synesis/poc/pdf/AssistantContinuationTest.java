package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.util.*;

/** Five-turn task discussion stays read-only until the current explicit execution request. */
public final class AssistantContinuationTest {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static JsonObject intent(String question,String kind,String reference){
        JsonObject o=new JsonObject();o.addProperty("question",question);o.addProperty("decision",kind);
        o.addProperty("evidence",kind.equals("none")||kind.equals("reject")?"":question);
        JsonArray scopes=new JsonArray(),ops=new JsonArray();
        if(!kind.equals("none")&&!kind.equals("reject")){scopes.add("planner");ops.add("update");}
        o.add("scopes",scopes);o.add("plannerOperations",ops);o.addProperty("referenceId",reference);
        o.addProperty("resetPersonalization",false);o.addProperty("allRecurring",false);return o;
    }
    static JsonObject pending(AssistantMutationAuthority authority){
        for(JsonElement e:authority.context())if(e.getAsJsonObject().has("pending"))return e.getAsJsonObject();
        throw new AssertionError("pending task missing");
    }
    public static void main(String[]args){
        AssistantMutationAuthority a=new AssistantMutationAuthority();String first="학지 일정 색을 다른 걸로 바꿔줘";
        a.begin("s","1",first,null);check(a.interpret(intent(first,"clarify","")).scopes().isEmpty(),"clarification granted writes");a.finish(false,"어떤 색으로 바꿀까요?");
        String id=pending(a).get("id").getAsString();
        for(String q:List.of("분홍과 슬레이트가 어떤 색이야?","학지에는 어느 쪽이 어울릴까?","슬레이트로 한다면 잘 보일지 설명해줘. 적용은 기다려")){
            a.begin("s",UUID.randomUUID().toString(),q,null);
            check(pending(a).get("id").getAsString().equals(id),"original task displaced by explanation");
            check(a.interpret(intent(q,"none",id)).scopes().isEmpty(),"explanation granted writes");
            a.finish(false,"슬레이트가 차분하고 구분하기 좋아요.");
        }
        String go="ㅇㅋ 그렇게 진행해줘.";a.begin("s","5",go,null);
        var d=a.interpret(intent(go,"approve",id));check(d.scopes().equals(Set.of("planner"))&&d.operations().equals(Set.of("update")),"final request lost original action");
        check(d.quote().contains(first)&&d.quote().contains(go),"current consent not linked to original task");a.finish(true,"색을 바꿨어요.");
        a.begin("s","6","좋아",null);boolean denied=false;try{a.interpret(intent("좋아","approve",id));}catch(IllegalArgumentException expected){denied=true;}check(denied,"completed task repeated");
        a.begin("s","7",first,null);a.interpret(intent(first,"clarify",""));a.finish(false,"색을 골라 주세요.");String abandoned=pending(a).get("id").getAsString();
        a.begin("s","8","오늘 날씨 이야기도 해보자",null);a.interpret(intent("오늘 날씨 이야기도 해보자","none",""));a.finish(false,"일반 대화예요.");
        check(pending(a).get("id").getAsString().equals(abandoned),"unrelated chat cancelled pending task");
        check(pending(a).get("confirmationQuestion").getAsString().equals("색을 골라 주세요."),"confirmation question was overwritten");
        a.begin("s","cancel","그 작업은 취소해",null);a.interpret(intent("그 작업은 취소해","reject",abandoned));a.finish(false,"취소했어요.");
        a.begin("s","9",go,null);denied=false;try{a.interpret(intent(go,"approve",abandoned));}catch(IllegalArgumentException expected){denied=true;}check(denied,"abandoned topic resumed on bare consent");
        a.begin("new-session","10",go,null);check(a.context().isEmpty(),"pending state crossed sessions");
        System.out.println("AssistantContinuationTest OK: five turns, no premature writes, pinned referent, completion, topic change, session isolation");
    }
}

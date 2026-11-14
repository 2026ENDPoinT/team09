package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.util.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;

/** Model decisions are fixture inputs; the host never classifies words in this test. */
public final class AssistantApprovalTest {
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("assistant-semantic-approval-");
        try{
            for(String text:List.of("네, 그렇게 해주세요.","그 방향으로 부탁드릴게요","응 그거면 충분하겠네 진행하자","좋아요","ㅇㅇ","등록해줘")){
                Path dir=Files.createTempDirectory(root,"flow-");PlannerStore store=new PlannerStore(dir.resolve("planner.json"));AssistantLocal local=new AssistantLocal(store,dir.resolve("memory.json"),JsonObject::new);
                String original="화요일 16시~18시 스페인어 수업 등록해줘.";
                local.begin("s","original",original);check(ok(call(local,"context.get",new JsonObject(),"")).get("mutationScope").getAsString().isEmpty(),"no keyword permission before interpretation");local.finish("확인할 내용이 있어요.");
                local.begin("s","followup",text);String grant=authorize(local,text,"planner",false,false,reference(local,original),"create");
                long revision=query(local).get("revision").getAsLong();JsonObject proposal=patch(revision,array(change("event","create",null,json("{\"title\":\"스페인어 수업\",\"start\":\"2026-10-27T16:00\",\"end\":\"2026-10-27T18:00\"}"))));
                ok(call(local,"planner.apply",proposal,grant));check(store.load().events().size()==1,"semantic approval executes: "+text);
                denied(call(local,"planner.apply",patch(store.load().revision(),array(change("event","delete",store.load().events().getFirst().id(),new JsonObject()))),grant));
                local.finish("추가했어요.");local.begin("new-session","other","좋습니다");
                check(ok(call(local,"context.get",new JsonObject(),"")).getAsJsonArray("mutationReferences").isEmpty(),"new chat has no inherited references");
            }
            PlannerStore store=new PlannerStore(root.resolve("direct.json"));AssistantLocal local=new AssistantLocal(store,root.resolve("direct-memory.json"),JsonObject::new);
            String question="화요일 16시~18시 스페인어 수업 등록해줘.";local.begin("s","direct",question);authorize(local,question,"planner","create");
            long revision=query(local).get("revision").getAsLong();ok(call(local,"planner.apply",patch(revision,array(change("event","create",null,json("{\"title\":\"스페인어 수업\",\"start\":\"2026-10-27T16:00\",\"end\":\"2026-10-27T18:00\"}")))),question));
            check(store.load().events().size()==1,"actual screenshot request saves without the word tag or schedule");
            String quoted="‘수업 등록해줘’라는 문장을 설명해줘";local.begin("s","quoted",quoted);
            JsonObject intent=decision(quoted,"request","수업 등록해줘","planner","create");denied(call(local,"internal.mutationIntent",intent,""));
            for(String decision:List.of("clarify","none","reject")){
                String q=decision.equals("clarify")?"그거 어떻게든 바꿔봐":"지금은 그대로 둘게";local.begin("s",decision,q);intent=decision(q,decision,decision.equals("clarify")?q:"","","");ok(call(local,"internal.mutationIntent",intent,""));
                check(ok(call(local,"context.get",new JsonObject(),"")).get("mutationScope").getAsString().isEmpty(),"non-actionable decision never grants: "+decision);
            }
            local.begin("s","stale","좋아요");intent=decision("좋아요","approve","좋아요","planner","create");intent.addProperty("referenceId","made-up");denied(call(local,"internal.mutationIntent",intent,""));
            JsonArray history=new JsonArray();JsonObject old=new JsonObject();old.addProperty("question",question);old.addProperty("timestampMs",System.currentTimeMillis());history.add(old);
            AssistantLocal restored=new AssistantLocal(store,root.resolve("restored-memory.json"),JsonObject::new);restored.begin("same-chat","continue","부탁할게요",history);
            check(!authorize(restored,"부탁할게요","planner",false,false,reference(restored,question),"create").isEmpty(),"real saved user request survives engine restart");
            old.addProperty("timestampMs",System.currentTimeMillis()-1_800_001);restored.begin("different-chat","expired","부탁할게요",history);
            check(ok(call(restored,"context.get",new JsonObject(),"")).getAsJsonArray("mutationReferences").isEmpty(),"expired history cannot grant approval");
            System.out.println("AssistantApprovalTest OK · direct course request, varied semantic consent, operation bounds, ambiguity, quotes, session/history isolation");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
    static JsonObject decision(String question,String kind,String evidence,String scope,String operation){
        JsonObject value=new JsonObject();value.addProperty("question",question);value.addProperty("decision",kind);value.addProperty("evidence",evidence);value.addProperty("referenceId","");value.addProperty("resetPersonalization",false);value.addProperty("allRecurring",false);
        JsonArray scopes=new JsonArray();if(!scope.isEmpty())scopes.add(scope);value.add("scopes",scopes);JsonArray ops=new JsonArray();if(!operation.isEmpty())ops.add(operation);value.add("plannerOperations",ops);return value;
    }
}

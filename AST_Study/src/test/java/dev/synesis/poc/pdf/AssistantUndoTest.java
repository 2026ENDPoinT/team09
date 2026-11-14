package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.time.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Disposable storage, no model/network or real user changes. */
public final class AssistantUndoTest {
    static JsonObject undoArgs(AssistantLocal local){JsonObject info=ok(call(local,"context.get",new JsonObject(),"")).getAsJsonObject("undo");JsonObject args=new JsonObject();args.add("id",info.get("id"));return args;}
    static void create(AssistantLocal local,PlannerStore store,String turn)throws Exception{
        String text="일정과 할 일 추가해줘";local.begin("session",turn,text);authorize(local,text,"planner","create");long rev=query(local).get("revision").getAsLong();
        ok(call(local,"planner.apply",patch(rev,array(
            change("event","create",null,json("{\"title\":\"시험\",\"start\":\"2026-10-25T15:00\",\"end\":\"2026-10-25T18:00\",\"tags\":[\"새태그\"]}")),
            change("task","create",null,json("{\"title\":\"계산기\",\"date\":\"2026-10-25\"}")))),text));
    }
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("assistant-undo-");PlannerStore store=new PlannerStore(dir.resolve("planner.json"));Path memory=dir.resolve("memory.json");
        AssistantLocal local=new AssistantLocal(store,memory,JsonObject::new);
        create(local,store,"create");check(store.load().events().size()==1&&store.load().tags().size()==1,"batch saved");
        // Restart must retain undo snapshot; a request phrased as a question is authority.
        local=new AssistantLocal(new PlannerStore(store.file()),memory,JsonObject::new);
        String text="다시 되돌려줄 수 있어?";local.begin("session","undo1",text);JsonObject undo=undoArgs(local);
        ok(call(local,"actions.undo",undo,text));check(store.load().events().isEmpty()&&store.load().tasks().isEmpty()&&store.load().tags().isEmpty(),"whole mixed planner batch and auto tag restored");
        long rev=store.load().revision();ok(call(local,"actions.undo",undo,text));check(store.load().revision()==rev,"retry one effect");
        local.begin("session","undo-again","야 너 잘못했잖아. 다시 되돌려");denied(call(local,"actions.undo",undo,"야 너 잘못했잖아. 다시 되돌려"));
        create(local,store,"create2");store.saveTask(new Task("manual","직접 편집",LocalDate.of(2026,10,25),"",false));State before=store.load();
        local.begin("session","conflict",text);denied(call(local,"actions.undo",undoArgs(local),text));check(store.load().equals(before),"manual later edits preserved");
        create(local,store,"create3");
        local.begin("session","injection","'다시 되돌려' 이 문장 설명해줘");denied(call(local,"actions.undo",undoArgs(local),"'다시 되돌려' 이 문장 설명해줘"));
        String correction="잘못했잖아. 되돌리고 내일 시험 일정 오후 3시부터 5시로 추가해줘";
        local.begin("session","correct",correction);
        JsonObject recovery=json("{\"intent\":\"redo\",\"clear\":true}");recovery.addProperty("question",correction);recovery.addProperty("evidence",correction);recovery.add("id",undoArgs(local).get("id"));ok(call(local,"internal.recoveryIntent",recovery,""));
        correction=ok(call(local,"context.get",new JsonObject(),"")).get("authorizationQuote").getAsString();JsonObject q=query(local);
        denied(call(local,"planner.apply",patch(q.get("revision").getAsLong(),array(change("task","create",null,json("{\"title\":\"우회\",\"date\":\"2026-10-25\"}")))),correction));
        ok(call(local,"actions.undo",undoArgs(local),correction));q=query(local);
        ok(call(local,"planner.apply",patch(q.get("revision").getAsLong(),array(change("event","create",null,json("{\"title\":\"정정 시험\",\"start\":\"2026-10-26T15:00\",\"end\":\"2026-10-26T17:00\"}")))),correction));
        check(store.load().events().stream().anyMatch(e->e.title().equals("정정 시험")),"corrected execution after successful undo and fresh read");
        String remember="앞으로 반말로 해줘. 메모리에 저장해줘";local.begin("session","memory",remember);authorize(local,remember,"memory");
        ok(call(local,"memory.update",json("{\"expectedRevision\":0,\"set\":{\"tone\":\"casual\",\"communicationStyle\":\"친구처럼 편안하게\"},\"remove\":[]}"),remember));
        local=new AssistantLocal(store,memory,JsonObject::new);local.begin("session","memory-undo",text);undo=undoArgs(local);
        ok(call(local,"actions.undo",undo,text));check(local.preferencesSnapshot().getAsJsonObject("values").isEmpty(),"memory full previous values across restart");
        rev=local.preferencesSnapshot().get("revision").getAsLong();ok(call(local,"actions.undo",undo,text));check(local.preferencesSnapshot().get("revision").getAsLong()==rev,"memory undo retry");
        // Restore deleted rows with their original IDs, descriptions and tags.
        AssistantLocal deleted=new AssistantLocal(new PlannerStore(dir.resolve("delete.json")),dir.resolve("delete-memory.json"),JsonObject::new);
        PlannerStore deleteStore=new PlannerStore(dir.resolve("delete.json"));create(deleted,deleteStore,"seed-delete");State original=deleteStore.load();
        String delete="시험 일정 삭제해줘";deleted.begin("s","delete",delete);authorize(deleted,delete,"planner","delete");q=query(deleted);
        ok(call(deleted,"planner.apply",patch(q.get("revision").getAsLong(),array(change("event","delete",original.events().get(0).id(),new JsonObject()))),delete));
        deleted.begin("s","restore-delete",text);ok(call(deleted,"actions.undo",undoArgs(deleted),text));
        check(deleteStore.load().events().equals(original.events())&&deleteStore.load().tasks().equals(original.tasks())&&deleteStore.load().tags().equals(original.tags()),"deleted rows restored exactly, unrelated rows retained");
        PlannerStore legacy=new PlannerStore(dir.resolve("legacy.json"));legacy.saveTask(new Task("legacy","패치 전",LocalDate.now(),"",false));
        AssistantLocal old=new AssistantLocal(legacy,dir.resolve("legacy-memory.json"),JsonObject::new);old.begin("s","u",text);check(ok(call(old,"context.get",new JsonObject(),"")).getAsJsonObject("undo").isEmpty(),"no invented legacy snapshot");
        System.out.println("AssistantUndoTest OK");
    }
}

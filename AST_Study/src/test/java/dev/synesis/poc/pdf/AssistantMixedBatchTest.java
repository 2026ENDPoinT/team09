package dev.synesis.poc.pdf;
import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.pdf.AssistantLocalTest.*;
public final class AssistantMixedBatchTest {
    public static void main(String[] args)throws Exception{
        Path dir=Files.createTempDirectory("assistant-mixed-");PlannerStore store=new PlannerStore(dir.resolve("planner.json"));
        store.saveEvent(new Event("c","C","설명 보존",LocalDateTime.parse("2026-10-25T15:00"),LocalDateTime.parse("2026-10-25T16:00"),false,EventColor.BLUE,List.of(),false,Repeat.NONE,-1));
        AssistantLocal local=new AssistantLocal(store,dir.resolve("preferences.json"),JsonObject::new);
        String quote="A 일정 생성, B 일정 추가, C 일정 수정하고 TODO에 D 추가해줘. 태그는 중요!@!!";
        local.begin("s","mixed",quote);authorize(local,quote,"planner","create","update");
        long revision=ok(call(local,"planner.query",json("{\"from\":\"2026-10-25\",\"to\":\"2026-10-26\"}"),"")).get("revision").getAsLong();
        JsonObject fields=json("{\"title\":\"A\",\"start\":\"2026-10-25T13:00\",\"end\":\"2026-10-25T14:00\",\"tags\":[\"중요!@!!\"]}");JsonObject b=fields.deepCopy();b.addProperty("title","B");
        JsonObject request=patch(revision,array(change("event","create",null,fields),change("event","create",null,b),change("event","update","c",json("{\"title\":\"C 수정\",\"tags\":[\"중요!@!!\"]}")),change("task","create",null,json("{\"title\":\"D\",\"date\":\"2026-10-25\",\"detail\":\"할 일\"}"))));
        ok(call(local,"planner.apply",request,quote));State state=store.load();
        check(state.events().size()==3&&state.tasks().size()==1,"mixed create/update/todo committed together");
        check(state.tags().size()==1&&state.tags().get(0).name().equals("중요!@!!"),"missing special-character tag created exactly once");
        check(state.events().stream().allMatch(e->e.tagIds().equals(List.of(state.tags().get(0).id()))),"same tag reused for every event");
        check(state.events().stream().filter(e->e.id().equals("c")).findFirst().orElseThrow().description().equals("설명 보존"),"unrequested fields preserved");
        ok(call(local,"planner.apply",request,quote));check(store.load().equals(state),"mixed retry has no duplicate events/todos");
        try(var paths=Files.walk(dir)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}
        System.out.println("AssistantMixedBatchTest OK · two event creates, event edit, daily todo, shared new tag, one atomic commit");
    }
}

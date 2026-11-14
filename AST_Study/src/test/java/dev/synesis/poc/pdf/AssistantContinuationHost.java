package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import static dev.synesis.poc.planner.PlannerModel.*;
import java.nio.file.*;
import java.io.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;

/** Headless native dispatcher for a reproducible chat replay in a disposable data directory. */
public final class AssistantContinuationHost {
    public static void main(String[]args)throws Exception{
        Path root=Path.of(args[0]);Files.createDirectories(root.resolve("library"));
        PlannerStore store=new PlannerStore(root.resolve("planner.json"));
        store.saveEvent(new Event("hakji","학지","보존할 설명",LocalDateTime.parse("2026-11-06T14:00"),LocalDateTime.parse("2026-11-06T17:00"),false,EventColor.GREEN,List.of(),false,Repeat.NONE,-1));
        store.saveEvent(new Event("other","다른 일정","",LocalDateTime.parse("2026-11-05T10:00"),LocalDateTime.parse("2026-11-05T11:00"),false,EventColor.BLUE,List.of(),false,Repeat.NONE,-1));
        AssistantLocal local=new AssistantLocal(store,root.resolve("preferences.json"),()->JsonParser.parseString("{\"name\":\"테스트\",\"plan\":\"Test\",\"credits\":100}").getAsJsonObject());
        local.attachLibrary(new AssistantLibrary(root.resolve("library")),new AssistantLibraryUi(){
            public JsonObject viewContext(){return JsonParser.parseString("{\"screen\":\"library\",\"currentFolderId\":\"\",\"search\":\"\"}").getAsJsonObject();}
            public CompletionStage<JsonObject> navigateFolder(String id){return CompletableFuture.completedFuture(new JsonObject());}
            public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(new JsonObject());}
            public Object prepareMutation(JsonArray changes){return changes;}
            public void cancelMutation(Object value){}
            public CompletionStage<JsonObject> finishMutation(Object value,JsonObject result){return CompletableFuture.completedFuture(result);}
        });
        try(BufferedReader reader=new BufferedReader(new InputStreamReader(System.in,java.nio.charset.StandardCharsets.UTF_8))){
            String line;while((line=reader.readLine())!=null){JsonObject request=JsonParser.parseString(line).getAsJsonObject(),reply;
                switch(request.get("operation").getAsString()){
                    case "begin"->{local.begin("five-turn",request.get("turn").getAsString(),request.get("question").getAsString(),request.getAsJsonArray("history"));reply=new JsonObject();reply.addProperty("ok",true);}
                    case "finish"->{local.finish(request.get("answer").getAsString());reply=new JsonObject();reply.addProperty("ok",true);}
                    case "call"->reply=AssistantLocalTest.call(local,request.get("tool").getAsString(),request.getAsJsonObject("arguments"),request.get("quote").getAsString());
                    case "snapshot"->{reply=new JsonObject();reply.addProperty("revision",store.load().revision());JsonArray events=new JsonArray();for(Event event:store.load().events()){JsonObject row=new JsonObject();row.addProperty("id",event.id());row.addProperty("title",event.title());row.addProperty("color",event.color().name());row.addProperty("start",event.start().toString());row.addProperty("end",event.end().toString());row.addProperty("description",event.description());events.add(row);}reply.add("events",events);}
                    default->throw new IllegalArgumentException("Unknown replay operation");
                }
                System.out.println(reply);System.out.flush();
            }
        }
    }
}

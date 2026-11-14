package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.io.*;
import java.nio.file.*;
import java.util.concurrent.*;

/** Native chat replay with disposable documents; never opens an app or user library. */
public final class AssistantTerminologyFixtureHost {
    public static void main(String[] args)throws Exception{
        Path root=Path.of(args[0]).toAbsolutePath().normalize();
        Path allowed=Path.of(System.getProperty("user.dir")).toAbsolutePath().resolve("output/assistant-intent-wording-20261102/runs");
        if(!root.startsWith(allowed)||Files.exists(root))throw new IllegalArgumentException("new disposable fixture required");
        Path data=root.resolve("library");Files.createDirectories(data);
        var org=PdfLibraryOrganization.load(data);
        String course=org.createFolder("","금융강의").id(),outside=org.createFolder("","다른 과목").id();
        for(int i=0;i<3;i++){
            String id=String.valueOf((char)('a'+i)).repeat(64);
            AssistantRenameFixtureHost.document(data,id,i==2?"다른 과목.pdf":"금융-"+(i+1)+"주차.pdf");
            org.moveDocument(id,i==2?outside:course);
        }
        AssistantLibrary library=new AssistantLibrary(data);
        AssistantLocal local=new AssistantLocal(new PlannerStore(root.resolve("planner.json")),root.resolve("preferences.json"),JsonObject::new);
        local.attachLibrary(library,new AssistantLibraryUi(){
            public JsonObject viewContext(){JsonObject v=new JsonObject();v.addProperty("screen","library");v.addProperty("currentFolderId",course);v.addProperty("currentPath","홈화면 > 금융강의");v.addProperty("search","");return v;}
            public CompletionStage<JsonObject> navigateFolder(String id){return CompletableFuture.completedFuture(new JsonObject());}
            public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(new JsonObject());}
            public Object prepareMutation(JsonArray changes){return changes;}
            public CompletionStage<JsonObject> finishMutation(Object prepared,JsonObject result){return CompletableFuture.completedFuture(result);}
        });
        try(var input=new BufferedReader(new InputStreamReader(System.in,java.nio.charset.StandardCharsets.UTF_8))){
            for(String line;(line=input.readLine())!=null;){JsonObject request=JsonParser.parseString(line).getAsJsonObject(),reply;
                switch(request.get("operation").getAsString()){
                    case "begin"->{local.begin("terminology",request.get("turn").getAsString(),request.get("question").getAsString(),request.getAsJsonArray("history"));reply=new JsonObject();}
                    case "finish"->{local.finish(request.get("answer").getAsString());reply=new JsonObject();}
                    case "call"->reply=AssistantLocalTest.call(local,request.get("tool").getAsString(),request.getAsJsonObject("arguments"),request.get("quote").getAsString());
                    case "snapshot"->reply=library.snapshot();
                    default->throw new IllegalArgumentException("unknown fixture operation");
                }
                System.out.println(reply);System.out.flush();
            }
        }
    }
}

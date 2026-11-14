package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.io.*;
import java.nio.file.*;
import java.util.concurrent.*;

/** JSON-lines bridge for live model validation on an explicitly supplied disposable root. */
public final class AssistantRenameFixtureHost {
    static JsonObject obj(String...pairs){JsonObject o=new JsonObject();for(int i=0;i<pairs.length;i+=2)o.addProperty(pairs[i],pairs[i+1]);return o;}
    static void document(Path root,String id,String name)throws Exception{
        Path p=root.resolve(id);Files.createDirectories(p.resolve("notes"));Files.writeString(p.resolve("source.pdf"),"%PDF-1.4\nrename fixture");Files.writeString(p.resolve("notes/note.txt"),"preserve me");
        java.util.Properties props=new java.util.Properties();props.setProperty("name",name);try(var out=Files.newOutputStream(p.resolve("library.properties"))){props.store(out,"fixture");}
    }
    public static void main(String[] args)throws Exception{
        Path root=Path.of(args[0]).toAbsolutePath().normalize();
        if(!root.startsWith(Path.of(System.getProperty("user.dir")).toAbsolutePath().resolve("build/assistant-rename-eval-20261025"))||Files.exists(root))throw new IllegalArgumentException("new evaluation fixture root required");
        Files.createDirectories(root);var org=PdfLibraryOrganization.load(root);
        org.createFolder("","수학 자료");org.createFolder("","영어 자료");
        document(root,"a".repeat(64),"강의1.pdf");document(root,"b".repeat(64),"강의2.pdf");document(root,"c".repeat(64),"기존 이름.pdf");
        AssistantLibrary library=new AssistantLibrary(root);
        AssistantLocal host=new AssistantLocal(new PlannerStore(root.resolve("planner.json")),root.resolve("preferences.json"),JsonObject::new);
        host.attachLibrary(library,new AssistantLibraryUi(){
            public JsonObject viewContext(){JsonObject v=obj("screen","library","currentFolderId","","currentPath","홈화면","search","");v.addProperty("libraryVisible",true);v.add("visibleItems",new JsonArray());return v;}
            public CompletionStage<JsonObject> navigateFolder(String id){return CompletableFuture.completedFuture(obj("status","opened"));}
            public CompletionStage<JsonObject> openDocument(String id){return CompletableFuture.completedFuture(obj("status","opened"));}
            public Object prepareMutation(JsonArray changes){return changes;}
            public CompletionStage<JsonObject> finishMutation(Object capture,JsonObject committed){return CompletableFuture.completedFuture(committed);}
        });
        try(var input=new BufferedReader(new InputStreamReader(System.in,java.nio.charset.StandardCharsets.UTF_8))){
            for(String line;(line=input.readLine())!=null;){JsonObject command=JsonParser.parseString(line).getAsJsonObject(),result;
                switch(command.get("method").getAsString()){
                    case "begin"->{host.begin(command.get("session").getAsString(),command.get("turn").getAsString(),command.get("question").getAsString());result=new JsonObject();}
                    case "snapshot"->result=library.snapshot();
                    case "call"->{JsonObject request=command.getAsJsonObject("request");result=host.handle(request);}
                    default->throw new IllegalArgumentException("unknown fixture command");
                }
                System.out.println(new Gson().toJson(result));System.out.flush();
            }
        }
    }
}

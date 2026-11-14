package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Disposable virtual library only; no native UI, model, network or live user files. */
public final class AssistantLibraryTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static JsonObject json(String value){return JsonParser.parseString(value).getAsJsonObject();}
    private static JsonArray changes(JsonObject... values){JsonArray out=new JsonArray();for(var value:values)out.add(value);return out;}
    private static String operation(String value){return PdfLibraryOrganization.sha256(value.getBytes(StandardCharsets.UTF_8));}
    private static String revision(AssistantLibrary library)throws Exception{return library.snapshot().get("revision").getAsString();}
    private static void document(Path root,String id,String name)throws Exception{Path folder=root.resolve(id);Files.createDirectories(folder);Files.writeString(folder.resolve("source.pdf"),"%PDF-1.4\n");Properties properties=new Properties();properties.setProperty("name",name);try(var out=Files.newOutputStream(folder.resolve("library.properties"))){properties.store(out,"fixture");}}
    private static JsonObject move(String kind,String id,String parent){JsonObject out=new JsonObject();out.addProperty("operation","move");out.addProperty("kind",kind);out.addProperty("id",id);out.addProperty("parentId",parent);return out;}
    private static JsonObject folder(String name,String parent,String reference){JsonObject out=new JsonObject();out.addProperty("operation","createFolder");out.addProperty("name",name);out.addProperty("parentId",parent);if(reference!=null)out.addProperty("ref",reference);return out;}
    public static void main(String[] args)throws Exception{
        Path root=Files.createTempDirectory("assistant-library-");AssistantLibrary library=new AssistantLibrary(root);check(library.snapshot().getAsJsonArray("items").isEmpty(),"empty library");check(!Files.exists(root.resolve("library-organization.json")),"reads do not create organization");
        String a="a".repeat(64),b="b".repeat(64),c="c".repeat(64);document(root,a,"2021기출.pdf");document(root,b,"2021기출.pdf");document(root,c,"2021기출해설.pdf");
        var org=PdfLibraryOrganization.load(root);var first=org.createFolder("","폴더1");var fourth=org.createFolder("","폴더4");var nested=org.createFolder(first.id(),"폴더3");org.moveDocument(a,first.id());org.moveDocument(b,fourth.id());org.createFolder("","기출문제모음");
        JsonObject all=library.query(json("{\"query\":\"2021기출\",\"kind\":\"document\"}"));check(all.get("total").getAsInt()==3&&all.get("exactMatches").getAsInt()==2,"duplicates plus similar names reported");
        var rows=all.getAsJsonArray("items");check(rows.get(0).getAsJsonObject().get("exactMatch").getAsBoolean()&&rows.get(1).getAsJsonObject().get("exactMatch").getAsBoolean(),"exact duplicates rank before similar");check(!rows.get(0).getAsJsonObject().get("parentPath").getAsString().equals(rows.get(1).getAsJsonObject().get("parentPath").getAsString()),"duplicate choices include full parent paths");check(!all.toString().contains(root.toString()),"catalog exposes virtual paths only");
        check(library.query(json("{\"parentId\":\"\",\"kind\":\"document\"}")).get("total").getAsInt()==1,"empty parent means current home only");
        JsonObject firstPage=library.query(json("{\"limit\":1}"));JsonObject next=json("{\"offset\":1,\"limit\":1}");try{library.query(next);throw new AssertionError("missing pagination revision");}catch(java.io.IOException expected){checks++;}next.add("expectedRevision",firstPage.get("revision"));check(library.query(next).getAsJsonArray("items").size()==1,"stable pagination");
        JsonObject fuzzy=library.query(json("{\"kind\":\"folder\",\"query\":\"기출모음\"}"));
        check(fuzzy.getAsJsonArray("items").asList().stream().anyMatch(e->e.getAsJsonObject().get("name").getAsString().equals("기출문제모음")&&e.getAsJsonObject().get("matchQuality").getAsString().equals("similar")),"inserted word folder suggestions");
        String before=revision(library);JsonArray batch=changes(folder("기출모음","","newFolder"),move("document",a,"@newFolder"),move("document",b,"@newFolder"));JsonObject applied=library.apply(operation("organize"),before,batch);String created=applied.getAsJsonArray("createdFolders").get(0).getAsJsonObject().get("id").getAsString();
        org=PdfLibraryOrganization.load(root);check(org.location(a).equals(created)&&org.location(b).equals(created),"create folder plus two moves commit together");check(applied.getAsJsonArray("moved").get(0).getAsJsonObject().get("sourceParentId").getAsString().equals(first.id()),"move result includes animation source");check(applied.get("revision").getAsString().equals(revision(library)),"result uses catalog revision");
        JsonObject ranked=library.query(json("{\"kind\":\"folder\",\"query\":\"기출모음\"}"));check(ranked.getAsJsonArray("items").get(0).getAsJsonObject().get("matchQuality").getAsString().equals("exact"),"exact folder ranks before fuzzy suggestion");
        String after=Files.readString(root.resolve("library-organization.json"));JsonObject replay=library.apply(operation("organize"),before,batch);check(replay.get("replayed").getAsBoolean()&&Files.readString(root.resolve("library-organization.json")).equals(after),"same operation retry has one effect");
        org.createFolder("","직접 만든 폴더");check(library.apply(operation("organize"),before,batch).get("replayed").getAsBoolean(),"normal saves preserve assistant receipts");
        before=revision(library);byte[] original=Files.readAllBytes(root.resolve("library-organization.json"));
        try{library.apply(operation("invalid"),before,changes(folder("저장되면안됨","","temp"),move("folder",first.id(),nested.id())));throw new AssertionError("cycle accepted");}catch(java.io.IOException expected){checks++;}check(Arrays.equals(original,Files.readAllBytes(root.resolve("library-organization.json"))),"invalid last step rolls back whole batch");
        PdfLibraryStore.rename(root,c,"다른 이름.pdf");try{library.apply(operation("stale-name"),before,changes(move("document",c,created)));throw new AssertionError("stale catalog accepted");}catch(java.io.IOException expected){checks++;}
        var stale=PdfLibraryOrganization.load(root);var fresh=PdfLibraryOrganization.load(root);fresh.createFolder("","동시수정");try{stale.createFolder("","덮어쓰기");throw new AssertionError("concurrent editor overwrite accepted");}catch(java.io.IOException expected){checks++;}check(PdfLibraryOrganization.load(root).folders().stream().anyMatch(f->f.name().equals("동시수정")),"concurrent user edit retained");
        before=revision(library);library.apply(operation("folder-move"),before,changes(move("folder",nested.id(),fourth.id())));org=PdfLibraryOrganization.load(root);check(org.folder(nested.id()).parentId().equals(fourth.id()),"folder moves supported");
        check(AssistantLibrary.find(library.snapshot(),"folder",nested.id()).get("path").getAsString().equals("홈화면 > 폴더4 > 폴더3"),"nested full path updates after move");
        System.out.println("AssistantLibraryTest OK · "+checks+" catalog, duplicate, transaction, receipt and concurrency checks");
    }
}

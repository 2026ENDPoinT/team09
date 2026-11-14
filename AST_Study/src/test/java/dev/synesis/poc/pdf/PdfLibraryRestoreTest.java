package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Restore provenance/atomicity on disposable storage, never real user PDFs. */
public final class PdfLibraryRestoreTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private interface Task{void run()throws Exception;}
    private static void denied(Task task)throws Exception{try{task.run();throw new AssertionError("unsafe restore accepted");}catch(java.io.IOException expected){checks++;}}
    private static String doc(Path root,char digit)throws Exception{
        String id=String.valueOf(digit).repeat(64);Path dir=root.resolve(id);Files.createDirectories(dir.resolve("generated"));Files.createDirectories(dir.resolve("requests"));
        Files.writeString(dir.resolve("source.pdf"),"%PDF "+digit);Files.writeString(dir.resolve("generated/answer.json"),"learning");Files.writeString(dir.resolve("requests/history.json"),"history");return id;
    }
    private static JsonObject json(String text){return JsonParser.parseString(text).getAsJsonObject();}
    private static PdfLibraryOrganization.RestoreResult restore(Path root,List<String> docs,List<String> folders)throws Exception{var org=PdfLibraryOrganization.load(root);return org.restoreFromTrash(org.revision(),docs,folders);}
    public static void main(String[] ignored)throws Exception{
        Path root=Files.createTempDirectory("synesis-restore-");
        try{
            String a=doc(root,'a'),b=doc(root,'b'),c=doc(root,'c');var org=PdfLibraryOrganization.load(root);var original=org.createFolder("","수업");var other=org.createFolder("","보관");org.moveDocument(a,original.id());
            org.moveToTrash(List.of(a),List.of());org=PdfLibraryOrganization.load(root);org.renameFolder(original.id(),"수업 변경");
            var result=restore(root,List.of(a),List.of());check(result.homeFallbackCount()==0&&PdfLibraryOrganization.load(root).location(a).equals(original.id()),"renamed parent not restored by stable ID");
            org=PdfLibraryOrganization.load(root);org.moveDocument(a,other.id());org.moveToTrash(List.of(a),List.of());restore(root,List.of(a),List.of());check(PdfLibraryOrganization.load(root).location(a).equals(other.id()),"second deletion used older provenance");
            check(Files.readString(root.resolve(a).resolve("source.pdf")).equals("%PDF a")&&Files.readString(root.resolve(a).resolve("generated/answer.json")).equals("learning")&&Files.readString(root.resolve(a).resolve("requests/history.json")).equals("history"),"restore changed PDF or data");
            org=PdfLibraryOrganization.load(root);var parent=org.createFolder(original.id(),"과제");var child=org.createFolder(parent.id(),"실습");org.moveDocument(b,child.id());org.moveToTrash(List.of(c,b),List.of(parent.id(),child.id()));
            result=restore(root,List.of(c,b),List.of(child.id(),parent.id()));org=PdfLibraryOrganization.load(root);
            check(result.restoredCount()==4&&result.homeFallbackCount()==0,"mixed restore result wrong");check(org.folder(parent.id()).parentId().equals(original.id())&&org.folder(child.id()).parentId().equals(parent.id())&&org.location(b).equals(child.id())&&org.location(c).isEmpty(),"mixed selection flattened/misplaced subtree");
            org.moveToTrash(List.of(b),List.of());org.moveToTrash(List.of(),List.of(child.id()));
            result=restore(root,List.of(b),List.of(child.id()));check(result.homeFallbackCount()==0&&PdfLibraryOrganization.load(root).location(b).equals(child.id()),"restore did not reuse parent restored in same batch");
            org=PdfLibraryOrganization.load(root);org.moveToTrash(List.of(a),List.of());org.removeFolderTree(other.id());result=restore(root,List.of(a),List.of());check(result.homeFallbackCount()==1&&PdfLibraryOrganization.load(root).location(a).isEmpty(),"missing parent did not safely fall back home");
            org=PdfLibraryOrganization.load(root);org.moveDocument(a,child.id());org.moveToTrash(List.of(a),List.of());org.moveToTrash(List.of(),List.of(parent.id()));result=restore(root,List.of(a),List.of());check(result.homeFallbackCount()==1&&PdfLibraryOrganization.load(root).location(a).isEmpty(),"restored file remains inside trash parent");
            org=PdfLibraryOrganization.load(root);String stale=org.revision();org.createFolder("","변경");denied(()->PdfLibraryOrganization.load(root).restoreFromTrash(stale,List.of(),List.of(parent.id())));check(PdfLibraryOrganization.load(root).isFolderInTrash(parent.id()),"stale restore committed");
            denied(()->restore(root,List.of(a),List.of(parent.id())));check(PdfLibraryOrganization.load(root).isFolderInTrash(parent.id()),"invalid mixed batch partially restored");denied(()->restore(root,List.of(),List.of(PdfLibraryOrganization.TRASH_ID)));
            org=PdfLibraryOrganization.load(root);var collision=org.createFolder(original.id(),"과제");denied(()->restore(root,List.of(),List.of(parent.id())));check(PdfLibraryOrganization.load(root).isFolderInTrash(parent.id())&&PdfLibraryOrganization.load(root).folder(collision.id())!=null,"name conflict overwritten or partially committed");
            // Dragging and assistant trash/move routes also save the pre-trash location.
            org=PdfLibraryOrganization.load(root);org.moveDocument(a,original.id());org.moveDocument(a,PdfLibraryOrganization.TRASH_ID);restore(root,List.of(a),List.of());check(PdfLibraryOrganization.load(root).location(a).equals(original.id()),"drag move failed to record origin");
            var library=new AssistantLibrary(root);JsonArray changes=new JsonArray();changes.add(json("{\"operation\":\"trash\",\"kind\":\"document\",\"id\":\""+a+"\"}"));library.apply("1".repeat(64),library.snapshot().get("revision").getAsString(),changes);restore(root,List.of(a),List.of());check(PdfLibraryOrganization.load(root).location(a).equals(original.id()),"assistant deletion failed to record origin");
            // Backward compatibility: old assistant receipts can recover exact location without new origins.
            library.apply("2".repeat(64),library.snapshot().get("revision").getAsString(),changes);Path metadata=root.resolve("library-organization.json");JsonObject old=json(Files.readString(metadata));old.remove("trashOrigins");Files.writeString(metadata,old.toString());result=restore(root,List.of(a),List.of());check(result.homeFallbackCount()==0&&PdfLibraryOrganization.load(root).location(a).equals(original.id()),"legacy receipt source lost");
            org=PdfLibraryOrganization.load(root);org.moveToTrash(List.of(c),List.of());old=json(Files.readString(metadata));old.remove("trashOrigins");Files.writeString(metadata,old.toString());result=restore(root,List.of(c),List.of());check(result.homeFallbackCount()==1&&PdfLibraryOrganization.load(root).location(c).isEmpty(),"unknown old source did not fall back home");
            check(!json(Files.readString(metadata)).has("trashOrigins")||!json(Files.readString(metadata)).getAsJsonObject("trashOrigins").has("document:"+a),"restored origin record leaked");
            System.out.println("PdfLibraryRestoreTest passed: "+checks+" provenance, mixed batch, subtree, repeat-delete, missing-parent, stale, conflict and legacy checks");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}}
    }
}

package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.nio.file.*;
import java.util.*;

/** Disposable storage only: no live library, model calls or native dialogs. */
public final class PdfLibraryTrashTest {
    private static int checks;
    private static void check(boolean condition,String message){checks++;if(!condition)throw new AssertionError(message);}
    private interface IoTask{void run()throws Exception;}
    private static void denied(IoTask task)throws Exception{try{task.run();throw new AssertionError("unsafe operation accepted");}catch(IOException expected){checks++;}}
    private static String doc(Path root,char digit)throws Exception{
        String id=String.valueOf(digit).repeat(64);Path folder=root.resolve(id);Files.createDirectories(folder.resolve("generated"));
        Files.createDirectories(folder.resolve("requests"));Files.writeString(folder.resolve("source.pdf"),"%PDF fixture "+digit);
        Files.writeString(folder.resolve("generated/answer.json"),"{\"answer\":\"보존할 학습 데이터\"}");
        Files.writeString(folder.resolve("requests/history.json"),"{\"question\":\"보존할 대화\"}");return id;
    }
    private static JsonObject json(String text){return JsonParser.parseString(text).getAsJsonObject();}
    public static void main(String[] args)throws Exception{
        Path root=Files.createTempDirectory("synesis-trash-").resolve("library");Files.createDirectories(root);
        var org=PdfLibraryOrganization.load(root);var original=org.createFolder("","휴지통");
        var trash=org.ensureTrashFolder();check(!trash.id().equals(original.id()),"adopted a user folder as trash");
        check(trash.parentId().isEmpty()&&trash.name().contains("휴지통"),"trash is not a home folder");
        String revision=org.revision();org.ensureTrashFolder();check(revision.equals(org.revision()),"unchanged trash causes writes");
        check(PdfLibraryOrganization.load(root).folder(trash.id())!=null,"trash not persisted");
        denied(()->PdfLibraryOrganization.load(root).moveFolder(trash.id(),original.id()));
        denied(()->PdfLibraryOrganization.load(root).renameFolder(trash.id(),"없애기"));
        denied(()->PdfLibraryOrganization.load(root).removeFolderTree(trash.id()));
        denied(()->PdfLibraryOrganization.load(root).setColor(trash.id(),"#ff0000"));

        String a=doc(root,'a'),b=doc(root,'b'),c=doc(root,'c'),d=doc(root,'d');
        var parent=org.createFolder("","수업");var child=org.createFolder(parent.id(),"하위");
        org.moveDocument(a,child.id());org.moveDocument(b,parent.id());
        byte[] source=Files.readAllBytes(root.resolve(a).resolve("source.pdf"));
        byte[] answer=Files.readAllBytes(root.resolve(a).resolve("generated/answer.json"));
        org.moveToTrash(List.of(a,c),List.of(child.id(),parent.id()));
        org=PdfLibraryOrganization.load(root);
        check(org.folder(parent.id()).parentId().equals(trash.id()),"selected folder not moved");
        check(org.folder(child.id()).parentId().equals(parent.id()),"nested selection flattened the tree");
        check(org.location(a).equals(child.id())&&org.location(b).equals(parent.id()),"nested document locations changed");
        check(org.location(c).equals(trash.id())&&org.location(d).isEmpty(),"selection moved extra files");
        check(org.isDocumentInTrash(a)&&org.isDocumentInTrash(b)&&org.isFolderInTrash(child.id()),"descendant trash detection failed");
        check(Arrays.equals(source,Files.readAllBytes(root.resolve(a).resolve("source.pdf")))&&Arrays.equals(answer,Files.readAllBytes(root.resolve(a).resolve("generated/answer.json"))),"trash erased source or generated data");
        check(Files.exists(root.resolve(a).resolve("requests/history.json")),"trash erased chat history");

        AssistantLibrary library=new AssistantLibrary(root);
        JsonObject defaultSearch=library.query(json("{\"kind\":\"document\"}"));
        check(defaultSearch.get("total").getAsInt()==1,"normal assistant query includes discarded documents");
        JsonObject inTrash=library.query(json("{\"kind\":\"document\",\"parentId\":\""+trash.id()+"\"}"));
        check(inTrash.get("total").getAsInt()==1,"explicit trash query hides contents");
        org.moveDocument(c,"");check(!PdfLibraryOrganization.load(root).isDocumentInTrash(c),"normal move cannot restore a document");
        PdfLibraryStore.deleteGeneratedData(root,c);
        check(Files.exists(root.resolve(c).resolve("source.pdf"))&&!Files.exists(root.resolve(c).resolve("generated")),"data-only delete touched PDF");
        check(PdfLibraryOrganization.load(root).location(c).isEmpty(),"data delete moved document to trash");
        org=PdfLibraryOrganization.load(root);var other=org.createFolder("","별도");var duplicate=org.createFolder(other.id(),"수업");
        org.moveToTrash(List.of(),List.of(duplicate.id()));check(org.folder(duplicate.id()).parentId().equals(trash.id()),"same-name discarded folders collide");

        var current=PdfLibraryOrganization.load(root);String before=current.revision();
        var guarded=current;
        denied(()->guarded.permanentlyDeleteTrashed(before,List.of(d),List.of()));
        check(Files.exists(root.resolve(d).resolve("source.pdf")),"permanent delete accepted home document");
        denied(()->guarded.permanentlyDeleteTrashed(before,List.of(a),List.of(parent.id())));
        check(Files.exists(root.resolve(a).resolve("source.pdf")),"incomplete tree validation partially deleted data");
        current.moveDocument(a,"");
        denied(()->PdfLibraryOrganization.load(root).permanentlyDeleteTrashed(before,List.of(a,b),List.of(parent.id())));
        check(Files.exists(root.resolve(a).resolve("source.pdf"))&&Files.exists(root.resolve(b).resolve("source.pdf")),"stale delete erased a restored file");
        current=PdfLibraryOrganization.load(root);current.moveDocument(a,child.id());
        current.permanentlyDeleteTrashed(current.revision(),List.of(a,b),List.of(parent.id()));
        var finalState=PdfLibraryOrganization.load(root);
        check(!Files.exists(root.resolve(a).resolve("source.pdf"))&&!Files.exists(root.resolve(b).resolve("source.pdf")),"confirmed permanent deletion retained PDFs");
        check(finalState.folder(parent.id())==null&&finalState.folder(child.id())==null,"permanent folder delete retained tree");
        check(finalState.folder(trash.id())!=null&&Files.exists(root.resolve(c).resolve("source.pdf"))&&Files.exists(root.resolve(d).resolve("source.pdf")),"permanent deletion affected trash or unrelated items");

        JsonArray changes=new JsonArray();changes.add(json("{\"operation\":\"move\",\"kind\":\"folder\",\"id\":\""+trash.id()+"\",\"parentId\":\""+original.id()+"\"}"));
        denied(()->library.apply("f".repeat(64),library.snapshot().get("revision").getAsString(),changes));
        check(PdfLibraryOrganization.load(root).folder(trash.id()).parentId().isEmpty(),"assistant moved system trash");
        System.out.println("PdfLibraryTrashTest passed: "+checks+" storage, subtree, restore, data-only, stale-delete and assistant checks");
    }
}

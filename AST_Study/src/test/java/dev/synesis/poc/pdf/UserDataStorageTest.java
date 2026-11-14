package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.*;
import java.nio.file.*;
import java.math.BigDecimal;
import org.apache.pdfbox.pdmodel.*;

/** End-to-end local path routing, Java/Python wallet, relocatable files and PDF deletion safety. */
public final class UserDataStorageTest {
    private static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);}
    private static void python(String code,String...args) throws Exception {
        java.util.List<String> command=new java.util.ArrayList<>(java.util.List.of(PythonRuntime.pdf(),"-B","-c",code));
        command.addAll(java.util.List.of(args));
        ProcessBuilder builder=AppPaths.process(new ProcessBuilder(command)).directory(Path.of(System.getProperty("java.io.tmpdir")).toFile());
        builder.environment().put("PYTHONPATH",AppPaths.appRoot().resolve("scripts").toString());
        Process p=builder.redirectErrorStream(true).start();String out=new String(p.getInputStream().readAllBytes());
        check(p.waitFor()==0,"Python from unrelated cwd: "+out);
    }
    public static void main(String[] args) throws Exception {
        Path temp=Files.createTempDirectory("synesis-user-store-").toRealPath(),data=temp.resolve("사용자 자료");
        System.setProperty("synesis.dataRoot",data.toString());
        python("from migrate_user_data import migrate;import sys;migrate(sys.argv[1],sys.argv[2],True,check_busy=False)",temp.resolve("empty").toString(),data.toString());
        check(PdfLibraryStore.defaultRoot().equals(data.resolve("library")),"canonical library");
        Path input=temp.resolve("original.pdf");
        try(PDDocument doc=new PDDocument()){doc.addPage(new PDPage());doc.save(input.toFile());}
        String id;
        try(PdfSource source=PdfSource.open(input,AppPaths.library())) {
            id=source.id;check(source.folder.equals(data.resolve("library").resolve(id)),"per-file folder");
            check(source.render(1,1).getWidth()>0,"PDF rendering");
            JsonObject request=new JsonObject();request.addProperty("question","안녕");
            Path file=source.folder.resolve("requests/hello.json");Files.createDirectories(file.getParent());Files.writeString(file,request.toString());
            Files.writeString(source.folder.resolve("document.json"),"{\"documentId\":\""+id+"\",\"pages\":[],\"chunks\":[]}");
            PdfProcess worker=new PdfProcess();
            worker.run("pdf_ai.py",java.util.List.of("tutor","--folder",source.folder.toString(),"--request",file.toString()),worker.ticket(),event->{});
            check(Files.isRegularFile(file.resolveSibling("hello.result.json")),"PDF worker finds scripts and runtime");worker.close();
        }
        String reference=AppPaths.reference(AppPaths.document(id).resolve("source.pdf"));
        check(reference.startsWith("synesis-data://library/"),"portable reference");
        check(AppPaths.stored(reference).equals(AppPaths.document(id).resolve("source.pdf")),"reference resolution");
        try{AppPaths.stored("synesis-data://../outside");throw new AssertionError("escape");}catch(IllegalArgumentException expected){}
        JsonObject note=new JsonObject();note.addProperty("body","메모 보존");
        UserDataStore.save(UserDataStore.Area.NOTES,"note-1",note);
        UserDataStore.save(UserDataStore.Area.PLANNER,"task-1",note);
        check(UserDataStore.read(UserDataStore.Area.NOTES,"note-1").equals(note),"notes persistence");
        check(UserDataStore.file(UserDataStore.Area.PLANNER,"task-1").startsWith(data),"planner under same user root");
        var preferences=UserPreferences.forPackage(UserDataStorageTest.class);preferences.put("storageTest","yes");
        check(UserPreferences.forPackage(UserDataStorageTest.class).get("storageTest","").equals("yes"),"portable preferences");
        Path library=AppPaths.library();CreditWallet.read(library,0);CreditWallet.topUp(library,CreditWallet.PLANS[0]);CreditWallet.activateBilling(library,0);
        python("from synesis_paths import wallet_for_document;from pdf_credit_billing import Billing;import sys;b=Billing(wallet_for_document(sys.argv[1]),'storage-op','chat');b.reserve('storage-charge',.002);b.settle('storage-charge',.001);b.settle('storage-charge',.001)",AppPaths.document(id).toString());
        check(CreditWallet.read(library,0).balance().subtract(new BigDecimal("2700").subtract(CreditWallet.credits(.001))).abs().doubleValue()<.000001,"single Java/Python debit in account");
        check(Files.isRegularFile(data.resolve("account/credits-wallet.json")),"wallet independent of library");
        check(!Files.exists(data.resolve("credits-wallet.json")),"no duplicate wallet");
        Path audio=AppPaths.recordingParts(id).resolve("part-1/audio.wav");Files.createDirectories(audio.getParent());Files.write(audio,new byte[]{1,2});
        Path notes=AppPaths.documentNotes(id);Files.createDirectories(notes);Files.writeString(notes.resolve("note.json"),note.toString());
        PdfLibraryStore.deleteFile(library,id);
        check(!Files.exists(AppPaths.document(id).resolve("source.pdf")),"PDF removed");
        check(Files.isRegularFile(audio)&&Files.isRegularFile(notes.resolve("note.json")),"PDF deletion preserves independent notes and recordings");
        check(Files.isRegularFile(data.resolve("account/credits-wallet.json")),"PDF deletion preserves wallet");
        System.out.println("UserDataStorageTest OK: PDF import/render/worker, shared notes/planner, preferences, cross-language debit and deletion safety");
    }
}

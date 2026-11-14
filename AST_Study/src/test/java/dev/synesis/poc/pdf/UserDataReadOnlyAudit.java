package dev.synesis.poc.pdf;

import dev.synesis.poc.AppPaths;
import com.google.gson.*;
import java.nio.file.*;
import org.apache.pdfbox.Loader;

/** Read-only verification of the real migrated library. Does not instantiate UI or settle any usage. */
public final class UserDataReadOnlyAudit {
    public static void main(String[] args) throws Exception {
        int documents=0,pages=0,lectures=0,parts=0,holds=0;
        for(var item:PdfLibraryStore.list(AppPaths.library()))try(var pdf=Loader.loadPDF(item.source().toFile())) {
            documents++;pages+=pdf.getNumberOfPages();
        }
        try(var files=Files.list(AppPaths.lectureNotes())) {
            for(Path file:files.filter(p->p.toString().endsWith(".json")&&!p.toString().endsWith(".lecture.json")).toList()) {
                JsonObject lecture=JsonParser.parseString(Files.readString(file)).getAsJsonObject();lectures++;
                for(JsonElement item:lecture.getAsJsonArray("parts")) {
                    Path folder=AppPaths.stored(item.getAsJsonObject().get("folder").getAsString(),file);
                    if(!Files.isDirectory(folder))throw new AssertionError("Missing lecture part");parts++;
                }
            }
        }
        Path wallet=AppPaths.account().resolve("credits-wallet.json");
        JsonObject account=JsonParser.parseString(Files.readString(wallet)).getAsJsonObject();
        if(account.has("creditHolds"))for(JsonElement item:account.getAsJsonObject("creditHolds").asMap().values()) {
            JsonObject hold=item.getAsJsonObject();
            if(hold.has("ledgerPath")&&!hold.get("ledgerPath").isJsonNull()) {
                if(!Files.isRegularFile(AppPaths.stored(hold.get("ledgerPath").getAsString(),wallet)))throw new AssertionError("Missing held-usage ledger");holds++;
            }
        }
        System.out.printf("Read-only audit OK: %d PDFs / %d pages, %d lectures / %d audio parts, %d held ledger references%n",documents,pages,lectures,parts,holds);
    }
}

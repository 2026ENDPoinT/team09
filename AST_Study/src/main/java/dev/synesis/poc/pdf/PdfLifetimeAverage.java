package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import dev.synesis.poc.AppPaths;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Read-only lifetime view; subscription periods and balance resets keep their own rules. */
final class PdfLifetimeAverage {
    private record HistoryFile(Path path,long modifiedAt) {}

    private PdfLifetimeAverage() {}

    static SubscriptionUsage.Snapshot read(Path root) throws IOException {
        Path history=AppPaths.accountForLibrary(root).resolve("credit-wallet-history");
        List<HistoryFile> files=new ArrayList<>();
        if(Files.isDirectory(history))try(var paths=Files.list(history)) {
            for(Path path:paths.filter(p->p.getFileName().toString().endsWith(".json")&&Files.isRegularFile(p)).toList())
                files.add(new HistoryFile(path,Files.getLastModifiedTime(path).toMillis()));
        }
        files.sort(Comparator.comparingLong(HistoryFile::modifiedAt).thenComparing(file->file.path().toString()));
        List<JsonObject> wallets=new ArrayList<>();
        for(HistoryFile file:files)try {
            wallets.add(JsonParser.parseString(Files.readString(file.path())).getAsJsonObject());
        }catch(RuntimeException invalid) {
            throw new IOException("이전 PDF 생성 사용 기록을 읽지 못했어요.",invalid);
        }
        // The current wallet is authoritative when a past operation was settled again.
        wallets.add(CreditWallet.usageData(root));
        try {return fromWallets(wallets);}
        catch(RuntimeException invalid) {throw new IOException("전체 PDF 생성 사용 기록을 읽지 못했어요.",invalid);}
    }

    static SubscriptionUsage.Snapshot fromWallets(List<JsonObject> oldestToNewest) {
        JsonObject operations=new JsonObject();
        for(JsonObject wallet:oldestToNewest) {
            if(!wallet.has("creditOperations"))continue;
            for(var entry:wallet.getAsJsonObject("creditOperations").entrySet())
                operations.add(entry.getKey(),entry.getValue().deepCopy());
        }
        JsonObject lifetime=new JsonObject();
        lifetime.add("creditOperations",operations);
        lifetime.add("creditHolds",new JsonObject());
        // No plan purchase date enters this view; use the existing category and cost arithmetic.
        return SubscriptionUsage.fromWallet(lifetime,Instant.EPOCH);
    }
}

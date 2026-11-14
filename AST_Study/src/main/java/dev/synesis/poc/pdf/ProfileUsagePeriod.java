package dev.synesis.poc.pdf;

import com.google.gson.JsonParser;
import java.io.IOException;
import java.nio.file.*;
import java.time.Instant;

final class ProfileUsagePeriod {
    static void save(Path root,Instant since) throws IOException {
        Path settings=dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("profile-usage-settings.json");
        Files.createDirectories(settings.getParent());
        if(Files.exists(settings)) {
            Path history=settings.resolveSibling("profile-usage-history");
            Files.createDirectories(history);
            Files.copy(settings,history.resolve(java.util.UUID.randomUUID()+".json"));
        }
        Path temp=Files.createTempFile(settings.getParent(),"profile-period-",".tmp");
        try {
            Files.writeString(temp,"{\"since\":\""+since+"\",\"timezone\":\"Asia/Seoul\"}");
            try {Files.move(temp,settings,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException ignored) {Files.move(temp,settings,StandardCopyOption.REPLACE_EXISTING);}
        } finally {Files.deleteIfExists(temp);}
    }

    static Instant since(Path root) throws IOException {
        Path settings=dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("profile-usage-settings.json");
        if(!Files.exists(settings))return Instant.parse("2026-10-14T12:45:00Z");
        try {return Instant.parse(JsonParser.parseString(Files.readString(settings)).getAsJsonObject().get("since").getAsString());}
        catch(RuntimeException invalid) {throw new IOException("사용량 표시 기준 시각을 읽지 못했어요.",invalid);}
    }
}

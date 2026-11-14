package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.AtomicMoveNotSupportedException;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.time.Instant;

/** Confirmed API usage across PDF work, tutor turns, and saved deletion history. */
final class PdfUsageStore {
    record Totals(long inputTokens, long outputTokens, double usd,
                  long unknownRequests, double uncertainReservedUsd, long unreadableFiles) {
        long tokens() { return inputTokens + outputTokens; }
    }

    private static final class Counter {
        long input, output, unknown, unreadable;
        double usd, reserved;

        void add(Counter other) {
            input += other.input; output += other.output; unknown += other.unknown;
            unreadable += other.unreadable; usd += other.usd; reserved += other.reserved;
        }

        Totals totals() { return new Totals(input, output, usd, unknown, reserved, unreadable); }
    }

    private PdfUsageStore() {}

    static Totals read(Path root, List<PdfLibraryStore.Item> items) {
        return read(root,items,null);
    }

    static Totals read(Path root,List<PdfLibraryStore.Item> items,Instant since) {
        Counter all = new Counter();
        for (PdfLibraryStore.Item item : items) all.add(readDocument(item.source().getParent(),since));
        Path history = historyFolder(root);
        if (Files.isDirectory(history)) try (var files = Files.list(history)) {
            files.filter(path -> path.getFileName().toString().endsWith(".json"))
                .forEach(path -> readLedger(path, all,since));
        } catch (IOException failure) { all.unreadable++; }
        return all.totals();
    }

    /** Keep billed usage after the stored PDF and its per-document ledger are deleted. */
    static void archiveBeforeDelete(Path root, PdfLibraryStore.Item item) throws IOException {
        Path folder = item.source().getParent();
        Counter usage = readDocument(folder);
        if (usage.unreadable > 0) throw new IOException("사용량 기록 일부를 읽지 못해 삭제를 중단했어요.");
        PdfFirstGenerationStats.read(root,List.of(item),Instant.EPOCH);
        PdfGenerationCostStats.archive(root,item);
        List<Path> ledgers = ledgerFiles(folder);
        if (ledgers.isEmpty()) return;
        Path history = historyFolder(root);
        Files.createDirectories(history);
        for (Path ledger : ledgers) {
            Path archived = history.resolve(UUID.randomUUID() + ".json");
            try { Files.move(ledger, archived, StandardCopyOption.ATOMIC_MOVE); }
            catch (AtomicMoveNotSupportedException ignored) { Files.move(ledger, archived); }
        }
    }

    private static Path historyFolder(Path root) {
        return dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("pdf-usage-history");
    }

    private static Counter readDocument(Path folder) {
        return readDocument(folder,null);
    }

    private static Counter readDocument(Path folder,Instant since) {
        Counter total = new Counter();
        try {
            for (Path path : ledgerFiles(folder)) readLedger(path, total,since);
        } catch (IOException failure) { total.unreadable++; }
        return total;
    }

    private static List<Path> ledgerFiles(Path folder) throws IOException {
        if (!Files.isDirectory(folder)) return List.of();
        try (var paths = Files.walk(folder, 5)) {
            return paths.filter(path -> path.getFileName().toString().endsWith(".json")
                    && path.getParent() != null
                    && path.getParent().getFileName().toString().equals("usage"))
                .collect(java.util.stream.Collectors.toCollection(ArrayList::new));
        }
    }

    private static void readLedger(Path path, Counter total,Instant since) {
        try {
            JsonObject ledger = JsonParser.parseString(Files.readString(path, StandardCharsets.UTF_8)).getAsJsonObject();
            JsonArray requests = ledger.getAsJsonArray("requests");
            if (requests == null) throw new IllegalArgumentException("requests missing");
            Counter one = new Counter();
            Instant fallback=ledger.has("createdAtMs")?Instant.ofEpochMilli(ledger.get("createdAtMs").getAsLong())
                :Files.readAttributes(path,java.nio.file.attribute.BasicFileAttributes.class).creationTime().toInstant();
            for (JsonElement element : requests) {
                JsonObject request = element.getAsJsonObject();
                Instant created=request.has("createdAtMs")?Instant.ofEpochMilli(request.get("createdAtMs").getAsLong()):fallback;
                if(since!=null && created.isBefore(since))continue;
                if ("settled".equals(string(request, "state"))) {
                    // A proven capacity rejection has a known zero fee but no
                    // token receipt. It is not a corrupt settled generation.
                    if (documentedNoCharge(request)) continue;
                    JsonObject usage = request.getAsJsonObject("usage");
                    if (usage == null) { one.unreadable++; continue; }
                    one.input += number(usage, "prompt_tokens", "input_tokens").longValue();
                    one.output += number(usage, "completion_tokens", "output_tokens").longValue();
                    one.usd += number(request, "estimatedUsd").doubleValue();
                } else {
                    one.unknown++;
                    one.reserved += number(request, "reservedUsd").doubleValue();
                }
            }
            total.add(one);
        } catch (Exception failure) { total.unreadable++; }
    }

    static boolean documentedNoCharge(JsonObject request) {
        try {
            if (!"settled".equals(string(request,"state"))
                    || !"newest-k1-2-1".equals(string(request,"strategy"))
                    || !"responses".equals(string(request,"inputApi"))
                    || !"flex".equals(string(request,"requestedServiceTier"))
                    || !"flex".equals(string(request,"returnedServiceTier"))
                    || !"flex".equals(string(request,"billedServiceTier"))
                    || !"failed".equals(string(request,"serverTerminalStatus"))
                    || !"native_resource_unavailable_flex_unavailable".equals(string(request,"feeEvidence"))
                    || !trueFlag(request,"documentedFlexNoCharge") || !trueFlag(request,"usageUnreported")
                    || !string(request,"requestId").matches("[a-f0-9]{32}")
                    || !string(request,"responseId").matches("resp_[A-Za-z0-9_-]+")
                    || !string(request,"responseCacheKey").matches("[a-f0-9]{64}")) return false;
            if (request.has("usage") && !request.get("usage").isJsonNull()) return false;
            var cost=request.get("estimatedUsd");
            if (cost==null || !cost.isJsonPrimitive() || !cost.getAsJsonPrimitive().isNumber()
                    || cost.getAsBigDecimal().signum()!=0) return false;
            return !request.has("finalTextChars") || request.get("finalTextChars").getAsBigDecimal().signum()==0;
        } catch (RuntimeException malformed) {return false;}
    }

    private static boolean trueFlag(JsonObject object,String key) {
        var value=object.get(key);
        return value!=null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()
            && value.getAsBoolean();
    }

    private static Number number(JsonObject object, String... keys) {
        for (String key : keys) if (object.has(key) && !object.get(key).isJsonNull()) {
            try { return object.get(key).getAsNumber(); }
            catch (Exception ignored) { /* Try the next provider field. */ }
        }
        return 0;
    }

    private static String string(JsonObject object, String key) {
        return object.has(key) && !object.get(key).isJsonNull() ? object.get(key).getAsString() : "";
    }
}

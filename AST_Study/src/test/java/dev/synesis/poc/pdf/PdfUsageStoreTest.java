package dev.synesis.poc.pdf;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;

/** Local ledger fixture: PDF, tutor, web search, comparison, and deletion history. */
public final class PdfUsageStoreTest {
    public static void main(String[] args) throws Exception {
        Path base = Files.createTempDirectory("synesis-usage-test-");
        try {
            Path root = base.resolve("pdf");
            String id = "a".repeat(64);
            Path folder = root.resolve(id);
            Files.createDirectories(folder.resolve("usage"));
            Files.write(folder.resolve("source.pdf"), new byte[]{1});
            Files.writeString(folder.resolve("usage/analysis.json"), """
                {"requests":[
                  {"state":"settled","kind":"page_study","usage":{"prompt_tokens":100,"completion_tokens":20},"estimatedUsd":0.002},
                  {"state":"settled","usage":{"prompt_tokens":40,"completion_tokens":10},"estimatedUsd":0.001},
                  {"state":"settled","kind":"web_search","usage":{"input_tokens":30,"output_tokens":5},"estimatedUsd":0.01},
                  {"state":"usage_unknown","reservedUsd":0.05}
                ]}
                """);
            Path compared = folder.resolve("comparison/direct-123/usage");
            Files.createDirectories(compared);
            Files.writeString(compared.resolve("comparison.json"), """
                {"requests":[{"state":"settled","usage":{"prompt_tokens":70,"completion_tokens":15},"estimatedUsd":0.004}]}
                """);
            PdfLibraryStore.Item item = new PdfLibraryStore.Item(id,folder.resolve("source.pdf"),"fixture",
                Instant.EPOCH,Instant.EPOCH);
            PdfUsageStore.Totals current=PdfUsageStore.read(root,List.of(item));
            check(current,240,50,0.017,1);
            PdfUsageStore.archiveBeforeDelete(root,item);
            PdfLibraryStore.deleteFile(root,id);
            PdfUsageStore.Totals historical=PdfUsageStore.read(root,List.of());
            check(historical,240,50,0.017,1);
            System.out.println("PdfUsageStoreTest OK");
        } finally {
            try (var paths=Files.walk(base)) {
                for (Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.deleteIfExists(path);
            }
        }
    }

    private static void check(PdfUsageStore.Totals value,long input,long output,double usd,long unknown) {
        if(value.inputTokens()!=input || value.outputTokens()!=output
                || Math.abs(value.usd()-usd)>0.0000001 || value.unknownRequests()!=unknown
                || value.unreadableFiles()!=0)
            throw new AssertionError("Wrong usage totals: "+value);
    }
}

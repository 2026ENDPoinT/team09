package dev.synesis.poc.pdf;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.time.Instant;
import java.util.Comparator;
import java.util.List;

/** Lifetime averages survive plan changes, deleted documents and archived/reset wallets. */
public final class PdfLifetimeAverageTest {
    private static final Instant PAID=Instant.parse("2026-10-23T00:00:00Z");

    public static void main(String[] args) throws Exception {
        JsonObject older=wallet(),current=wallet();
        operation(older,"old-deleted-pdf",PAID.minusSeconds(600),"summary","10");
        operation(older,"partial-rerun",PAID.minusSeconds(300),"summary","15");
        operation(current,"partial-rerun",PAID.minusSeconds(300),"summary","20");
        operation(current,"new-pdf",PAID.plusSeconds(1),"summary","30");
        for(String category:List.of("chat","voice","quiz","planning"))
            operation(current,category,PAID.plusSeconds(1),category,"900");
        JsonObject held=new JsonObject();held.addProperty("credits","500");
        current.getAsJsonObject("creditHolds").add("pending",held);
        String original=current.toString();
        var lifetime=PdfLifetimeAverage.fromWallets(List.of(older,current));
        check(lifetime.summaryCount()==3,"deduplicate operation IDs, retaining deleted/old generations");
        equal(lifetime.summaryCredits(),"60","use current settled amount, excluding other features and holds");
        equal(lifetime.averagePdfCredits(),"20","lifetime credits average");
        equal(lifetime.averagePdfKrw(),"46","same cost conversion");
        check(PdfLibraryPanel.pdfAverageHtml(lifetime).contains("3회 생성 평균"),"show lifetime generation count");
        var subscription=SubscriptionUsage.fromWallet(current,PAID.minusSeconds(3600));
        check(subscription.summaryCount()==1,"subscription report retains purchase cutoff");
        equal(subscription.averagePdfCredits(),"30","subscription usage is independent");
        check(current.toString().equals(original),"lifetime calculation never mutates billing wallet");
        current.addProperty("planPurchasedAt",PAID.plusSeconds(3600).toString());
        equal(PdfLifetimeAverage.fromWallets(List.of(older,current)).averagePdfCredits(),"20","plan change cannot reset average");
        check(PdfLifetimeAverage.fromWallets(List.of(older,current,wallet())).summaryCount()==3,"reset wallet keeps archived history");
        equal(PdfLifetimeAverage.fromWallets(List.of(wallet())).averagePdfCredits(),"0","empty history has finite zero");

        Path home=Files.createTempDirectory("synesis-lifetime-average-");
        try {
            Path root=home.resolve("library");Files.createDirectories(root);
            Path history=home.resolve("credit-wallet-history");Files.createDirectories(history);
            Path archived=history.resolve("old.json"),latest=history.resolve("new.json");
            Files.writeString(archived,older.toString());Files.setLastModifiedTime(archived,FileTime.fromMillis(1));
            Files.writeString(latest,current.toString());Files.setLastModifiedTime(latest,FileTime.fromMillis(2));
            Path live=home.resolve("credits-wallet.json");Files.writeString(live,wallet().toString());
            String saved=Files.readString(live);
            var loaded=PdfLifetimeAverage.read(root);
            check(loaded.summaryCount()==3,"read archives even after statistics reset");
            equal(loaded.averagePdfCredits(),"20","archive snapshots are not double-counted");
            check(Files.readString(live).equals(saved),"reader does not change balance/plan/operations");
            Files.writeString(archived,"{");
            try {PdfLifetimeAverage.read(root);throw new AssertionError("corrupt history silently undercounted");}
            catch(java.io.IOException expected) { }
        } finally {
            try(var paths=Files.walk(home)) {
                for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(path);
            }
        }
        System.out.println("PdfLifetimeAverageTest passed: all-time average, plan/reset independence, deduplication, exclusions and read-only history.");
    }

    private static JsonObject wallet() {
        JsonObject result=new JsonObject();result.addProperty("version",1);
        result.addProperty("baselineCredits","0");result.addProperty("highWaterCredits","0");
        result.addProperty("planPurchasedAt",PAID.toString());result.add("purchases",new JsonArray());
        result.add("creditOperations",new JsonObject());result.add("creditHolds",new JsonObject());return result;
    }

    private static void operation(JsonObject wallet,String id,Instant at,String category,String credits) {
        JsonObject row=new JsonObject();row.addProperty("category",category);row.addProperty("credits",credits);
        row.addProperty("createdAtMs",at.toEpochMilli());row.addProperty("durationMs",60000);
        wallet.getAsJsonObject("creditOperations").add(id,row);
    }

    private static void equal(BigDecimal actual,String expected,String message) {
        check(actual.compareTo(new BigDecimal(expected))==0,message+": "+actual);
    }
    private static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
}

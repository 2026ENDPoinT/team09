package dev.synesis.poc.pdf;
import com.google.gson.*;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;
/** Known-zero fees stay distinct from missing usage and corrupt records. */
public final class PdfUsageNoChargeTest {
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static JsonObject proof(){return JsonParser.parseString("""
  {"requestId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","state":"settled","strategy":"newest-k1-2-1",
   "inputApi":"responses","requestedServiceTier":"flex","returnedServiceTier":"flex","billedServiceTier":"flex",
   "serverTerminalStatus":"failed","documentedFlexNoCharge":true,"usageUnreported":true,
   "feeEvidence":"native_resource_unavailable_flex_unavailable","estimatedUsd":0,
   "responseId":"resp_fixture","responseCacheKey":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
  """).getAsJsonObject();}
 static void write(Path folder,JsonObject request)throws Exception {
  JsonObject ledger=new JsonObject();ledger.add("requests",new JsonArray());ledger.getAsJsonArray("requests").add(request);
  Files.writeString(folder.resolve("usage/fixture.json"),ledger.toString());
 }
 public static void main(String[]args)throws Exception {
  Path temp=Files.createTempDirectory("usage-no-charge-");
  try {
   Path root=temp.resolve("library"),folder=root.resolve("a".repeat(64));Files.createDirectories(folder.resolve("usage"));Files.write(folder.resolve("source.pdf"),new byte[]{1});
   var item=new PdfLibraryStore.Item("a".repeat(64),folder.resolve("source.pdf"),"fixture",Instant.EPOCH,Instant.EPOCH);
   JsonObject valid=proof();write(folder,valid);var totals=PdfUsageStore.read(root,List.of(item));
   check(totals.unreadableFiles()==0&&totals.unknownRequests()==0&&totals.usd()==0&&totals.tokens()==0,"proven rejection readable without fake tokens");
   for(String field:List.of("documentedFlexNoCharge","usageUnreported","feeEvidence","responseId","responseCacheKey","requestId","estimatedUsd","serverTerminalStatus","strategy","inputApi","billedServiceTier","requestedServiceTier","returnedServiceTier")) {
    JsonObject bad=valid.deepCopy();bad.remove(field);check(!PdfUsageStore.documentedNoCharge(bad),"missing "+field);write(folder,bad);check(PdfUsageStore.read(root,List.of(item)).unreadableFiles()>0,"ordinary unreadable remains blocked: "+field);
   }
   for(String field:List.of("documentedFlexNoCharge","usageUnreported")){JsonObject bad=valid.deepCopy();bad.addProperty(field,"true");check(!PdfUsageStore.documentedNoCharge(bad),"string is not proof boolean");}
   JsonObject positive=valid.deepCopy();positive.addProperty("estimatedUsd",.001);check(!PdfUsageStore.documentedNoCharge(positive),"nonzero never free");
   JsonObject partial=valid.deepCopy();partial.addProperty("finalTextChars",1);check(!PdfUsageStore.documentedNoCharge(partial),"partial output never free");
   JsonObject missing=JsonParser.parseString("{\"state\":\"settled\",\"estimatedUsd\":0}").getAsJsonObject();write(folder,missing);check(PdfUsageStore.read(root,List.of(item)).unreadableFiles()>0,"plain zero is not a receipt");
   write(folder,valid);PdfUsageStore.archiveBeforeDelete(root,item);PdfLibraryStore.deleteFile(root,item.id());totals=PdfUsageStore.read(root,List.of());check(totals.unreadableFiles()==0&&totals.usd()==0,"archived rejection remains readable");
   System.out.println("PdfUsageNoChargeTest OK: known-zero, missing proof, wrong types, positive fee, partial output, ordinary corruption, deletion archive.");
  } finally {try(var paths=Files.walk(temp)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}}
 }
}

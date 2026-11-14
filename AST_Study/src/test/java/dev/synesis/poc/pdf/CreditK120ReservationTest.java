package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.math.BigDecimal;
import java.nio.file.*;

/** Restart settlement must enforce the same customer bound as the Python worker. */
public final class CreditK120ReservationTest {
    public static void main(String[] args)throws Exception {
        Path folder=Files.createTempDirectory("synesis-k120-credit-");
        try {
            Path ledger=folder.resolve("usage.json"),walletPath=folder.resolve("wallet.json");
            Files.writeString(ledger,"""
                {"operationId":"operation","requests":[
                 {"requestId":"first","state":"settled","estimatedUsd":0.2},
                 {"requestId":"second","state":"settled","estimatedUsd":0.1}]}
                """);
            JsonObject wallet=JsonParser.parseString("""
                {"liveBilling":true,"purchases":[{"credits":100}],"baselineCredits":0,
                 "highWaterCredits":0,"creditHolds":{},"creditCharges":{},"creditOperations":{}}
                """).getAsJsonObject();
            for(String id:new String[]{"first","second"}) {
                JsonObject hold=new JsonObject();
                hold.addProperty("operationId","operation");hold.addProperty("category","summary");
                hold.addProperty("ledgerPath",ledger.toString());hold.addProperty("credits",id.equals("first")?20:50);
                hold.addProperty("strategy","newest-k1-2-0");
                hold.addProperty("reservationPolicy","k120-estimate-1.3-v1");
                hold.addProperty("customerSettlementPolicy","available-balance-v1");
                hold.addProperty("reservationMultiplier",1.3);
                wallet.getAsJsonObject("creditHolds").add(id,hold);
            }
            if(!CreditReservationRecovery.reconcile(walletPath,wallet))throw new AssertionError("No reconciliation");
            JsonObject first=wallet.getAsJsonObject("creditCharges").getAsJsonObject("first");
            if(first.get("credits").getAsBigDecimal().compareTo(new BigDecimal("50"))!=0)
                throw new AssertionError("First settlement consumed the other hold: "+first);
            if(!"shared".equals(first.get("payer").getAsString())
                    || first.get("providerUsd").getAsBigDecimal().compareTo(new BigDecimal("0.2"))!=0
                    || first.get("synesisCoveredUsd").getAsBigDecimal().signum()<=0)
                throw new AssertionError("Provider/customer split missing: "+first);
            if(wallet.get("highWaterCredits").getAsBigDecimal().compareTo(new BigDecimal("100"))!=0)
                throw new AssertionError("Final customer balance must be exactly zero: "+wallet);
            String before=wallet.toString();
            if(CreditReservationRecovery.reconcile(walletPath,wallet)||!before.equals(wallet.toString()))
                throw new AssertionError("Duplicate settlement changed the wallet");
            System.out.println("CreditK120ReservationTest passed");
        } finally {
            try(var paths=Files.walk(folder)) {
                for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.deleteIfExists(path);
            }
        }
    }
}

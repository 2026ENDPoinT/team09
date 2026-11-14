package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.nio.file.*;
import java.util.concurrent.TimeUnit;

/** Offline wallet fixtures, including a real Python-owner crash; no desktop UI or API calls. */
public final class CreditReservationRecoveryTest {
    public static void main(String[] args) throws Exception {
        Path folder=Files.createTempDirectory("synesis-credit-recovery-");
        try {
            Path walletPath=folder.resolve("wallet.json"),ledger=folder.resolve("usage.json");
            JsonObject wallet=JsonParser.parseString("{\"liveBilling\":true,\"purchases\":[{\"credits\":\"100\"}],"
                +"\"baselineCredits\":0,\"highWaterCredits\":0,\"creditHolds\":{},\"creditCharges\":{},\"creditOperations\":{}}")
                .getAsJsonObject();
            JsonObject hold=new JsonObject();hold.addProperty("credits","20");hold.addProperty("operationId","operation");
            hold.addProperty("category","quiz");hold.addProperty("createdAtMs",1);hold.addProperty("ledgerPath",ledger.toString());
            wallet.getAsJsonObject("creditHolds").add("request",hold);
            require(CreditReservationRecovery.reconcile(walletPath,wallet),"orphan reservation is released");
            require(wallet.getAsJsonObject("creditHolds").isEmpty(),"orphan cannot lock spendable funds");
            require(wallet.getAsJsonObject("creditCharges").isEmpty(),"unknown is not declared free or charged");
            require(wallet.getAsJsonObject("creditPendingRequests").has("request"),"original evidence is retained");
            require(!CreditReservationRecovery.reconcile(walletPath,wallet),"replay without new usage is stable");
            Files.writeString(ledger,"{\"operationId\":\"operation\",\"requests\":[{\"requestId\":\"request\","
                +"\"state\":\"settled\",\"estimatedUsd\":0.01}]}");
            require(CreditReservationRecovery.reconcile(walletPath,wallet),"late receipt is replayed");
            BigDecimal charged=wallet.get("highWaterCredits").getAsBigDecimal();
            require(charged.signum()==0,"late confirmed usage stays SYNESIS funded");
            JsonObject sponsored=wallet.getAsJsonObject("creditCharges").getAsJsonObject("request");
            require("synesis".equals(sponsored.get("payer").getAsString()),"payer remains SYNESIS");
            require(sponsored.get("providerUsd").getAsBigDecimal().compareTo(new BigDecimal("0.01"))==0,"provider cost remains recorded");
            require(wallet.getAsJsonObject("creditPendingRequests").isEmpty(),"confirmed request leaves pending");
            require(wallet.getAsJsonObject("creditOperations").getAsJsonObject("operation").get("unknownRequests").getAsInt()==0,
                "unknown count clears after settlement");
            require(!CreditReservationRecovery.reconcile(walletPath,wallet),"settlement occurs once");
            require(wallet.get("highWaterCredits").getAsBigDecimal().compareTo(charged)==0,"no duplicate debit");

            // Exercise the exact byte-range lock shared by Python and Java, then simulate worker death.
            Path childWallet=folder.resolve("child-wallet.json");
            JsonObject empty=wallet.deepCopy();empty.add("creditHolds",new JsonObject());empty.add("creditCharges",new JsonObject());
            empty.add("creditPendingRequests",new JsonObject());empty.add("creditOperations",new JsonObject());empty.addProperty("highWaterCredits",0);
            Files.writeString(childWallet,new Gson().toJson(empty));
            String code="import sys; from pathlib import Path; from pdf_credit_billing import Billing; "
                +"Billing(Path(sys.argv[1]), 'child', 'quiz').reserve('live', .02); print('ready', flush=True); sys.stdin.read()";
            ProcessBuilder builder=new ProcessBuilder(Path.of(".venv-pdf/bin/python3").toAbsolutePath().toString(),"-c",code,childWallet.toString());
            builder.environment().put("PYTHONPATH",Path.of("scripts").toAbsolutePath().toString());
            Process child=builder.start();
            try {
                try(BufferedReader output=new BufferedReader(new InputStreamReader(child.getInputStream()))) {
                    require("ready".equals(output.readLine()),"Python lease is ready");
                    JsonObject live=JsonParser.parseString(Files.readString(childWallet)).getAsJsonObject();
                    require(!CreditReservationRecovery.reconcile(childWallet,live),"Java preserves a live Python lease");
                    child.destroy();require(child.waitFor(10,TimeUnit.SECONDS),"fixture worker exits");
                    require(CreditReservationRecovery.reconcile(childWallet,live),"Java recovers a dead Python lease");
                    require(live.getAsJsonObject("creditHolds").isEmpty(),"crash cannot leave a reservation");
                    require(live.getAsJsonObject("creditCharges").isEmpty(),"crash alone does not prove zero cost");
                }
            } finally {if(child.isAlive()){child.destroyForcibly();child.waitFor();}}
            System.out.println("Offline credit recovery fixtures passed");
        } finally {
            try(var paths=Files.walk(folder)) {
                for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.deleteIfExists(path);
            }
        }
    }
    private static void require(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
}

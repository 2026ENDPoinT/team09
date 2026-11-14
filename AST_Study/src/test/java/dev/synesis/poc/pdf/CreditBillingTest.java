package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.PythonRuntime;
import java.math.BigDecimal;
import java.nio.file.*;
import java.time.Instant;

/** Offline integration of Java purchases and Python per-call billing; no provider requests. */
public final class CreditBillingTest {
    private static void check(boolean condition,String label) {if(!condition)throw new AssertionError(label);}
    private static void near(BigDecimal actual,BigDecimal expected,String label) {
        check(actual.subtract(expected).abs().compareTo(new BigDecimal("0.000001"))<0,label+": "+actual+" != "+expected);
    }
    private static void python(Path root,String action) throws Exception {
        String code="import sys;sys.path.insert(0,'scripts');from pdf_credit_billing import Billing;"
            +"b=Billing(sys.argv[1],'python-summary','summary');"+action;
        Process process=new ProcessBuilder(PythonRuntime.pdf(),"-c",code,root.resolveSibling("credits-wallet.json").toString())
            .redirectErrorStream(true).start();String output=new String(process.getInputStream().readAllBytes());
        check(process.waitFor()==0,"Python fixture: "+output);
    }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory("synesis-credit-integration-").resolve("pdf");Files.createDirectories(root);
        ProfileUsagePeriod.save(root,Instant.EPOCH);
        CreditWallet.read(root,0);CreditWallet.topUp(root,CreditWallet.PLANS[0]);
        CreditWallet.activateBilling(root,0);
        Process contender;
        try(var channel=java.nio.channels.FileChannel.open(root.resolveSibling("credits-wallet.lock"),StandardOpenOption.WRITE);
            var lock=channel.lock(0,1,false)) {
            String code="import sys;sys.path.insert(0,'scripts');from pdf_credit_billing import Billing;print('ready',flush=True);b=Billing(sys.argv[1],'python-summary','summary');b.reserve('lock',.001);b.settle('lock',0)";
            contender=new ProcessBuilder(PythonRuntime.pdf(),"-c",code,root.resolveSibling("credits-wallet.json").toString()).redirectErrorStream(true).start();
            new java.io.BufferedReader(new java.io.InputStreamReader(contender.getInputStream())).readLine();
            Thread.sleep(150);check(contender.isAlive(),"Python waits for Java lock");
        }
        check(contender.waitFor()==0,"Python continues after Java unlock");
        String activeCode="import sys;sys.path.insert(0,'scripts');from pdf_credit_billing import Billing;"
            +"b=Billing(sys.argv[1],'python-summary','summary');b.reserve('call',.01);"
            +"print('reserved',flush=True);sys.stdin.readline();b.settle('call',.005);b.settle('call',.005)";
        Process active = new ProcessBuilder(PythonRuntime.pdf(),"-c",activeCode,
            root.resolveSibling("credits-wallet.json").toString()).redirectErrorStream(true).start();
        try(var output=active.inputReader(); var input=active.outputWriter()) {
            check("reserved".equals(output.readLine()),"Python holds the reservation lease");
            try {CreditWallet.restartStatistics(root,0,Instant.now());throw new AssertionError("active request reset");}
            catch(java.io.IOException expected) {check(expected.getMessage().contains("진행 중"),"reset reason");}
            input.write("\n");input.flush();
            check(active.waitFor()==0,"Python settles the reservation twice: "+output.readLine());
        } finally {if(active.isAlive())active.destroy();}
        near(CreditWallet.read(root,.005).balance(),new BigDecimal("2700").subtract(CreditWallet.credits(.005)),"single debit");
        // Aggregate display reads must not bill an already directly charged request again.
        near(CreditWallet.read(root,.8).balance(),new BigDecimal("2700").subtract(CreditWallet.credits(.005)),"no aggregate double charge");
        String report=SubscriptionUsage.report(root);
        check(report.contains("AI 요약/개념 생성</h3>1회"),"summary count");
        // Simulate a settled ledger durable before process death; the outstanding hold is reconciled once.
        Path ledger=root.resolve("fixture/usage/crash.json");Files.createDirectories(ledger.getParent());
        Files.writeString(ledger,"{\"operationId\":\"python-summary\",\"requests\":[{\"requestId\":\"crash\",\"state\":\"settled\",\"estimatedUsd\":0.001}]}");
        JsonObject wallet=CreditWallet.usageData(root);
        JsonObject hold=new JsonObject();hold.addProperty("credits",10);hold.addProperty("operationId","python-summary");hold.addProperty("ledgerPath",ledger.toString());
        wallet.getAsJsonObject("creditHolds").add("crash",hold);
        Files.writeString(root.resolveSibling("credits-wallet.json"),wallet.toString());
        CreditWallet.activateBilling(root,0);CreditWallet.activateBilling(root,0);
        near(CreditWallet.read(root,0).balance(),new BigDecimal("2700").subtract(CreditWallet.credits(.006)),"crash reconciliation once");
        Files.delete(ledger);
        check(SubscriptionUsage.report(root).contains("AI 요약/개념 생성</h3>1회"),"usage survives deleted document ledger");
        CreditWallet.restartStatistics(root,0,Instant.now());
        var reset=CreditWallet.read(root,0);
        check(reset.balance().signum()==0 && reset.activePlan().equals("플랜 없음"),"reset wallet and plan");
        check(SubscriptionUsage.report(root).contains("AI 요약/개념 생성</h3>0회"),"reset usage");
        CreditWallet.topUp(root,CreditWallet.PLANS[0]);check(CreditWallet.read(root,0).balance().intValueExact()==2700,"re-subscribe");
        System.out.println("CreditBillingTest OK: Java/Python debit, idempotency, crash recovery, deletion, reset and purchase.");
    }
}

package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.file.*;
import java.time.Instant;
import java.util.UUID;

/** Local developer wallet. All purchases are simulations; this is not payment authorization. */
final class CreditWallet {
    // Fixed internal cost conversion, independent of the credit retail price.
    static final BigDecimal COST_KRW_PER_CREDIT = new BigDecimal("2.3");
    static final BigDecimal CREDITS_PER_USD = new BigDecimal("1400")
        .divide(COST_KRW_PER_CREDIT,20,RoundingMode.HALF_UP);
    record Plan(String name,int won,int credits) {}
    static final Plan[] PLANS = {
        new Plan("Standard",9900,2700),new Plan("Pro",19900,6000),new Plan("Extra Pro",29900,10000)
    };
    record Snapshot(BigDecimal balance,BigDecimal usedSinceStart,BigDecimal purchased,
                    String activePlan,Instant planExpiresAt,Instant planPurchasedAt,boolean autoRenew) {
        boolean hasActivePlan() {return planExpiresAt!=null && planExpiresAt.isAfter(Instant.now());}
    }
    static BigDecimal credits(double usd) {
        if(!Double.isFinite(usd) || usd<0)throw new IllegalArgumentException("사용량 금액이 올바르지 않아요.");
        return BigDecimal.valueOf(usd).multiply(CREDITS_PER_USD);
    }
    static String display(BigDecimal credits) { return String.format(java.util.Locale.KOREA,"%,.2f",credits); }
    static String displayHtml(BigDecimal credits) {
        return displayHtml(credits,23);
    }
    static String displayHtml(BigDecimal credits,int fontSize) {
        String formatted=display(credits);
        int decimal=formatted.lastIndexOf('.');
        return "<html>"+formatted.substring(0,decimal)
            +"<span style='font-size:"+Math.round(fontSize*.6f)+"pt;color:#6d7785'>"+formatted.substring(decimal)+"</span>"
            +"<span style='font-size:"+Math.round(fontSize*.7f)+"pt;color:#6d7785'> 크레딧</span></html>";
    }

    private static String planName(String name) {
        return switch(name) {
            case "스탠다드" -> "Standard";
            case "프로" -> "Pro";
            case "엑스트라", "엑스트라 프로" -> "Extra Pro";
            default -> name;
        };
    }

    private interface IoWork<T> {T run() throws IOException;}
    private static final ThreadLocal<Boolean> LOCKED=ThreadLocal.withInitial(()->false);
    private static <T> T locked(Path root,IoWork<T> work) throws IOException {
        if(LOCKED.get())return work.run();
        Path lock=file(root).resolveSibling("credits-wallet.lock");Files.createDirectories(lock.getParent());
        try(var channel=java.nio.channels.FileChannel.open(lock,StandardOpenOption.CREATE,StandardOpenOption.WRITE);
            var ignored=channel.lock(0,1,false)) {
            LOCKED.set(true);try{return work.run();}finally{LOCKED.remove();}
        }
    }

    private static Path file(Path root) { return dev.synesis.poc.AppPaths.accountForLibrary(root).resolve("credits-wallet.json"); }

    static synchronized Snapshot read(Path root,double totalUsd) throws IOException {
        return locked(root,()->readUnlocked(root,totalUsd));
    }
    /** Read-only assistant projection; never migrates, reconciles or creates a wallet. */
    static synchronized Snapshot peek(Path root) throws IOException {
        return locked(root,()->snapshot(load(file(root))));
    }
    private static Snapshot readUnlocked(Path root,double totalUsd) throws IOException {
        Path path=file(root);
        BigDecimal total=credits(totalUsd);
        JsonObject wallet;
        boolean changed=false;
        if(!Files.exists(path)) {
            wallet=new JsonObject();
            wallet.addProperty("version",1);
            wallet.addProperty("mode","developer_simulated");
            wallet.addProperty("baselineCredits",total);
            wallet.addProperty("highWaterCredits",total);
            wallet.add("purchases",new JsonArray());
            changed=true;
        } else wallet=load(path);
        if(wallet.has("planExpiresAt") && !wallet.has("autoRenew")) {
            wallet.addProperty("autoRenew",true);changed=true;
        }
        if(!wallet.has("planPurchasedAt")) {
            Instant original=snapshot(wallet).planPurchasedAt();
            if(original!=null) {wallet.addProperty("planPurchasedAt",original.toString());changed=true;}
        }
        // Repair wallets reset by the earlier developer button that retained plan fields.
        if(wallet.has("balanceResetAt") && wallet.has("planExpiresAt")) {
            Instant resetAt=Instant.parse(wallet.get("balanceResetAt").getAsString());
            Instant paidAt=snapshot(wallet).planPurchasedAt();
            if(paidAt==null || !paidAt.isAfter(resetAt)) {clearPlan(wallet);changed=true;}
        }
        if(!wallet.has("liveBilling") && total.compareTo(wallet.get("highWaterCredits").getAsBigDecimal())>0) {
            wallet.addProperty("highWaterCredits",total);changed=true;
        }
        if(wallet.has("liveBilling")&&CreditReservationRecovery.reconcile(path,wallet))changed=true;
        if(changed)save(path,wallet);
        return snapshot(wallet);
    }

    /** Restart developer statistics, balance and membership while retaining purchase history. */
    static synchronized void restartStatistics(Path root,double previousUsd,Instant since) throws IOException {
        locked(root,()->{restartStatisticsUnlocked(root,previousUsd,since);return null;});
    }
    private static void restartStatisticsUnlocked(Path root,double previousUsd,Instant since) throws IOException {
        Snapshot current=read(root,previousUsd);
        Path path=file(root);
        JsonObject previous=load(path);
        JsonObject wallet=previous.deepCopy();
        if(wallet.has("creditHolds"))for(var hold:wallet.getAsJsonObject("creditHolds").entrySet())
            if(!hold.getValue().getAsJsonObject().has("unknown"))
                throw new IOException("유료 호출이 진행 중이에요. 완료된 뒤 초기화해 주세요.");
        Path history=path.resolveSibling("credit-wallet-history");Files.createDirectories(history);
        Files.copy(path,history.resolve(UUID.randomUUID()+".json"));
        wallet.addProperty("baselineCredits",BigDecimal.ZERO);
        wallet.addProperty("balanceAdjustmentCredits",current.purchased().negate());
        wallet.addProperty("balanceResetAt",since.toString());
        wallet.addProperty("highWaterCredits",BigDecimal.ZERO);
        clearPlan(wallet);
        wallet.add("creditOperations",new JsonObject());wallet.add("creditCharges",new JsonObject());
        wallet.add("creditHolds",new JsonObject());wallet.add("creditPendingRequests",new JsonObject());
        save(path,wallet);
        try {ProfileUsagePeriod.save(root,since);}
        catch(IOException failure) {
            try {save(path,previous);} catch(IOException rollback) {failure.addSuppressed(rollback);}
            throw failure;
        }
    }

    static synchronized void activateBilling(Path root,double previousUsd) throws IOException {
        locked(root,()->{
            read(root,previousUsd);
            JsonObject wallet=load(file(root));
            if(!wallet.has("liveBilling")) {
                wallet.addProperty("liveBilling",true);
                wallet.add("creditOperations",SubscriptionUsage.legacyOperations(root));
                wallet.add("creditCharges",new JsonObject());wallet.add("creditHolds",new JsonObject());
                save(file(root),wallet);
            }
            if(reconcileSettledHolds(root,wallet))save(file(root),wallet);
            return null;
        });
    }

    static synchronized void recoverReservations(Path root) throws IOException {
        locked(root,()->{
            if(!Files.isRegularFile(file(root)))return null;
            JsonObject wallet=load(file(root));
            if(wallet.has("liveBilling")&&CreditReservationRecovery.reconcile(file(root),wallet))save(file(root),wallet);
            return null;
        });
    }

    private static boolean reconcileSettledHolds(Path root,JsonObject wallet) throws IOException {
        return CreditReservationRecovery.reconcile(file(root),wallet);
    }

    static synchronized JsonObject usageData(Path root) throws IOException {
        return locked(root,()->load(file(root)).deepCopy());
    }

    private static void clearPlan(JsonObject wallet) {
        wallet.remove("activePlan");
        wallet.remove("planPurchasedAt");
        wallet.remove("planExpiresAt");
        wallet.addProperty("autoRenew",false);
    }

    static synchronized Snapshot reset(Path root,double currentUsd) throws IOException {
        return locked(root,()->resetUnlocked(root,currentUsd));
    }
    private static Snapshot resetUnlocked(Path root,double currentUsd) throws IOException {
        Path path=file(root);
        if(Files.exists(path)) {
            Path history=path.resolveSibling("credit-wallet-history");Files.createDirectories(history);
            Files.copy(path,history.resolve(UUID.randomUUID()+".json"));
        }
        JsonObject wallet=new JsonObject();wallet.addProperty("version",1);
        wallet.addProperty("mode","developer_simulated");
        wallet.addProperty("baselineCredits",credits(currentUsd));
        wallet.addProperty("highWaterCredits",credits(currentUsd));
        wallet.add("purchases",new JsonArray());wallet.addProperty("autoRenew",false);
        wallet.addProperty("resetAt",Instant.now().toString());save(path,wallet);
        return snapshot(wallet);
    }

    static synchronized Snapshot topUp(Path root,Plan plan) throws IOException {
        return locked(root,()->topUpUnlocked(root,plan));
    }
    private static Snapshot topUpUnlocked(Path root,Plan plan) throws IOException {
        if(java.util.Arrays.stream(PLANS).noneMatch(plan::equals))throw new IOException("충전 상품을 확인해 주세요.");
        Path path=file(root);JsonObject wallet=load(path);
        JsonObject purchase=new JsonObject();
        purchase.addProperty("id",UUID.randomUUID().toString());
        Instant purchasedAt=Instant.now();
        purchase.addProperty("createdAt",purchasedAt.toString());
        purchase.addProperty("plan",plan.name());purchase.addProperty("won",plan.won());
        purchase.addProperty("credits",plan.credits());purchase.addProperty("simulated",true);
        wallet.getAsJsonArray("purchases").add(purchase);
        wallet.addProperty("activePlan",plan.name());
        wallet.addProperty("planPurchasedAt",purchasedAt.toString());
        wallet.addProperty("planExpiresAt",purchasedAt.plus(java.time.Duration.ofDays(30)).toString());
        wallet.addProperty("autoRenew",true);
        save(path,wallet);
        return snapshot(wallet);
    }

    static synchronized Snapshot purchaseCredits(Path root,int amount,BigDecimal wonPerCredit) throws IOException {
        return locked(root,()->purchaseCreditsUnlocked(root,amount,wonPerCredit));
    }
    private static Snapshot purchaseCreditsUnlocked(Path root,int amount,BigDecimal wonPerCredit) throws IOException {
        Path path=file(root);JsonObject wallet=load(path);
        Snapshot current=snapshot(wallet);
        int minimum=current.hasActivePlan()?0:1000;
        if(amount<=0 || amount<minimum || wonPerCredit.signum()<=0)
            throw new IOException("구매할 크레딧 수량을 확인해 주세요.");
        JsonObject purchase=new JsonObject();
        purchase.addProperty("id",UUID.randomUUID().toString());
        purchase.addProperty("createdAt",Instant.now().toString());
        purchase.addProperty("plan","크레딧 별도 구매");
        purchase.addProperty("credits",amount);
        purchase.addProperty("won",wonPerCredit.multiply(BigDecimal.valueOf(amount)).setScale(0,RoundingMode.CEILING));
        purchase.addProperty("simulated",true);
        wallet.getAsJsonArray("purchases").add(purchase);
        save(path,wallet);return snapshot(wallet);
    }

    private static Snapshot snapshot(JsonObject wallet) {
        BigDecimal purchased=BigDecimal.ZERO;
        for(JsonElement entry:wallet.getAsJsonArray("purchases"))
            purchased=purchased.add(entry.getAsJsonObject().get("credits").getAsBigDecimal());
        BigDecimal used=wallet.get("highWaterCredits").getAsBigDecimal()
            .subtract(wallet.get("baselineCredits").getAsBigDecimal()).max(BigDecimal.ZERO);
        // Developer mode permits overdraft; keep the signed balance so usage never disappears.
        Instant expiry=wallet.has("planExpiresAt")?Instant.parse(wallet.get("planExpiresAt").getAsString()):null;
        Instant paidAt=wallet.has("planPurchasedAt")?Instant.parse(wallet.get("planPurchasedAt").getAsString()):null;
        // Existing developer purchases already contain a timestamp; keep their original date.
        if(paidAt==null && expiry!=null) {
            String plan=wallet.has("activePlan")?wallet.get("activePlan").getAsString():"";
            for(JsonElement entry:wallet.getAsJsonArray("purchases")) {
                JsonObject purchase=entry.getAsJsonObject();
                if(purchase.has("plan") && plan.equals(purchase.get("plan").getAsString()) && purchase.has("createdAt"))
                    paidAt=Instant.parse(purchase.get("createdAt").getAsString());
            }
        }
        BigDecimal adjustment=wallet.has("balanceAdjustmentCredits")
            ?wallet.get("balanceAdjustmentCredits").getAsBigDecimal():BigDecimal.ZERO;
        return new Snapshot(purchased.subtract(used).add(adjustment),used,purchased,
            wallet.has("activePlan")?planName(wallet.get("activePlan").getAsString()):"플랜 없음",expiry,paidAt,
            wallet.has("autoRenew") && wallet.get("autoRenew").getAsBoolean());
    }

    private static JsonObject load(Path path) throws IOException {
        try {
            JsonObject wallet=JsonParser.parseString(Files.readString(path)).getAsJsonObject();
            if(wallet.get("version").getAsInt()!=1 || !wallet.has("baselineCredits")
                || !wallet.has("highWaterCredits") || !wallet.get("purchases").isJsonArray())
                throw new IllegalArgumentException("invalid wallet");
            snapshot(wallet);
            return wallet;
        } catch(RuntimeException failure) { throw new IOException("크레딧 지갑 기록을 읽지 못했어요.",failure); }
    }

    private static void save(Path path,JsonObject wallet) throws IOException {
        Files.createDirectories(path.getParent());
        Path temp=Files.createTempFile(path.getParent(),"credits-wallet-",".tmp");
        try {
            Files.writeString(temp,new GsonBuilder().setPrettyPrinting().create().toJson(wallet));
            try {Files.move(temp,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);}
            catch(AtomicMoveNotSupportedException ignored) {Files.move(temp,path,StandardCopyOption.REPLACE_EXISTING);}
        } finally {Files.deleteIfExists(temp);}
    }
}

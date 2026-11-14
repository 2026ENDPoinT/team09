package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.AppPaths;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.channels.FileChannel;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.*;
import java.util.*;

/** Offline counterpart of credit_reservations.py; callers hold the shared wallet lock. */
final class CreditReservationRecovery {
    private CreditReservationRecovery() {}

    static boolean reconcile(Path walletPath, JsonObject wallet) {
        boolean changed=false;
        Map<Path,JsonObject> ledgers=new HashMap<>();
        for(String collection:List.of("creditHolds","creditPendingRequests")) {
            JsonObject records=object(wallet,collection);
            if(records==null)continue;
            for(String id:new ArrayList<>(records.keySet())) {
                JsonObject record=object(records,id);
                if(record==null||text(record,"operationId").isEmpty())continue;
                JsonObject request=request(walletPath,record,id,ledgers);
                BigDecimal confirmed=confirmedUsage(request);
                if(object(wallet,"creditCharges")!=null&&object(wallet,"creditCharges").has(id)) {
                    settle(wallet,id,record,BigDecimal.ZERO);changed=true;
                } else if(confirmed!=null) {
                    settle(wallet,id,record,confirmed);changed=true;
                } else if(collection.equals("creditHolds")&&(flag(record,"unknown")||!ownerAlive(walletPath,record))) {
                    JsonObject pending=ensure(wallet,"creditPendingRequests");
                    if(!pending.has(id)) {
                        JsonObject retained=record.deepCopy();
                        if(!flag(record,"unknown")) {
                            JsonObject operation=operation(wallet,record);
                            operation.addProperty("unknownRequests",integer(operation,"unknownRequests")+1);
                        }
                        retained.addProperty("unknown",true);
                        retained.addProperty("payer","synesis");
                        retained.addProperty("customerChargeUsd","0");
                        retained.addProperty("reservationReleasedAtMs",System.currentTimeMillis());
                        retained.addProperty("reservationReleaseReason",flag(record,"unknown")?"usage_unconfirmed":"owner_stopped");
                        pending.add(id,retained);
                    }
                    records.remove(id);changed=true;
                }
            }
        }
        return changed;
    }

    private static BigDecimal confirmedUsage(JsonObject request) {
        if(request==null)return null;
        if("not_sent".equals(text(request,"state")))return BigDecimal.ZERO;
        if("settled".equals(text(request,"state")))try {
            BigDecimal usd=request.get("estimatedUsd").getAsBigDecimal();
            if(usd.signum()>=0)return usd;
        } catch(RuntimeException ignored) { /* Invalid amounts cannot become confirmed charges. */ }
        return null;
    }

    private static JsonObject request(Path walletPath,JsonObject record,String id,Map<Path,JsonObject> ledgers) {
        String reference=text(record,"ledgerPath");if(reference.isEmpty())return null;
        try {
            Path path=AppPaths.stored(reference,walletPath);
            if(!ledgers.containsKey(path))ledgers.put(path,JsonParser.parseString(Files.readString(path)).getAsJsonObject());
            JsonObject ledger=ledgers.get(path);
            if(!text(record,"operationId").equals(text(ledger,"operationId")))return null;
            JsonArray requests=ledger.getAsJsonArray("requests");if(requests==null)return null;
            for(JsonElement value:requests)if(value.isJsonObject()&&id.equals(text(value.getAsJsonObject(),"requestId")))
                return value.getAsJsonObject();
        } catch(IOException|RuntimeException ignored) { /* A missing ledger does not prove that a sent request was free. */ }
        return null;
    }

    private static boolean ownerAlive(Path walletPath,JsonObject record) {
        String owner=text(record,"ownerId");if(!owner.matches("[a-f0-9]{32}"))return false;
        Path lease=walletPath.getParent().resolve("credit-owners").resolve(owner+".lock");
        try(FileChannel channel=FileChannel.open(lease,StandardOpenOption.READ,StandardOpenOption.WRITE)) {
            try(var lock=channel.tryLock(0,1,false)) {return lock==null;}
        } catch(NoSuchFileException ignored) {return false;}
        catch(OverlappingFileLockException ignored) {return true;}
        catch(IOException ignored) {return true;}
    }

    private static void settle(JsonObject wallet,String id,JsonObject record,BigDecimal usd) {
        JsonObject holds=ensure(wallet,"creditHolds"),pending=ensure(wallet,"creditPendingRequests");
        JsonObject old=object(pending,id);if(old==null)old=object(holds,id);
        pending.remove(id);holds.remove(id);
        JsonObject operation=operation(wallet,record);
        if(old!=null&&flag(old,"unknown"))operation.addProperty("unknownRequests",Math.max(0,integer(operation,"unknownRequests")-1));
        JsonObject charges=ensure(wallet,"creditCharges");if(charges.has(id))return;
        boolean sponsored=(old!=null&&flag(old,"unknown"))||flag(record,"unknown")||"synesis".equals(text(record,"payer"));
        JsonObject policy=old==null?record:old;
        boolean bounded=java.util.Set.of("newest-k1-2-0","newest-k1-2-1","newest-k1-2-2","newest-k1-2-3","newest-k1-2-4","newest-k1-2-5").contains(text(policy,"strategy"))
            && "k120-estimate-1.3-v1".equals(text(policy,"reservationPolicy"))
            && "available-balance-v1".equals(text(policy,"customerSettlementPolicy"));
        BigDecimal customerUsd=sponsored?BigDecimal.ZERO:usd;
        BigDecimal credits=customerUsd.multiply(CreditWallet.CREDITS_PER_USD);
        if(bounded&&!sponsored) {
            // Own hold is released; all other holds remain protected. A local
            // prediction miss is SYNESIS cost, never a negative customer balance.
            BigDecimal spendable=available(wallet).max(BigDecimal.ZERO);
            if(credits.compareTo(spendable)>0) {
                credits=spendable;
                customerUsd=credits.divide(CreditWallet.CREDITS_PER_USD,24,RoundingMode.DOWN);
            }
        }
        wallet.addProperty("highWaterCredits",wallet.get("highWaterCredits").getAsBigDecimal().add(credits));
        operation.addProperty("credits",operation.get("credits").getAsBigDecimal().add(credits));
        JsonObject charge=new JsonObject();charge.addProperty("usd",customerUsd);charge.addProperty("credits",credits);
        charge.addProperty("providerUsd",usd);charge.addProperty("payer",sponsored?"synesis":"customer");
        if(bounded) {
            for(String key:List.of("strategy","reservationPolicy","customerSettlementPolicy","userEstimatedUsd",
                    "customerReservedUsd","reservationMultiplier","providerUpperBoundUsd","reservationEstimateBasis",
                    "reservationEstimateSamples","reservationInputTokens","reservationOutputTokens"))
                if(policy.has(key))charge.add(key,policy.get(key).deepCopy());
            BigDecimal covered=usd.subtract(customerUsd).max(BigDecimal.ZERO);
            charge.addProperty("customerChargeUsd",customerUsd);charge.addProperty("synesisCoveredUsd",covered);
            charge.addProperty("payer",customerUsd.signum()==0&&usd.signum()>0?"synesis":covered.signum()>0?"shared":"customer");
        }
        charge.addProperty("operationId",text(record,"operationId"));charges.add(id,charge);
    }

    private static BigDecimal available(JsonObject wallet) {
        BigDecimal purchased=BigDecimal.ZERO;
        if(wallet.has("purchases")&&wallet.get("purchases").isJsonArray())
            for(JsonElement value:wallet.getAsJsonArray("purchases"))if(value.isJsonObject())
                purchased=purchased.add(amount(value.getAsJsonObject(),"credits"));
        BigDecimal used=amount(wallet,"highWaterCredits").subtract(amount(wallet,"baselineCredits")).max(BigDecimal.ZERO);
        BigDecimal available=purchased.subtract(used).add(amount(wallet,"balanceAdjustmentCredits"));
        JsonObject holds=object(wallet,"creditHolds");
        if(holds!=null)for(JsonElement value:holds.asMap().values())if(value.isJsonObject())
            available=available.subtract(amount(value.getAsJsonObject(),"credits"));
        return available;
    }

    private static BigDecimal amount(JsonObject value,String key) {
        return value.has(key)?value.get(key).getAsBigDecimal():BigDecimal.ZERO;
    }

    private static JsonObject operation(JsonObject wallet,JsonObject record) {
        JsonObject operations=ensure(wallet,"creditOperations");String id=text(record,"operationId");
        JsonObject operation=object(operations,id);
        if(operation==null) {
            operation=new JsonObject();operation.addProperty("category",text(record,"category").isEmpty()?"analysis":text(record,"category"));
            operation.add("createdAtMs",record.has("operationCreatedAtMs")?record.get("operationCreatedAtMs"):
                record.has("createdAtMs")?record.get("createdAtMs"):new JsonPrimitive(0));
            operation.addProperty("credits",BigDecimal.ZERO);operation.addProperty("unknownRequests",0);operations.add(id,operation);
        }
        return operation;
    }

    private static JsonObject object(JsonObject parent,String key) {
        return parent.has(key)&&parent.get(key).isJsonObject()?parent.getAsJsonObject(key):null;
    }
    private static JsonObject ensure(JsonObject parent,String key) {
        JsonObject value=object(parent,key);if(value==null){value=new JsonObject();parent.add(key,value);}return value;
    }
    private static String text(JsonObject object,String key) {
        return object.has(key)&&!object.get(key).isJsonNull()?object.get(key).getAsString():"";
    }
    private static boolean flag(JsonObject object,String key) {return object.has(key)&&object.get(key).getAsBoolean();}
    private static int integer(JsonObject object,String key) {return object.has(key)?object.get(key).getAsInt():0;}
}

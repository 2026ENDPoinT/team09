package dev.synesis.poc.pdf;
public final class AssistantDeliveryTest {
    public static void main(String[] args){
        long at=java.time.LocalDateTime.of(2026,10,25,17,18)
                .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
        long[] elapsed={-1,0,59999,60000,120000,299999,300000,900000,
                3_599_999,3_600_000,82_799_999,82_800_000,86_400_000,172_800_000};
        String[] expected={"방금 읽음","방금 읽음","방금 읽음","1분전 읽음","2분전 읽음",
                "4분전 읽음","5분전 읽음","15분전 읽음","59분전 읽음","1시간 전 읽음",
                "22시간 전 읽음","읽음: 2026. 10. 25.","읽음: 2026. 10. 25.","읽음: 2026. 10. 25."};
        if(!AssistantDelivery.label(0,at).equals("전송됨"))throw new AssertionError();
        for(int i=0;i<elapsed.length;i++)if(!AssistantDelivery.label(at,at+elapsed[i]).equals(expected[i]))throw new AssertionError("boundary "+elapsed[i]);
        System.out.println("AssistantDeliveryTest OK");
    }
}

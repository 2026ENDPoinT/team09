package dev.synesis.poc.pdf;

import com.google.gson.*;
import dev.synesis.poc.planner.PlannerStore;
import java.nio.file.*;

/** Offline operation-state regression; no user files, windows or provider calls. */
public final class AssistantFailureStateTest {
    public static void main(String[] args)throws Exception{
        Path root=Files.createTempDirectory("assistant-operation-state-");
        AssistantLocal local=new AssistantLocal(new PlannerStore(root.resolve("planner.json")),root.resolve("preferences.json"),JsonObject::new);
        local.begin("s","chat","안녕하세요");
        check(local.failureNotice().isEmpty(),"ordinary failure should not imply writes");
        JsonObject request=JsonParser.parseString("{\"id\":\"bad\",\"tool\":\"memory.update\",\"arguments\":{},\"authorizationQuote\":\"\"}").getAsJsonObject();
        local.handle(request);
        check(local.failureNotice().isEmpty(),"denied action should not imply uncertain writes");
        local.begin("s","preference","답변 길이를 짧게 바꿔줘");AssistantLocalTest.authorize(local,"답변 길이를 짧게 바꿔줘","memory");
        request=JsonParser.parseString("{\"id\":\"save\",\"tool\":\"memory.update\",\"arguments\":{\"expectedRevision\":0,\"set\":{\"responseLength\":\"concise\"},\"remove\":[]},\"authorizationQuote\":\"답변 길이를 짧게 바꿔줘\"}").getAsJsonObject();
        check(local.handle(request).get("ok").getAsBoolean(),"explicit preference request should save");
        check(local.failureNotice().equals("저장된 변경은 유지돼요."),"confirmed save must not be described as uncertain");
        for(String requestText:new String[]{"호칭을 새 이름으로 부르자","어조를 차분하게 바꿔줘","응답을 간결하게 해줘","언어를 영어로 사용해줘"})
            check(AssistantLocal.preferenceRequest(requestText),"preference domain/request not recognized: "+requestText);
        for(String inquiry:new String[]{"호칭을 바꿨어?","응답 방식이 어떤 뜻이야?","언어 설정을 확인했어?"})
            check(!AssistantLocal.preferenceRequest(inquiry),"status question misread as change: "+inquiry);
        local.begin("s","query","메모리에 저장된 내용을 확인해줘");
        check(local.failureNotice().isEmpty(),"previous turn must not cause a new write warning");
        try(var paths=Files.walk(root)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList())Files.deleteIfExists(path);}
        System.out.println("AssistantFailureStateTest OK: no write, denied, confirmed save, next-turn reset");
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}

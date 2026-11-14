package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;

/** Real Java↔Python JSONL roundtrip, but the child is a tiny offline fixture. */
public final class AssistantTransportTest {
    public static void main(String[] args)throws Exception{
        Path project=Path.of("").toAbsolutePath(),temp=Files.createTempDirectory("assistant-rpc-");
        Files.createDirectories(temp.resolve("scripts"));Files.createSymbolicLink(temp.resolve(".venv-pdf"),project.resolve(".venv-pdf"));
        Files.writeString(temp.resolve("scripts/pdf_pipeline.py"),"# resource-root marker\n");
        Files.writeString(temp.resolve("scripts/home_assistant.py"),"""
import json,sys
print(json.dumps({'type':'assistant_local_request','id':'17','tool':'profile.get','arguments':{},'authorizationQuote':''}),flush=True)
reply=json.loads(sys.stdin.readline())
assert reply['id']=='17' and reply['ok'] and reply['data']['readOnly']
print(json.dumps({'type':'assistant_stage','stage':'continuing'}),flush=True)
print(json.dumps({'type':'assistant_delta','text':'로컬 결과를 확인했어요.'}),flush=True)
""");
        String old=System.getProperty("synesis.appRoot");System.setProperty("synesis.appRoot",temp.toString());
        List<JsonObject> events=new ArrayList<>();int[] requests={0};
        try(PdfProcess process=new PdfProcess()){
            process.run("home_assistant.py",List.of(),process.ticket(),events::add,request->{requests[0]++;JsonObject reply=new JsonObject();reply.add("id",request.get("id"));reply.addProperty("ok",true);JsonObject data=new JsonObject();data.addProperty("readOnly",true);reply.add("data",data);return reply;});
            if(requests[0]!=1||events.size()!=2||!events.get(1).get("text").getAsString().contains("로컬 결과"))throw new AssertionError("RPC/result routing");
        }finally{if(old==null)System.clearProperty("synesis.appRoot");else System.setProperty("synesis.appRoot",old);try(var paths=Files.walk(temp)){for(Path path:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}}
        System.out.println("AssistantTransportTest OK · actual subprocess request, reply and final event roundtrip");
    }
}

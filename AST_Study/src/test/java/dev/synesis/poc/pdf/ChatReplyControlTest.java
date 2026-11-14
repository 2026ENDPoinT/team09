package dev.synesis.poc.pdf;

import java.nio.file.*;
import java.io.*;
import java.util.concurrent.TimeUnit;

/** Real isolated workers and signals; no app process or provider request. */
public final class ChatReplyControlTest {
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        Path root=Files.createTempDirectory("chat-cancel-");
        ChatReplyControl early=new ChatReplyControl();early.cancel();
        try{early.prepare(root.resolve("early.json"));throw new AssertionError("started cancelled reply");}catch(ChatReplyControl.Cancelled expected){}
        for(boolean sealed:new boolean[]{false,true}){
            Path result=root.resolve(sealed?"complete.json":"cancel.json");
            ChatReplyControl reply=new ChatReplyControl();reply.prepare(result);
            String program="import sys,time;sys.path.insert(0,'scripts');import pdf_chat_cancel as c;c.start();"+
                (sealed?"c.seal();":"")+"print('ready',flush=True);time.sleep(.3);open(sys.argv[1],'w').write('{}')";
            Process worker=new ProcessBuilder(".venv-pdf/bin/python","-c",program,result.toString()).redirectError(ProcessBuilder.Redirect.DISCARD).start();
            try(BufferedReader output=worker.inputReader()){
                check("ready".equals(output.readLine()),"worker not ready");reply.attach(worker);reply.cancel();
                check(worker.waitFor(5,TimeUnit.SECONDS),"worker did not settle");
                if(sealed){check(reply.completed(),"late cancel discarded answer");reply.check();}
                else {check(!Files.exists(result),"cancelled worker continued");try{reply.check();throw new AssertionError("missing cancellation");}catch(ChatReplyControl.Cancelled expected){}}
            }finally{reply.detach();if(worker.isAlive())worker.destroyForcibly();}
        }
        ChatReplyControl published=new ChatReplyControl();Path result=root.resolve("published.json");published.prepare(result);Files.writeString(result,"{}");published.cancel();published.check();
        check(published.cancelled()&&published.completed(),"published result must win and finish presentation");
        System.out.println("ChatReplyControlTest OK · early stop, active stop, sealed completion, published completion");
    }
}

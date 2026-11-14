package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.lang.reflect.*;
import java.nio.file.*;
import javax.swing.*;

/** Offline progress ordering, cancellation and display-only history persistence. */
public final class AssistantActivityTest {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static Object get(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    static void set(Object target,String name,Object value)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    static Object call(Object target,String name,Class<?>[] types,Object...args)throws Exception{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,args);}
    static JsonObject update(int id,String phase,String text){JsonObject r=new JsonObject();r.addProperty("id",id);r.addProperty("phase",phase);r.addProperty("text",text);r.addProperty("timestampMs",1000+id);return r;}
    static void checkReplyEntrance(boolean fast)throws Exception{
        HomeAssistant[] home={null};
        JComponent[] answer={null};
        try{
            SwingUtilities.invokeAndWait(()->{
                home[0]=new HomeAssistant();
                try{
                    ChatReplyControl reply=new ChatReplyControl();
                    set(home[0],"busy",true);
                    set(home[0],"replyControl",reply);
                    Object user=call(home[0],"addBubble",new Class[]{String.class,boolean.class},"안녕",true);
                    Object bubble=call(home[0],"addBubble",new Class[]{String.class,boolean.class},"",false);
                    answer[0]=(JComponent)bubble;
                    set(home[0],"answerBubble",bubble);
                    call(bubble,"thinking",new Class[]{});
                    call(home[0],"startSendEntrance",new Class[]{user.getClass(),bubble.getClass()},user,bubble);
                    check(!answer[0].isVisible(),"preparing bubble shown before upload");
                    call(home[0],"uploaded",new Class[]{ChatReplyControl.class,user.getClass(),long.class},reply,user,System.currentTimeMillis());
                    check("방금 읽음".equals(((JLabel)get(user,"delivery")).getText()),"upload receipt did not update the user message");
                    check(!answer[0].isVisible(),"receipt and preparing bubble appeared together");
                    if(fast){
                        call(home[0],"displayReplyText",new Class[]{ChatReplyControl.class,String.class},reply,"안녕하세요.");
                        String shown=(String)get(bubble,"shown");
                        check(answer[0].isVisible()&&!shown.isBlank()&&"안녕하세요.".startsWith(shown),
                                "fast response displayed a placeholder first");
                        check(get(home[0],"preparingBubbleTimer")==null,"fast response did not cancel the pending placeholder");
                    }
                }catch(Exception failure){throw new RuntimeException(failure);}
            });
            if(!fast){
                Thread.sleep(650);
                SwingUtilities.invokeAndWait(()->check(answer[0].isVisible(),"slow response never showed the preparing bubble"));
            }
        }finally{
            if(home[0]!=null)SwingUtilities.invokeAndWait(home[0]::close);
        }
    }
    public static void main(String[]args)throws Exception{
        Path data=Files.createTempDirectory("assistant-activity-");System.setProperty("synesis.dataRoot",data.toString());
        checkReplyEntrance(true);
        checkReplyEntrance(false);
        AssistantActivityLog log=new AssistantActivityLog();JsonObject plan=update(1,"plan","파일을 확인할게요."),done=update(2,"result","파일 3개를 옮겼어요.");
        check(log.accept(plan)!=null&&log.accept(done)!=null,"valid updates lost");
        check(log.accept(plan)==null,"duplicate progress repeated");
        check(log.accept(update(3,"untrusted","hidden"))==null,"unknown phase accepted");
        JsonArray copy=log.snapshot();copy.remove(0);check(log.snapshot().size()==2,"mutable history leaked");
        check(log.remainingAnswer("파일 3개를 옮겼어요.\n• 수업자료",false).equals("• 수업자료"),"duplicate completion prefix not suppressed");
        check(log.remainingAnswer("파일 3개를 옮겼어요.",false).isEmpty(),"completion-only answer was shown twice");
        check(log.remainingAnswer("파일 3개를",true).isEmpty(),"duplicate prefix flashed during streaming");
        check(log.remainingAnswer("파일 3개를",false).equals("파일 3개를"),"different final answer was dropped");
        check(log.remainingAnswer("파일 3개를 옮기지 못했어요.",false).contains("못했어요"),"failure was mistaken for duplicate success");
        check(log.remainingAnswer("파일 3개를 옮겼어요. 추가로 1개는 실패했어요.",false).contains("실패"),"new fact on same line was lost");
        check(log.remainingAnswer("    파일 3개를 옮겼어요.",false).startsWith("    "),"indented code was modified");
        check(log.remainingAnswer("파일 3개를 옮겼어요.\n\n    keep indentation",false).equals("    keep indentation"),"detail indentation lost");
        SwingUtilities.invokeAndWait(()->{
            HomeAssistant home=new HomeAssistant();
            try{
                set(home,"ready",true);set(home,"busy",true);set(home,"replyControl",new ChatReplyControl());
                ((JPanel)get(home,"messages")).removeAll();
                Object user=call(home,"addBubble",new Class[]{String.class,boolean.class},"파일 옮겨줘",true);
                Object answer=call(home,"addBubble",new Class[]{String.class,boolean.class},"",false);set(home,"answerBubble",answer);
                call(answer,"thinking",new Class[]{});
                call(answer,"addActivity",new Class[]{JsonObject.class,boolean.class},plan,true);
                call(answer,"addActivity",new Class[]{JsonObject.class,boolean.class},done,true);
                JPanel messages=(JPanel)get(home,"messages");
                check(messages.getComponentZOrder((JComponent)user)==0,"user turn moved");
                check(messages.getComponentCount()==4&&messages.getComponentZOrder((JComponent)answer)==2,"progress created extra bubbles");
                String progress=(String)get(answer,"shown");
                check(progress.equals("파일을 확인할게요.\n\n파일 3개를 옮겼어요."),"progress not appended in order");
                Object renderer=get(answer,"renderedAnswer");JLabel indicator=(JLabel)get(renderer,"thinkingLabel");
                check(indicator.isVisible()&&indicator.getText().equals("생각중이에요…"),"unfinished operation has no thinking footer");
                check(!(boolean)get(renderer,"thinkingBeforeAnswer"),"thinking footer is above progress");
                call(answer,"stream",new Class[]{String.class},"완료");
                check(((String)get(answer,"shown")).equals(progress+"\n\n완료"),"final stream replaced progress");
                call(answer,"stream",new Class[]{String.class},"완료했어요.");
                check(((String)get(answer,"shown")).equals(progress+"\n\n완료했어요."),"final stream duplicated progress");
                check(indicator.isVisible(),"thinking disappeared before completion");
                call(answer,"finish",new Class[]{String.class},"완료했어요.");
                check(!indicator.isVisible(),"completed answer still thinking");
                check(((String)get(answer,"shown")).equals(progress+"\n\n완료했어요."),"completed answer lost progress");
                call(answer,"stream",new Class[]{String.class},"파일 3개를 옮겼어요.\n• 보관함");
                call(answer,"finish",new Class[]{String.class},"파일 3개를 옮겼어요.\n• 보관함");
                check(((String)get(answer,"shown")).equals(progress+"\n\n• 보관함"),"same outcome repeated in final bubble");
                // Re-enter an unfinished state to verify cancellation and late tool results.
                call(answer,"thinking",new Class[]{});
                call(home,"cancelReply",new Class[]{});
                check(((JComponent)answer).isVisible()&&!indicator.isVisible(),"cancel hid confirmed progress or kept thinking");
                call(answer,"addActivity",new Class[]{JsonObject.class,boolean.class},update(3,"error","중지 결과를 확인했어요."),false);
                check(!indicator.isVisible(),"late cancelled result restarted thinking");
                call(home,"finishInterruptedReply",new Class[]{String.class},"요청을 중지했어요.");
                check(((JComponent)answer).isVisible()&&!((boolean)get(home,"busy")),"cancelled operation did not settle");
                check(((String)get(answer,"shown")).contains("파일 3개를 옮겼어요."),"confirmed result removed on cancel");
                JsonObject request=new JsonObject(),memory=new JsonObject();memory.addProperty("documentId","home-assistant-v1");memory.add("turns",new JsonArray());
                request.addProperty("sessionId","activity-test");request.add("memory",memory);
                JsonObject next=(JsonObject)call(home,"saveInterruptedTurn",new Class[]{JsonObject.class,String.class,JsonArray.class,long.class,JsonArray.class,String.class},request,"파일 옮겨줘",new JsonArray(),1L,log.snapshot(),"요청을 중지했어요.");
                check(!next.toString().contains("activity"),"progress leaked to model memory");
                AssistantConversations store=new AssistantConversations(data.resolve("account/assistant"));
                JsonObject saved=store.load("activity-test");JsonObject turn=AssistantConversations.turns(saved).get(0).getAsJsonObject();
                check(AssistantActivityLog.fromTurn(turn).equals(log.snapshot()),"progress not restored after restart");
                check(turn.get("answer").getAsString().equals("요청을 중지했어요."),"cancel notice lost");
                Object restored=call(home,"addBubble",new Class[]{String.class,boolean.class},"",false);
                call(restored,"restoreActivity",new Class[]{JsonArray.class},AssistantActivityLog.fromTurn(turn));
                call(restored,"finish",new Class[]{String.class},turn.get("answer").getAsString());
                check(((String)get(restored,"shown")).equals(progress+"\n\n요청을 중지했어요."),"restored progress not in one bubble");
                check(!((JLabel)get(get(restored,"renderedAnswer"),"thinkingLabel")).isVisible(),"history showed a stale thinking indicator");
            }catch(Exception failure){throw new RuntimeException(failure);}finally{home.close();}
        });
        System.out.println("AssistantActivityTest OK: ordered updates, cancellation, persistence, no model-context growth");
    }
}

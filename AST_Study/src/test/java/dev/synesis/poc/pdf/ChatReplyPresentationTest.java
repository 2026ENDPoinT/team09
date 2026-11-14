package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.List;
import javax.swing.*;

/** Offline view state only, with a private temporary data root. */
public final class ChatReplyPresentationTest {
    static Object get(Object target,String name)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    static void set(Object target,String name,Object value)throws Exception{Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    static Object call(Object target,String name,Class<?>[] types,Object...args)throws Exception{Method m=target.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(target,args);}
    static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    public static void main(String[]args)throws Exception{
        System.setProperty("synesis.dataRoot",Files.createTempDirectory("chat-presentation-").toString());
        SwingUtilities.invokeAndWait(()->{HomeAssistant home=null;PdfWorkspace mentor=null;try{
            home=new HomeAssistant();set(home,"ready",true);set(home,"busy",true);set(home,"replyControl",new ChatReplyControl());
            Object user=call(home,"addBubble",new Class[]{String.class,boolean.class},"질문",true);
            Object answer=call(home,"addBubble",new Class[]{String.class,boolean.class},"일부",false);set(home,"answerBubble",answer);
            call(home,"updateSendButton",new Class[]{});check(((JButton)get(home,"send")).isEnabled(),"stop button disabled");
            call(home,"cancelReply",new Class[]{});check(!((JComponent)answer).isVisible(),"partial reply visible after stop");
            call(home,"removeCancelledReply",new Class[]{});
            JPanel messages=(JPanel)get(home,"messages");check(((JComponent)answer).getParent()==null,"cancelled reply retained");check(((JComponent)user).getParent()==messages,"user message removed");
            set(home,"busy",true);set(home,"replyControl",new ChatReplyControl());answer=call(home,"addBubble",new Class[]{String.class,boolean.class},"",false);set(home,"answerBubble",answer);set(home,"completedAnswer","완료된 답변");set(home,"completionStatus","완료");
            call(home,"cancelReply",new Class[]{});check("완료된 답변".equals(get(answer,"shown")),"completed reply lost");check(!((boolean)get(home,"busy")),"completion kept busy");
            mentor=new PdfWorkspace(false,Files.createTempDirectory("mentor-cancel-"));set(mentor,"activeTutorMarker","stop");set(mentor,"tutorBusy",true);
            @SuppressWarnings("unchecked") List<Object> turns=(List<Object>)get(mentor,"conversation");
            Class<?> type=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");Constructor<?> ctor=type.getDeclaredConstructor(String.class,String.class,List.class);ctor.setAccessible(true);
            Object turn=ctor.newInstance("질문","stop",List.of());turns.add(turn);
            call(mentor,"finishCancelledTutorReply",new Class[]{});check("[답변 생성이 중지됐어요.]".equals(get(turn,"failure")),"wrong mentor notice");
            check(!(boolean)get(mentor,"tutorBusy"),"mentor remained busy");
            set(mentor,"tutorBusy",true);final int[] completed={0};set(mentor,"tutorStreamCompletion",(Runnable)()->completed[0]++);call(mentor,"cancelTutorReply",new Class[]{});check(completed[0]==1,"mentor completed result discarded");
        }catch(Exception failure){throw new RuntimeException(failure);}finally{if(home!=null)home.close();if(mentor!=null)mentor.close();}});
        System.out.println("ChatReplyPresentationTest OK · assistant hides stop, user retained, completed answers win, mentor notice");System.exit(0);
    }
}

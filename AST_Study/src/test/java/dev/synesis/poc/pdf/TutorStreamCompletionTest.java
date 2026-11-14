package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.List;
import javax.swing.*;

/** A terminal/cached result must drain through the same view before finalization. */
public final class TutorStreamCompletionTest {
    private static PdfWorkspace workspace;
    private static int completions;
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try {
                workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-stream-completion-fixture"));
                ((JScrollPane)field("tutorScroll")).getViewport().setSize(380,600);
                Field active=PdfWorkspace.class.getDeclaredField("activeTutorMarker");active.setAccessible(true);active.set(workspace,"fixture");
                Class<?> turn=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");
                Constructor<?> ctor=turn.getDeclaredConstructor(String.class,String.class,List.class);ctor.setAccessible(true);
                @SuppressWarnings("unchecked") List<Object> conversation=(List<Object>)field("conversation");
                conversation.add(ctor.newInstance("질문","fixture",List.of()));
                call("renderTutor",new Class<?>[]{boolean.class},false);
                String answer="조건을 순서대로 설명해요. 😀 ".repeat(80);
                JsonObject result=new JsonObject();result.addProperty("answer",answer);
                call("completeTutorStream",new Class<?>[]{JsonObject.class,Runnable.class},result,(Runnable)()->completions++);
                ((Timer)field("tutorFadeTimer")).stop();
                call("refreshTutorFade",new Class<?>[]{});
                String first=(String)field("streamingTutorText");
                if(first.isEmpty()||first.equals(answer)||completions!=0)throw new AssertionError("terminal answer bypassed stream");
                for(int n=0;n<100&&!((TutorTextReveal)field("tutorTextReveal")).complete();n++)
                    call("refreshTutorFade",new Class<?>[]{});
                if(!answer.equals(field("streamingTutorText")))throw new AssertionError("answer truncated");
            }catch(Exception e){throw new RuntimeException(e);}
        });
        Thread.sleep(300);
        SwingUtilities.invokeAndWait(()->{
            try {
                call("refreshTutorFade",new Class<?>[]{});call("refreshTutorFade",new Class<?>[]{});
                if(completions!=1)throw new AssertionError("completion lost or repeated");
            }catch(Exception e){throw new RuntimeException(e);}finally{workspace.close();}
        });
        System.out.println("TutorStreamCompletionTest OK");
        System.exit(0);
    }
    private static Object field(String name)throws Exception {
        Field f=PdfWorkspace.class.getDeclaredField(name);f.setAccessible(true);return f.get(workspace);
    }
    private static void call(String name,Class<?>[] types,Object... args)throws Exception {
        Method m=PdfWorkspace.class.getDeclaredMethod(name,types);m.setAccessible(true);m.invoke(workspace,args);
    }
}

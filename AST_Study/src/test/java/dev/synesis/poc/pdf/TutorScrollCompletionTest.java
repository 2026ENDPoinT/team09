package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import javax.swing.*;

/** Exercises the real mentor final-render and animation paths without opening a window. */
public final class TutorScrollCompletionTest {
    private static PdfWorkspace workspace;
    private static JScrollPane scroll;
    private static JPanel messages;
    private static Map<String,JsonObject> answers;
    private static final String ANSWER=("운동량은 질량과 속도의 곱이에요. 조건을 순서대로 확인해요.\n\n").repeat(25);

    public static void main(String[] args)throws Exception {
        try {
            edt(()->{
                workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-scroll-completion-fixture"));
                scroll=(JScrollPane)field("tutorScroll");messages=(JPanel)field("tutorMessages");
                scroll.getViewport().setExtentSize(new Dimension(380,300));
                @SuppressWarnings("unchecked") Map<String,JsonObject> resultMap=(Map<String,JsonObject>)field("tutorAnswers");answers=resultMap;
                @SuppressWarnings("unchecked") List<Object> turns=(List<Object>)field("conversation");
                Class<?> turn=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");
                Constructor<?> ctor=turn.getDeclaredConstructor(String.class,String.class,List.class);ctor.setAccessible(true);
                for(int i=0;i<5;i++) {
                    turns.add(ctor.newInstance("질문 "+i,"fixture-"+i,List.of()));
                    JsonObject result=new JsonObject();result.addProperty("answer",ANSWER);answers.put("fixture-"+i,result);
                }
                call("renderTutor",new Class<?>[]{boolean.class},false);
            });
            drain();
            edt(()->{
                ((TutorScrollKeeper)field("tutorScrollKeeper")).userInput();
                scroll.getViewport().setViewPosition(new Point(0,anchorY("fixture-2/answer")+37));
                finishAnswer();
            });
            drain();
            edt(()->check(scroll.getViewport().getViewPosition().y==anchorY("fixture-2/answer")+37,
                "mentor finalization lost the message being read"));
            edt(()->{
                ((TutorScrollKeeper)field("tutorScrollKeeper")).userInput();
                scroll.getViewport().setViewPosition(new Point(0,messages.getHeight()-300));
                finishAnswer();
            });
            drain();
            edt(()->check(scroll.getViewport().getViewPosition().y==messages.getHeight()-300,
                "mentor finalization stopped following the bottom"));
            System.out.println("TutorScrollCompletionTest OK: final answer and bubble motion preserve reading / follow bottom");
        } finally {if(workspace!=null)edt(()->workspace.close());}
        System.exit(0);
    }

    private static void finishAnswer()throws Exception {
        JsonObject last=answers.get("fixture-4");
        last.addProperty("answer",last.get("answer").getAsString()+ANSWER);
        last.addProperty("followUpQuestion","이 조건이 달라지면 어떻게 돼요?");
        call("renderTutor",new Class<?>[]{boolean.class},true);
        // Multiple size callbacks can be queued before Swing lays out the rebuilt column.
        @SuppressWarnings("unchecked") Map<String,Object> bubbles=(Map<String,Object>)field("tutorBubbles");
        for(Object bubble:bubbles.values()) {
            Field time=bubble.getClass().getDeclaredField("lastResizeNanos");time.setAccessible(true);
            for(int i=0;i<20;i++) {
                time.setLong(bubble,System.nanoTime()-50_000_000);
                call("animateTutorBubbles",new Class<?>[]{});
            }
        }
        ((Timer)field("tutorResizeTimer")).stop();
    }

    private static int anchorY(String key) {
        for(Component row:messages.getComponents())
            if(row instanceof JComponent view && key.equals(view.getClientProperty(TutorScrollKeeper.ANCHOR)))return row.getY();
        throw new AssertionError("anchor missing: "+key);
    }
    private static Object field(String name)throws Exception {
        Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field.get(workspace);
    }
    private static void call(String name,Class<?>[] types,Object...args)throws Exception {
        Method method=PdfWorkspace.class.getDeclaredMethod(name,types);method.setAccessible(true);method.invoke(workspace,args);
    }
    private interface Checked{void run()throws Exception;}
    private static void edt(Checked work)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception error){throw new RuntimeException(error);}});
    }
    private static void drain()throws Exception {edt(()->{});edt(()->{});}
    private static void check(boolean pass,String message){if(!pass)throw new AssertionError(message);}
}

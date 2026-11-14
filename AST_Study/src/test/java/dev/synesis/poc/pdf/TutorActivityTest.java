package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;

/** Exercises status transitions, stale events, and shrink/glide motion offscreen. */
public final class TutorActivityTest {
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(()->{
            AtomicInteger changes=new AtomicInteger();
            TutorActivity activity=new TutorActivity(changes::incrementAndGet);activity.start("first");
            equal(activity.text(),TutorActivity.Stage.PDF.text);
            activity.pdfSearchDone("stale");equal(activity.text(),TutorActivity.Stage.PDF.text);
            activity.pdfSearchDone("first");equal(activity.text(),TutorActivity.Stage.THINKING.text);
            activity.answerStarted("first");equal(changes.get(),2);
            activity.start("fast");activity.answerStarted("fast");
            equal(activity.text(),TutorActivity.Stage.THINKING.text);
            activity.pdfSearchDone("fast");equal(changes.get(),4);
            activity.start("cancel");activity.clear();activity.answerStarted("cancel");
            equal(changes.get(),5);
            activity.start("next");activity.answerStarted("cancel");activity.pdfSearchDone("cancel");
            equal(activity.text(),TutorActivity.Stage.PDF.text);equal(changes.get(),6);
            try {workspace();}catch(Exception error){throw new RuntimeException(error);}
        });
        System.out.println("TutorActivityTest passed: PDF → thinking; stream motion preserved; stale events ignored");
        System.exit(0);
    }
    @SuppressWarnings("unchecked")
    private static void workspace() throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-unused-tutor-stage-fixture"));
        try {
            ((JScrollPane)field(workspace,"tutorScroll")).getViewport().setSize(380,600);
            String marker="stage-fixture";set(workspace,"activeTutorMarker",marker);
            TutorActivity state=(TutorActivity)field(workspace,"tutorActivity");state.start(marker);
            Class<?> turn=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");
            Constructor<?> ctor=turn.getDeclaredConstructor(String.class,String.class,List.class);ctor.setAccessible(true);
            ((List<Object>)field(workspace,"conversation")).add(ctor.newInstance("운동량을 설명해줘",marker,List.of()));
            method(PdfWorkspace.class,"renderTutor",boolean.class).invoke(workspace,false);
            JPanel bubble=((Map<String,JPanel>)field(workspace,"tutorBubbles")).get(marker);
            JLabel label=(JLabel)field(bubble,"thinkingLabel");
            equal(label.getText(),TutorActivity.Stage.PDF.text);
            bubble.setSize(bubble.getPreferredSize());bubble.doLayout();
            if(!label.isVisible() || label.getFont().getSize2D()<16)throw new AssertionError("waiting label lost original large state");
            JsonObject event=new JsonObject();event.addProperty("type","tutor_stage");event.addProperty("stage","answer_wait");
            Method accept=method(PdfWorkspace.class,"acceptTutorEvent",String.class,JsonObject.class);
            accept.invoke(workspace,"stale",event);equal(label.getText(),TutorActivity.Stage.PDF.text);
            accept.invoke(workspace,marker,event);equal(label.getText(),TutorActivity.Stage.THINKING.text);
            event=new JsonObject();event.addProperty("type","tutor_delta");
            event.addProperty("text","운동량은 질량과 속도의 곱이에요. 전체 운동량의 보존 조건을 설명해요. ".repeat(8));
            accept.invoke(workspace,marker,event);method(PdfWorkspace.class,"refreshTutorFade").invoke(workspace);
            equal(label.getText(),TutorActivity.Stage.THINKING.text);
            if((boolean)field(bubble,"thinkingBeforeAnswer"))throw new AssertionError("first delta did not start original lower-position transition");
            Method animate=method(bubble.getClass(),"animateSize",long.class);
            long now=System.nanoTime();for(int i=1;i<=200;i++)animate.invoke(bubble,now+i*16_000_000L);
            if(Math.abs(label.getFont().getSize2D()-13f)>.03f)throw new AssertionError("original small font target changed");
            if(!label.isVisible() || label.getY()<bubble.getPreferredSize().height/2)throw new AssertionError("thinking did not remain below streamed answer");
            int x=label.getX();float font=label.getFont().getSize2D();
            JsonObject duplicate=new JsonObject();duplicate.addProperty("type","tutor_stage");duplicate.addProperty("stage","answer_wait");
            accept.invoke(workspace,marker,duplicate);
            equal(label.getText(),TutorActivity.Stage.THINKING.text);
            if(label.getX()!=x || label.getFont().getSize2D()!=font)throw new AssertionError("stage event restarted motion");
            JsonObject result=new JsonObject();result.addProperty("kind","ai_generated");result.addProperty("answer",event.get("text").getAsString());
            ((Map<String,JsonObject>)field(workspace,"tutorAnswers")).put(marker,result);
            set(workspace,"activeTutorMarker",null);method(PdfWorkspace.class,"clearTutorStream").invoke(workspace);
            method(PdfWorkspace.class,"renderTutor",boolean.class).invoke(workspace,false);
            if(label.isVisible())throw new AssertionError("activity survived completion");
        } finally {workspace.close();}
    }
    private static void equal(Object actual,Object expected) {if(!expected.equals(actual))throw new AssertionError(actual+" != "+expected);}
    private static Object field(Object object,String name)throws Exception {Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(object);}
    private static void set(Object object,String name,Object value)throws Exception {Field f=object.getClass().getDeclaredField(name);f.setAccessible(true);f.set(object,value);}
    private static Method method(Class<?> type,String name,Class<?>... types)throws Exception {Method m=type.getDeclaredMethod(name,types);m.setAccessible(true);return m;}
}

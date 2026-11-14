package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import javax.swing.*;

/** Offline resizing of a long synthetic conversation; no PDF, model or recording. */
public final class TutorLiveResizeTest {
    private static final String ANSWER=("운동량은 질량과 속도의 곱이에요. **외력이 없는 계의 전체 운동량은 보존돼요.** "
        +"물체 사이에 힘이 작용해도 두 힘이 서로 상쇄되기 때문이에요.\n\n"
        +"| 물체 | 질량 | 속도 |\n|---|---|---|\n| A | 2kg | 3m/s |\n| B | 1kg | 0m/s |\n\n"
        +"운동량은 \\(p=mv\\)예요.\n\n"
        +"$$p_{1i}+p_{2i}+p_{3i}+p_{4i}+p_{5i}+p_{6i}=p_{1f}+p_{2f}+p_{3f}+p_{4f}+p_{5f}+p_{6f}$$\n\n").repeat(4);

    public static void main(String[] args) throws Exception {
        boolean baseline=args.length>0 && args[0].equals("baseline");
        SwingUtilities.invokeAndWait(()->{
            try {run(baseline);}catch(Exception error){throw new RuntimeException(error);}
        });
        System.exit(0);
    }

    @SuppressWarnings("unchecked")
    private static void run(boolean baseline) throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-unused-resize-fixture"));
        try {
            JScrollPane scroll=(JScrollPane)field(workspace,"tutorScroll");
            JPanel messages=(JPanel)field(workspace,"tutorMessages");
            scroll.getViewport().setSize(660,600);
            Class<?> turnType=Class.forName("dev.synesis.poc.pdf.PdfWorkspace$TutorTurn");
            Constructor<?> constructor=turnType.getDeclaredConstructors()[0];constructor.setAccessible(true);
            List<Object> conversation=(List<Object>)field(workspace,"conversation");
            Map<String,JsonObject> answers=(Map<String,JsonObject>)field(workspace,"tutorAnswers");
            for(int i=0;i<6;i++) {
                String marker="resize-fixture-"+i;
                conversation.add(constructor.newInstance("운동량 보존을 설명해줘 "+i,marker,List.of()));
                JsonObject answer=new JsonObject();answer.addProperty("kind","ai_generated");
                answer.addProperty("answer",ANSWER);answer.add("evidence",new JsonArray());
                answers.put(marker,answer);
            }
            Method render=method("renderTutor",boolean.class);
            render.invoke(workspace,true);
            Component[] originalRows=messages.getComponents();
            Map<String,JPanel> bubbles=(Map<String,JPanel>)field(workspace,"tutorBubbles");
            JPanel first=bubbles.get("resize-fixture-0");
            JEditorPane firstText=(JEditorPane)field(first,"text");
            Object document=firstText.getDocument();
            firstText.select(5,17);
            Method schedule=baseline?null:method("scheduleTutorReflow");
            Method reflow=baseline?null:method("reflowNextTutorBubble");
            long total=0,maximum=0;
            int frames=18;
            for(int frame=0;frame<frames;frame++) {
                int width=660-frame*3;
                scroll.getViewport().setSize(width,600);
                long start=System.nanoTime();
                if(baseline)render.invoke(workspace,true);
                else {
                    schedule.invoke(workspace);
                    java.util.Deque<?> queue=(java.util.Deque<?>)field(workspace,"tutorReflowQueue");
                    while(!queue.isEmpty()) {
                        long tick=System.nanoTime();reflow.invoke(workspace);
                        maximum=Math.max(maximum,System.nanoTime()-tick);
                    }
                }
                total+=System.nanoTime()-start;
            }
            if(!baseline) {
                if(firstText.getDocument()!=document)throw new AssertionError("width-only resize reparsed unchanged HTML");
                if(firstText.getSelectionStart()!=5 || firstText.getSelectionEnd()!=17)
                    throw new AssertionError("resize discarded text selection");
                Component[] rows=messages.getComponents();
                if(rows.length!=originalRows.length)throw new AssertionError("resize rebuilt conversation");
                for(int i=0;i<rows.length;i++)if(rows[i]!=originalRows[i])throw new AssertionError("resize replaced a conversation row");
                for(JPanel bubble:bubbles.values()) {
                    int width=(int)field(bubble,"targetWidth");
                    if(width!=scroll.getViewport().getWidth()-40)throw new AssertionError("stale bubble width");
                    bubble.setSize(bubble.getPreferredSize());bubble.doLayout();
                    for(Component part:(List<Component>)field(bubble,"bodyParts"))
                        if(part instanceof JEditorPane pane) {
                            var last=pane.modelToView2D(pane.getDocument().getLength());
                            if(last!=null && last.getMaxY()>pane.getHeight()+1)throw new AssertionError("resize clipped final text");
                        }
                }
            }
            System.out.printf("%s: 6 long answers, %d widths, mean full pass %.2f ms, slowest queued item %.2f ms%n",
                baseline?"baseline":"live reflow",frames,total/1_000_000d/frames,maximum/1_000_000d);
        } finally {workspace.close();}
    }

    private static Object field(Object object,String name) throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }
    private static Method method(String name,Class<?>... types) throws Exception {
        Method method=PdfWorkspace.class.getDeclaredMethod(name,types);method.setAccessible(true);return method;
    }
}

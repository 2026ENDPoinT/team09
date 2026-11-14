package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.Path;
import javax.swing.*;

/** Exercises both actual selectors and the request snapshot, without model calls or a window. */
public final class TutorReasoningChoiceTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            PdfWorkspace workspace=new PdfWorkspace(false,Path.of(System.getProperty("java.io.tmpdir"),"synesis-tutor-reasoning-choice"));
            try {
                JComboBox<?> mode=(JComboBox<?>)field(workspace,"tutorMode");
                JComboBox<?> reasoning=(JComboBox<?>)field(workspace,"tutorReasoning");
                check("중간 추론".equals(reasoning.getSelectedItem()),"default reasoning should be middle (low)");
                check(reasoning.getItemCount()==2 && "중간 추론".equals(reasoning.getItemAt(1)),"reasoning choices missing");
                Method options=PdfWorkspace.class.getDeclaredMethod("addTutorAnswerOptions",JsonObject.class);options.setAccessible(true);
                for(int m=0;m<2;m++)for(int r=0;r<2;r++) {
                    mode.setSelectedIndex(m);reasoning.setSelectedIndex(r);
                    JsonObject request=new JsonObject();options.invoke(workspace,request);
                    check(request.get("mode").getAsString().equals(m==1?"deep":"quick"),"reasoning changed answer length");
                    check(request.get("reasoningEffort").getAsString().equals(r==1?"low":"medium"),"reasoning label mapped to wrong API effort");
                    reasoning.setSelectedIndex(1-r);
                    check(request.get("reasoningEffort").getAsString().equals(r==1?"low":"medium"),"changing next choice altered a submitted request");
                }
                JPanel row=(JPanel)reasoning.getParent();row.setSize(306,36);row.doLayout();
                check(!mode.getBounds().intersects(reasoning.getBounds()),"selectors overlap");
                for(Component option:row.getComponents())check(option.getX()>=0 && option.getX()+option.getWidth()<=row.getWidth()
                    && option.getY()+option.getHeight()<=row.getHeight(),"answer options wrap outside the input header");
            }catch(Exception error){throw new RuntimeException(error);}
            finally {workspace.close();}
        });
        System.out.println("TutorReasoningChoiceTest OK: high=medium / middle=low, independent explanation modes, stable request snapshot, compact layout");
        System.exit(0);
    }
    private static Object field(Object target,String name)throws Exception {
        Field field=PdfWorkspace.class.getDeclaredField(name);field.setAccessible(true);return field.get(target);
    }
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}

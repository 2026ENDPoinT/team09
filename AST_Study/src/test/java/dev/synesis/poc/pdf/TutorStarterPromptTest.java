package dev.synesis.poc.pdf;

import com.google.gson.JsonObject;
import java.util.ArrayList;
import java.util.List;
import javax.swing.JButton;
import javax.swing.SwingUtilities;

/** Exercise the actual welcome button factory without a window or remote call. */
public final class TutorStarterPromptTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            String[] labels={"이해에 필요한 배경지식 설명해줘.","핵심 개념들만 모아줘.","시험 출제 예상해줘."};
            String[] ids={"background_knowledge","key_concepts","exam_prediction"};
            List<TutorStarterPrompt> selected=new ArrayList<>();
            int i=0;
            for(TutorStarterPrompt starter:TutorStarterPrompt.values()) {
                JButton button=starter.button(selected::add);
                check(button.getText().equals(labels[i]),"visible label changed");
                button.doClick(0);
                check(selected.size()==i+1 && selected.get(i)==starter,"button sent another task");
                JsonObject request=new JsonObject();request.addProperty("question",button.getText());
                starter.addTo(request);
                check(request.get("starterId").getAsString().equals(ids[i]),"worker task ID mismatch");
                check(request.get("question").getAsString().equals(labels[i]),"hidden policy leaked into chat text");
                request.addProperty("question","다른 질문");
                try {starter.addTo(request);throw new AssertionError("mismatched question accepted");}
                catch(IllegalArgumentException expected) { }
                i++;
            }
        });
        System.out.println("TutorStarterPromptTest OK: 3 actual button actions, labels and worker IDs");
    }
    private static void check(boolean condition,String message) {if(!condition)throw new AssertionError(message);}
}

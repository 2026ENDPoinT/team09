package dev.synesis.poc.pdf;

import com.google.gson.*;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.nio.file.*;

final class StepFlowTest {
    public static void main(String[] args)throws Exception {
        Files.createDirectories(Path.of("build","pdf-tests"));
        run();
        System.out.println("PASS: approved StepFlow controls, 40-step navigation and offscreen layout");
    }
    static void run() throws Exception {
        JsonObject index=JsonParser.parseString("{\"pages\":[{},{}]}").getAsJsonObject();
        JsonObject block=new JsonObject(),value=new JsonObject();block.add("stepFlow",value);
        value.addProperty("moduleId",StepFlow.ID);value.addProperty("schemaVersion",1);
        value.addProperty("title","자료를 이해하는 순서");value.addProperty("variant","a");
        JsonArray steps=new JsonArray();value.add("steps",steps);
        for(String name:new String[]{"자료 수집","분류","관계 파악","검토","결과 정리"}) {
            JsonObject step=new JsonObject();step.addProperty("title",name);
            step.addProperty("body","**"+name+"** 단계에서 자료를 살펴봅니다.\n\n앞선 단계에서 얻은 결과를 확인하고, 다음 단계에 필요한 내용을 정리합니다.");
            step.addProperty("context","강의 자료");step.addProperty("insight","단계 사이에 어떤 정보가 이어지는지 확인해 보세요.");
            step.add("evidence",JsonParser.parseString("[{\"page\":1,\"quote\":\"근거\"}]"));steps.add(step);
        }
        approve(value,steps.size());
        for(String style:new String[]{"a","d"}) {
            value.addProperty("variant",style);StepFlow.Model model=StepFlow.resolve(block,index);
            if(model==null)throw new AssertionError("Valid StepFlow rejected");
            SwingUtilities.invokeAndWait(()->{
                StepFlow.Panel panel=new StepFlow.Panel(model,18,0,n->{},n->{});
                panel.select(99);if(panel.selected()!=4)throw new AssertionError("Last step");
                panel.select(-1);if(panel.selected()!=0)throw new AssertionError("First step");
                JButton tab=buttons(panel).stream().filter(b->b.getText().contains("관계 파악")).findFirst().orElseThrow();
                tab.doClick();if(panel.selected()!=2)throw new AssertionError("Tab click");
                tab.getActionMap().get("RIGHT").actionPerformed(null);
                if(panel.selected()!=3)throw new AssertionError("Right arrow");
                JButton next=buttons(panel).stream().filter(b->"다음 단계".equals(b.getAccessibleContext().getAccessibleName())).findFirst().orElseThrow();
                next.doClick();if(panel.selected()!=4 || next.isEnabled())throw new AssertionError("Next/end state");
                panel.select(2);
                for(int width:new int[]{680,340}) {
                    panel.setSize(width,600);panel.setSize(width,panel.getPreferredSize().height);layout(panel);
                    panel.select(2);
                    int cardWidth=width-panel.getInsets().left-panel.getInsets().right+52;
                    if(Math.abs(cardWidth-width*.85)>3)throw new AssertionError("Step card width");
                    for(JEditorPane pane:findPanes(panel))
                        if(pane.getPreferredSize().height>pane.getHeight()+2)throw new AssertionError("Step text clipped");
                    BufferedImage image=new BufferedImage(width,panel.getHeight(),BufferedImage.TYPE_INT_RGB);
                    Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,width,image.getHeight());panel.printAll(g);g.dispose();
                    try{ImageIO.write(image,"png",Path.of("build","pdf-tests","step-flow-"+style+"-"+width+".png").toFile());}
                    catch(Exception error){throw new RuntimeException(error);}
                }
                JPanel content=new JPanel(new BorderLayout());
                content.add(panel,BorderLayout.NORTH);content.add(Box.createVerticalStrut(900),BorderLayout.CENTER);
                JScrollPane outer=new JScrollPane(content);
                outer.setSize(680,300);outer.doLayout();content.setSize(outer.getViewport().getExtentSize());
                layout(content);outer.getVerticalScrollBar().setValue(0);
                JScrollPane tabs=findScrollPanes(panel).stream().findFirst().orElseThrow();
                tabs.dispatchEvent(new MouseWheelEvent(tabs,MouseWheelEvent.MOUSE_WHEEL,
                    System.currentTimeMillis(),0,20,20,0,0,0,false,
                    MouseWheelEvent.WHEEL_UNIT_SCROLL,3,2,2));
                if(outer.getVerticalScrollBar().getValue()==0)throw new AssertionError("Wheel over step tabs did not scroll document");
            });
        }
        for(int i=steps.size();i<40;i++) {
            JsonObject step=new JsonObject();
            step.addProperty("title","긴 설명을 담은 학습 단계 "+i+" 다음 상태와 연결되는 조건 확인");
            step.addProperty("body","앞선 상태 "+(i-1)+"를 바탕으로 상태 "+i+"로 넘어가는 조건을 설명합니다.");
            step.add("evidence",JsonParser.parseString("[{\"page\":1,\"quote\":\"근거\"}]").getAsJsonArray());
            steps.add(step);
        }
        approve(value,steps.size());
        StepFlow.Model longModel=StepFlow.resolve(block,index);
        if(longModel==null || longModel.steps().size()!=40)throw new AssertionError("Long process truncated");
        SwingUtilities.invokeAndWait(()->{
            StepFlow.Panel panel=new StepFlow.Panel(longModel,18,0,n->{},n->{});
            panel.setSize(680,900);panel.setSize(680,panel.getPreferredSize().height);layout(panel);
            panel.select(39);layout(panel);
            JScrollPane navigation=findScrollPanes(panel).get(0);
            if(navigation.getHorizontalScrollBar().getMaximum()<=navigation.getViewport().getWidth()
                    || navigation.getViewport().getViewPosition().x==0)
                throw new AssertionError("Long process should scroll selected tab into view");
            JButton last=buttons(panel).stream().filter(b->b.getToolTipText()!=null && b.getToolTipText().contains("39")).findFirst().orElseThrow();
            if(!last.getText().contains("…") || !last.getAccessibleContext().getAccessibleName().contains("다음 상태"))
                throw new AssertionError("Long tab label must indicate truncation and retain accessible full title");
        });
        value.addProperty("variant","b");if(StepFlow.resolve(block,index)!=null)throw new AssertionError("Unsupported style accepted");
        value.addProperty("variant","a");value.addProperty("schemaVersion",99);
        if(StepFlow.resolve(block,index)!=null)throw new AssertionError("Unsupported version accepted");
    }
    static JsonObject fixtureModule(){return JsonParser.parseString("""
        {"moduleId":"synesis.step-flow","schemaVersion":1,"variant":"a","title":"순서 확인",
         "eligibility":{"policyVersion":"ordered-process-v2","kind":"procedure","sourceGrounded":true,"transitionCount":2},
         "steps":[{"title":"수집","body":"자료를 수집합니다.","evidence":[{"page":1,"quote":"자료 수집"}]},
                  {"title":"정제","body":"모은 자료의 오류를 정제합니다.","evidence":[{"page":1,"quote":"자료 정제"}]},
                  {"title":"검토","body":"수집한 자료를 검토합니다.","evidence":[{"page":1,"quote":"자료 검토"}]}]}
        """).getAsJsonObject();}
    private static void approve(JsonObject value,int count) {
        JsonObject stamp=new JsonObject();stamp.addProperty("policyVersion",StepFlow.POLICY_VERSION);
        stamp.addProperty("kind","process");stamp.addProperty("sourceGrounded",true);
        stamp.addProperty("transitionCount",count-1);value.add("eligibility",stamp);
    }
    private static void layout(Container container){container.doLayout();for(Component c:container.getComponents())if(c instanceof Container child)layout(child);}
    private static java.util.List<JButton> buttons(Container container){
        java.util.List<JButton> result=new java.util.ArrayList<>();
        for(Component c:container.getComponents()){if(c instanceof JButton button)result.add(button);else if(c instanceof Container child)result.addAll(buttons(child));}
        return result;
    }
    private static java.util.List<JEditorPane> findPanes(Container container){
        java.util.List<JEditorPane> result=new java.util.ArrayList<>();
        for(Component c:container.getComponents()) {if(c instanceof JEditorPane pane)result.add(pane);else if(c instanceof Container child)result.addAll(findPanes(child));}
        return result;
    }
    private static java.util.List<JScrollPane> findScrollPanes(Container container){
        java.util.List<JScrollPane> result=new java.util.ArrayList<>();
        for(Component c:container.getComponents()) {
            if(c instanceof JScrollPane pane)result.add(pane);
            else if(c instanceof Container child)result.addAll(findScrollPanes(child));
        }
        return result;
    }
}

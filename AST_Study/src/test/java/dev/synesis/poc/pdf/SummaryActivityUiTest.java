package dev.synesis.poc.pdf;

import com.google.gson.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import javax.imageio.ImageIO;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Offline activity lifecycle and live-reading position contracts, without an API or dialog. */
public final class SummaryActivityUiTest {
    private static PdfWorkspace workspace;
    private static JScrollPane scroll;
    private static JPanel flow;
    private static SummaryActivityBar bar;
    private static int readingY;
    private static final Path OUT=Path.of("build/pdf-overview-completion-20261021/workspace");
    public static void main(String[] args)throws Exception {
        try {
            Files.createDirectories(OUT);
            edt(SummaryActivityUiTest::setup);flush();
            edt(()->{
                check(!text(flow).contains("EXTRACTED_ORIGINAL"),"raw PDF extraction leaked into summary");
                check(text(flow).contains("이 강의의 흐름")&&text(flow).contains("강의의 흐름을 PDF를 읽으며 정리하고 있어요."),"preparation overview missing");
                check(text(flow).contains("요약 생성 중에도 PDF와 연결된 AI멘토를 이용할 수 있어요."),"tutor availability notice missing");
                check(bar.getParent() instanceof SummaryOverviewLoading&&bar.getParent().getParent()==flow
                    &&bar.state()==SummaryActivityBar.State.RUNNING,"activity must be inside the overview card");
                check(((JLabel)get(workspace,"status")).getParent()==null,"PDF footer progress still attached");
                List<StudyHtmlPane> panes=panes(flow);long[] revisions=panes.stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
                activityFrames();
                for(int i=0;i<panes.size();i++)check(revisions[i]==panes.get(i).contentRevision(),"activity frames reparsed HTML");
                snapshot("preparing.png");
                set(workspace,"liveGenerationKey",call(workspace,"productKey",new Class<?>[]{String.class,int.class},"document",0));
                set(workspace,"liveSummaryTotal",10);append(1);
                render();layout();
                check(((SummaryOverviewLoading)bar.getParent()).hasSummary(),"first actual summary must start docking");
            });flush();
            edt(()->check(scroll.getViewport().getViewPosition().y==0,"first summary scrolled the docking overview out of view"));
            // A reader in the middle must stay there while another completed unit arrives.
            edt(()->{scroll.getVerticalScrollBar().setValue(120);readingY=scroll.getVerticalScrollBar().getValue();append(2);render();layout();});flush();
            edt(()->check(scroll.getVerticalScrollBar().getValue()==readingY,"middle reader followed generated tail"));
            // Even 20 pixels above the end is not the bottom.
            edt(()->{scroll.getVerticalScrollBar().setValue(max()-20);readingY=scroll.getVerticalScrollBar().getValue();append(3);render();layout();});flush();
            edt(()->check(scroll.getVerticalScrollBar().getValue()==readingY,"near-bottom reader was pulled down"));
            // The reader already at the end still gets follow-tail behavior.
            edt(()->{scroll.getVerticalScrollBar().setValue(Integer.MAX_VALUE);append(4);render();layout();});flush();
            edt(()->check(Math.abs(scroll.getVerticalScrollBar().getValue()-max())<=3,"bottom reader stopped following: "+scroll.getVerticalScrollBar().getValue()+" / "+max()));
            // Wheel input after render but before its queued callback wins over that callback.
            edt(()->{
                append(5);render();layout();
                scroll.dispatchEvent(new MouseWheelEvent(scroll,MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,5,5,0,false,
                    MouseWheelEvent.WHEEL_UNIT_SCROLL,3,-10));
                scroll.getVerticalScrollBar().setValue(80);readingY=scroll.getVerticalScrollBar().getValue();
            });flush();
            edt(()->{
                check(scroll.getVerticalScrollBar().getValue()==readingY,"queued follow-tail overrode wheel input");
                check(!text(flow).contains("완료된 구간")&&!text(flow).contains("기다리는 중"),"old waiting/progress copy remains");
                long[] revisions=panes(flow).stream().mapToLong(StudyHtmlPane::contentRevision).toArray();
                call(workspace,"setGenerationProgress",new Class<?>[]{PdfWorkspace.GenerationProgress.class},
                    new PdfWorkspace.GenerationProgress("fixture","fixture.pdf",37,"생성 중",false,false));
                check(bar.progress()==37,"measured generation progress not connected");
                check(Arrays.equals(revisions,panes(flow).stream().mapToLong(StudyHtmlPane::contentRevision).toArray()),
                    "progress-only update reparsed summary HTML");
                call(workspace,"setGenerationProgress",new Class<?>[]{PdfWorkspace.GenerationProgress.class},
                    new PdfWorkspace.GenerationProgress("fixture","fixture.pdf",37,"네트워크 오류",true,true));
                check(bar.state()==SummaryActivityBar.State.STOPPED,"failed job did not turn red");
                render();layout();snapshot("stopped.png");
                call(workspace,"cancelAnalysis");check(bar.state()==SummaryActivityBar.State.STOPPED,"cancel did not stay red");
                check(bar.progress()==37,"cancel erased last measured progress");
                call(workspace,"setGenerationProgress",new Class<?>[]{PdfWorkspace.GenerationProgress.class},
                    new PdfWorkspace.GenerationProgress("fixture","fixture.pdf",0,"다시 준비",false,false));
                check(bar.state()==SummaryActivityBar.State.RUNNING,"retry did not restart green activity");
                check(bar.progress()==0,"retry retained stale progress");
                call(workspace,"clearLiveSummary");
                JsonObject result=JsonParser.parseString("{\"kind\":\"ai_generated\",\"scope\":\"document\",\"page\":0,\"overview\":{\"body\":\"완료된 학습 요약이에요.\"},\"sections\":[],\"concepts\":[]}").getAsJsonObject();
                set(workspace,"generated",result);
                call(workspace,"finishGeneration",new Class<?>[]{boolean.class,String.class},false,"완료");
                SummaryOverviewLoading card=(SummaryOverviewLoading)bar.getParent();
                check(bar.state()==SummaryActivityBar.State.IDLE && card.getParent()==flow && card.completed(),"completion must reuse the existing overview card");
                check(!bar.isVisible() && !text(flow).contains("정리하고 있어요") && !text(flow).contains("AI멘토를 이용할 수"),"loading notices remained after completion");
                check(text(flow).contains("완료된 학습 요약"),"completed summary lost");
                layout();snapshot("completed.png");
                call(workspace,"renderSummary",new Class<?>[]{boolean.class},true);layout();
                check(card==bar.getParent() && card.getParent()==flow && card.completed(),"rerender replaced the completed card");
            });flush();
            edt(()->{workspace.close();check(!((javax.swing.Timer)get(bar,"timer")).isRunning(),"close retained animation timer");workspace=null;});
            System.out.println("SummaryActivityUiTest passed: decelerating 500ms sweep; 10x launch speed; separate measured progress; lifecycle colors; raw extraction hidden; reading position and user-input race.");
        }catch(Throwable error){error.printStackTrace();if(workspace!=null)edt(()->workspace.close());System.exit(1);}
        System.exit(0);
    }
    private static void setup()throws Exception {
        Path file=Files.createTempFile("synesis-activity-", ".pdf");
        try(PDDocument pdf=new PDDocument()){pdf.addPage(new PDPage());pdf.save(file.toFile());}
        workspace=new PdfWorkspace(false,OUT.resolve("unused-library"));
        set(workspace,"source",PdfSource.open(file,OUT.resolve("unused-library")));Files.deleteIfExists(file);
        JsonObject index=JsonParser.parseString("{\"pages\":[{\"number\":1,\"markdown\":\"EXTRACTED_ORIGINAL\"}]}").getAsJsonObject();set(workspace,"index",index);
        scroll=(JScrollPane)get(workspace,"summaryScroll");flow=(JPanel)get(workspace,"summaryFlow");bar=(SummaryActivityBar)get(workspace,"summaryActivity");
        call(workspace,"setSummaryActivity",new Class<?>[]{SummaryActivityBar.State.class},SummaryActivityBar.State.RUNNING);layout();
    }
    @SuppressWarnings("unchecked")
    private static void append(int number)throws Exception {
        JsonObject section=new JsonObject();section.addProperty("title","학습 구간 "+number);
        String body=("문맥을 이해하며 읽고 있는 학습 내용이에요. 수식과 조건을 함께 살펴봐요.\n\n").repeat(12);
        section.addProperty("body",body);section.addProperty("easyExplanation","");section.add("evidence",new JsonArray());
        ((Map<Integer,JsonObject>)get(workspace,"liveSummarySections")).put(number,section);
        ((Map<Integer,Integer>)get(workspace,"liveSummaryVisible")).put(number,body.codePointCount(0,body.length()));
    }
    private static void activityFrames()throws Exception {
        AtomicLong time=new AtomicLong();SummaryActivityBar sample=new SummaryActivityBar(time::get);sample.setSize(500,20);sample.setState(SummaryActivityBar.State.RUNNING);sample.setProgress(37);
        time.set(100_000_000);BufferedImage a=frame(sample);time.set(350_000_000);BufferedImage b=frame(sample);
        check(!Arrays.equals(pixels(a),pixels(b)),"activity sweep is static");
        check(new Color(a.getRGB(80,14)).getBlue()>230&&a.getRGB(250,14)==new Color(0xedf1f5).getRGB(),
            "lower progress track does not show measured 37 percent");
        check(Arrays.equals(a.getRGB(0,14,500,1,null,0,500),b.getRGB(0,14,500,1,null,0,500)),
            "activity animation changed measured progress");
        time.set(600_000_000);check(Arrays.equals(pixels(a),pixels(frame(sample))),"sweep period is not 500ms");
        double launch=(double)get(sample,"EASE_OUT_POWER")/SummaryActivityBar.CYCLE_NANOS;
        check(Math.abs(launch/((3*.25*500/700)/500_000_000)-10)<1e-9,"launch velocity is not 10x previous speed");
        int previousHead=-1,previousStep=Integer.MAX_VALUE;
        for(long instant=25_000_000;instant<=100_000_000;instant+=25_000_000) {
            time.set(instant);int head=activityHead(frame(sample));
            check(head>=0,"missile head disappeared mid-cycle");
            if(previousHead>=0) {int step=head-previousHead;check(step>0&&step<previousStep,"sweep did not decelerate");previousStep=step;}
            previousHead=head;
        }
        ImageIO.write(frame(sample),"png",OUT.resolve("bar-running.png").toFile());
        sample.setState(SummaryActivityBar.State.STOPPED);a=frame(sample);time.set(1_000_000_000);b=frame(sample);
        check(Arrays.equals(pixels(a),pixels(b)),"stopped bar still animates");
        Color middle=new Color(a.getRGB(250,6));check(middle.getRed()>middle.getGreen()*2,"stopped bar not red");
        check(!((javax.swing.Timer)get(sample,"timer")).isRunning(),"hidden/stopped bar has active timer");
        sample.close();ImageIO.write(a,"png",OUT.resolve("bar-stopped.png").toFile());
    }
    private static int activityHead(BufferedImage frame) {
        for(int x=frame.getWidth()-1;x>=0;x--) {Color c=new Color(frame.getRGB(x,6));
            if(Math.max(c.getRed(),Math.max(c.getGreen(),c.getBlue()))<80)return x;}
        return -1;
    }
    private static BufferedImage frame(JComponent c){BufferedImage b=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=b.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,b.getWidth(),b.getHeight());c.paint(g);g.dispose();return b;}
    private static int[] pixels(BufferedImage b){return b.getRGB(0,0,b.getWidth(),b.getHeight(),null,0,b.getWidth());}
    private static void render()throws Exception {call(workspace,"renderSummary",new Class<?>[]{boolean.class},true);}
    private static int max(){JScrollBar b=scroll.getVerticalScrollBar();return Math.max(0,b.getMaximum()-b.getVisibleAmount());}
    private static void layout(){scroll.setSize(646,420);scroll.doLayout();int w=scroll.getViewport().getWidth();flow.setSize(w,Math.max(1,flow.getPreferredSize().height));flow.doLayout();scroll.getViewport().setViewSize(flow.getSize());scroll.doLayout();}
    private static void snapshot(String name)throws Exception {layout();ImageIO.write(frame(flow),"png",OUT.resolve(name).toFile());}
    private static List<StudyHtmlPane> panes(Container c){List<StudyHtmlPane> ps=new ArrayList<>();for(Component x:c.getComponents())if(x instanceof StudyHtmlPane p)ps.add(p);else if(x instanceof Container n)ps.addAll(panes(n));return ps;}
    private static String text(Container c)throws Exception {StringBuilder b=new StringBuilder();for(Component child:c.getComponents()) {
        if(!child.isVisible())continue;
        if(child instanceof StudyHtmlPane p)b.append(p.getDocument().getText(0,p.getDocument().getLength()));
        else if(child instanceof JLabel label)b.append(label.getText());
        else if(child instanceof Container nested)b.append(text(nested));
    }return b.toString();}
    private static Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String n,Object v)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
    private static Object call(Object o,String n)throws Exception{return call(o,n,new Class<?>[]{});}
    private static Object call(Object o,String n,Class<?>[] types,Object...args)throws Exception{Method m=o.getClass().getDeclaredMethod(n,types);m.setAccessible(true);return m.invoke(o,args);}
    private interface Work{void run()throws Exception;}
    private static void edt(Work work)throws Exception{SwingUtilities.invokeAndWait(()->{try{work.run();}catch(Exception e){throw new RuntimeException(e);}});}
    private static void flush()throws Exception{edt(()->{});edt(()->{});}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}

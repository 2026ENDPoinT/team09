package dev.synesis.poc.pdf;

import com.google.gson.*;
import org.apache.pdfbox.pdmodel.*;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;
import javax.swing.*;

/** Offline behavior coverage: real Swing anchors, moved PDF viewport, and connection states. */
public final class WorkspaceDesignBehaviorTest {
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("WorkspaceDesignBehaviorTest passed");System.exit(0);
    }
    private static void run()throws Exception{
        long now=2_000_000_000_000L;
        check("방금".equals(TutorPresentation.relativeTime(now-120_000,now)),"two-minute boundary");
        check("2분 전".equals(TutorPresentation.relativeTime(now-120_001,now)),"after two minutes");
        check("58분 전".equals(TutorPresentation.relativeTime(now-58*60_000L,now)),"58-minute boundary");
        check("1시간 전".equals(TutorPresentation.relativeTime(now-58*60_000L-1,now)),"hour threshold");
        check("23시간 전".equals(TutorPresentation.relativeTime(now-23*3_600_000L,now)),"23-hour boundary");
        check("1일 전".equals(TutorPresentation.relativeTime(now-23*3_600_000L-1,now)),"day threshold");
        check("14일 전".equals(TutorPresentation.relativeTime(now-14*86_400_000L,now)),"14-day boundary");
        check("오래 전".equals(TutorPresentation.relativeTime(now-14*86_400_000L-1,now)),"old threshold");
        JsonObject suggestion=new JsonObject();suggestion.addProperty("followUpQuestion","  다음 질문?  ");
        check("다음 질문?".equals(TutorPresentation.followUp(suggestion)),"valid suggestion");
        suggestion.addProperty("followUpQuestion","두\n질문");check(TutorPresentation.followUp(suggestion).isEmpty(),"malformed suggestion");

        JPanel flow=new JPanel();
        JEditorPane overview=html("이 강의의 흐름 <a href='page:5'>p.5</a>");flow.add(overview);
        JPanel nested=new JPanel();JEditorPane section=html("<a name='synesis-summary-content'></a>첫 근거 <a href='page:5'>p.5</a> 다음 <a href='page:5'>p.5</a>");nested.add(section);flow.add(nested);
        var target=SummaryPageNavigator.find(flow,5);
        check(target!=null&&target.pane()==section,"skip overview, traverse split panes");
        check(target.offset()==section.getDocument().getText(0,section.getDocument().getLength()).indexOf("p.5"),"first matching citation");
        check(SummaryPageNavigator.find(flow,6)==null,"missing citation");

        Path root=Files.createTempDirectory("synesis-mist-test-");Path file=root.resolve("fixture.pdf");
        try(PDDocument doc=new PDDocument()){for(int i=0;i<3;i++)doc.addPage(new PDPage());doc.save(file.toFile());}
        PdfWorkspace workspace=new PdfWorkspace(false,root.resolve("library"));
        try{
            JPanel tutor=(JPanel)get(workspace,"tutorPanel");
            JLabel tutorTitle=findLabel(tutor,"AI멘토"),tagline=findLabel(tutor,"– 원문과 함께, 이해될 때까지.");
            check(tutorTitle.getFont().getSize()==18&&tagline.getFont().getSize()==11,"larger tutor title and tagline");
            for(int width:new int[]{500,210,500}){
                tutor.setSize(width,620);layout(tutor);
                check(tagline.isVisible()==(width==500),"tagline hides when narrow and returns when wide");
                if(tagline.isVisible()){
                    check(tagline.getX()>=tutorTitle.getX()+tutorTitle.getWidth(),"tagline stays beside title");
                    check(Math.abs((tutorTitle.getY()+tutorTitle.getHeight()/2)-(tagline.getY()+tagline.getHeight()/2))<=1,"tutor title and tagline vertically centered");
                }
                check(tutorTitle.getWidth()==tutorTitle.getPreferredSize().width,"title remains complete when tagline is hidden");
            }
            set(workspace,"source",PdfSource.open(file,root.resolve("library")));
            JsonObject index=new JsonObject();index.add("pages",new JsonArray());set(workspace,"index",index);
            ((JSpinner)get(workspace,"pageNumber")).setModel(new SpinnerNumberModel(1,1,3,1));
            call(workspace,"setControls");
            JLabel top=(JLabel)get(workspace,"tutorConnection"),bottom=(JLabel)get(workspace,"tutorDocumentConnection");
            check(top.getText().equals("PDF 연결됨")&&bottom.getText().contains("약한 연결"),"ready weak connection");
            set(workspace,"busy",true);call(workspace,"setControls");
            check(top.getText().contains("답변 가능")&&bottom.getText().contains("강한 연결 시도 중"),"generating connection");
            set(workspace,"busy",false);JsonObject generated=new JsonObject();JsonObject body=new JsonObject();body.addProperty("body","요약");generated.add("overview",body);set(workspace,"generated",generated);call(workspace,"updateTutorConnection");
            check(bottom.getText().contains("강한 연결 성공"),"saved summary connection");

            JComponent[] fullscreen={null};boolean[] returned={false};
            workspace.setPdfOnlyScreenHandler(screen->fullscreen[0]=screen,()->returned[0]=true);
            Object reading=get(workspace,"pdfReadingArea"),scroll=get(workspace,"imageScroll");
            JTabbedPane tabs=(JTabbedPane)get(workspace,"sourceTabs");
            JComboBox<?> studyZoom=(JComboBox<?>)get(workspace,"zoom"),fullZoom=(JComboBox<?>)get(workspace,"fullZoom");
            studyZoom.setSelectedItem("150%");
            call(workspace,"showPdfOnly");
            check(fullscreen[0]!=null&&((Component)reading).getParent()==fullscreen[0],"PDF-only screen owns existing viewport");
            check(((Component)reading).isVisible(),"detached PDF remains visible");
            check(tabs.getComponentAt(0)!=reading,"viewport detached from study");
            check("100%".equals(fullZoom.getSelectedItem()),"PDF-only default is 100%");
            check("150%".equals(studyZoom.getSelectedItem()),"entering fullscreen changed study zoom");
            fullZoom.setSelectedItem("125%");
            call(workspace,"leavePdfOnly");
            check(returned[0]&&tabs.getComponentAt(0)==reading&&get(workspace,"imageScroll")==scroll,"back restores existing viewport");
            check("150%".equals(studyZoom.getSelectedItem()),"fullscreen zoom leaked into study");
            call(workspace,"showPdfOnly");
            check("125%".equals(fullZoom.getSelectedItem()),"fullscreen zoom not preserved on re-entry");
            call(workspace,"leavePdfOnly");
            check("150%".equals(studyZoom.getSelectedItem()),"study zoom changed after repeated fullscreen");
        }finally{workspace.close();}
    }
    private static JEditorPane html(String body){return new JEditorPane("text/html","<html><body>"+body+"</body></html>");}
    private static JLabel findLabel(Container parent,String text){for(Component child:parent.getComponents()){if(child instanceof JLabel label&&text.equals(label.getText()))return label;if(child instanceof Container nested){JLabel found=findLabel(nested,text);if(found!=null)return found;}}return null;}
    private static void layout(Container parent){parent.doLayout();for(Component child:parent.getComponents())if(child instanceof Container nested)layout(nested);}
    private static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String name,Object value)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);f.set(o,value);}
    private static void call(Object o,String name)throws Exception{Method m=o.getClass().getDeclaredMethod(name);m.setAccessible(true);m.invoke(o);}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
}

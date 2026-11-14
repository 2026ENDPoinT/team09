package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.*;
import javax.swing.*;
import java.awt.*;
import java.lang.reflect.*;
import java.nio.file.*;

/** Integration with the actual PDF/summary/concept/quiz/tutor instances; no providers or native UI. */
public final class StudyWorkspaceColumnsTest {
    public static void main(String[] args)throws Exception{
        Path data=Files.createTempDirectory("study-workspace-columns-");
        System.setProperty("synesis.dataRoot",data.toString());
        SwingUtilities.invokeAndWait(()->{try{
            PdfWorkspace workspace=new PdfWorkspace(false,data.resolve("library"));
            FloatingMentor mentor=new FloatingMentor();
            try{
                StudyColumns columns=(StudyColumns)get(workspace,"studyColumns");
                JComponent notes=new JPanel();workspace.addLearningTab("강의록",notes);
                workspace.setSize(1500,800);layout(workspace);
                Object summary=get(workspace,"summary"),quiz=get(workspace,"quiz"),concept=get(workspace,"conceptOverview");
                check(columns.count()==1&&columns.containsView("요약"),"initial summary");
                columns.open("개념정리");layout(workspace);
                check(SwingUtilities.isDescendingFrom((Component)summary,columns)&&SwingUtilities.isDescendingFrom((Component)concept,columns),"simultaneous real summary and concepts");
                check(button(columns,"강의 해설")!=null&&button(columns,"개념 정리")!=null,"real header dropdowns");
                JButton selector=button(columns,"강의 해설");
                check(selector.getIcon()!=null&&selector.getHorizontalAlignment()==SwingConstants.LEFT,"drawn arrow and left aligned header");
                JSplitPane pdfSplit=(JSplitPane)get(workspace,"studySplit");Component pdf=pdfSplit.getLeftComponent();
                int pdfWidth=pdfSplit.getDividerLocation();columns.select(0,"개념정리");layout(workspace);
                check(pdfSplit.getLeftComponent()==pdf&&pdfSplit.getDividerLocation()==pdfWidth,"swap never moves PDF");
                columns.select(1,"퀴즈로 학습하기");layout(workspace);
                check(SwingUtilities.isDescendingFrom((Component)quiz,columns),"existing quiz instance mounted");
                set(workspace,"quizGenerating",true);columns.closeView("퀴즈로 학습하기");
                check((boolean)get(workspace,"quizGenerating"),"closing does not cancel quiz generation");set(workspace,"quizGenerating",false);
                columns.open("강의록");check(SwingUtilities.isDescendingFrom(notes,columns),"application transcript retained");
                check(button(columns,"강의록").getHorizontalAlignment()==SwingConstants.LEFT,"transcript title left aligned");
                JToggleButton pdfToggle=(JToggleButton)get(workspace,"pdfToggle");pdfToggle.doClick();
                check(pdfSplit.getLeftComponent()==null&&columns.count()==2,"PDF hides independently of both slots");pdfToggle.doClick();
                JPanel tutor=workspace.moveTutorToSidePanel(()->mentor.setOpen(true),()->mentor.setOpen(false));
                mentor.setSize(1500,800);mentor.setContent(tutor);
                JTextArea input=(JTextArea)get(workspace,"question");input.setText("미전송 질문");
                workspace.showTutor();check(mentor.isOpen()&&input.getText().equals("미전송 질문"),"programmatic mentor opens original composer");
                check(pdfSplit.getDividerLocation()==pdfWidth,"mentor opening leaves PDF width unchanged");
                mentor.setOpen(false,false);check(input.getText().equals("미전송 질문"),"collapse preserves draft");
                check(!((Timer)get(workspace,"tutorThinkingTimer")).isRunning(),"hidden mentor animation stopped");
                columns.closeView("요약");columns.closeView("개념정리");columns.closeView("강의록");
                check(!(boolean)get(workspace,"learningVisible"),"last slot closes outer panel");
                columns.open("요약");check((boolean)get(workspace,"learningVisible"),"add reopens outer panel");
                @SuppressWarnings("unchecked") java.util.Map<String,JToggleButton> navigation=(java.util.Map<String,JToggleButton>)get(workspace,"tabButtons");
                JPanel nav=workspace.moveLearningNavigation();nav.setSize(432,40);layout(nav);
                int row=navigation.get("요약").getY();
                check(!navigation.get("요약").getToolTipText().contains("새 학습창")
                    &&navigation.get("개념정리").getToolTipText().contains("새 학습창"),"add marker only advertises a new slot");
                for(String key:new String[]{"요약","개념정리","퀴즈로 학습하기","강의록"})
                    check(navigation.get(key).isVisible()&&navigation.get(key).getParent()!=null&&navigation.get(key).getY()==row,"restored navigation stays on one row");
                navigation.get("개념정리").doClick();check(columns.count()==2&&columns.containsView("요약")&&columns.containsView("개념정리"),"navigation opens second slot");
                for(String key:new String[]{"요약","개념정리","퀴즈로 학습하기","강의록"})
                    check(!navigation.get(key).getToolTipText().contains("새 학습창"),"full layout hides add markers");
                columns.noteInteraction((Component)summary);navigation.get("퀴즈로 학습하기").doClick();
                check(columns.containsView("퀴즈로 학습하기")&&columns.containsView("개념정리")&&!columns.containsView("요약"),"navigation replaces last clicked slot");
                columns.noteInteraction((Component)concept);navigation.get("강의록").doClick();
                check(columns.containsView("퀴즈로 학습하기")&&columns.containsView("강의록"),"last clicked other slot is replacement target");
                navigation.get("퀴즈로 학습하기").doClick();check(columns.count()==2&&columns.containsView("강의록"),"existing feature not duplicated or closed");
            }finally{mentor.close();workspace.close();}
        }catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS StudyWorkspaceColumns: real feature headers, PDF independence, recording view, quiz generation and tutor draft preservation");
        System.exit(0);
    }
    static Object get(Object o,String key)throws Exception{Field f=o.getClass().getDeclaredField(key);f.setAccessible(true);return f.get(o);}
    static void set(Object o,String key,Object value)throws Exception{Field f=o.getClass().getDeclaredField(key);f.setAccessible(true);f.set(o,value);}
    static JButton button(Container parent,String text){for(Component child:parent.getComponents()){if(child instanceof JButton b&&text.equals(b.getText()))return b;if(child instanceof Container c){JButton found=button(c,text);if(found!=null)return found;}}return null;}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}

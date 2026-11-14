package dev.synesis.poc.pdf;

import java.awt.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.Comparator;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.*;

/** Offline close/reopen contracts for the PDF and learning panes. */
public final class PaneCloseControlsTest {
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("pane-close-controls-");
        try {
            SwingUtilities.invokeAndWait(()->{try {
                workspacePanes(root);
            }catch(Exception failure){throw new RuntimeException(failure);}});
            System.out.println("PaneCloseControlsTest passed: learning/PDF close and reopen, moved PDF menu, stale actions, and mentor collapse.");
        } finally {try(var files=Files.walk(root)){for(Path path:files.sorted(Comparator.reverseOrder()).toList())Files.delete(path);}}
        System.exit(0);
    }
    private static void workspacePanes(Path root)throws Exception {
        PdfWorkspace workspace=new PdfWorkspace(false,root);
        try {
            JButton summary=button(workspace,"강의 흐름 창 닫기"),concept=button(workspace,"개념 정리 창 닫기");
            JButton quiz=button(workspace,"N제 창 닫기"),pdf=button(workspace,"PDF 원문 창 닫기");
            require(find(workspace,"강의 흐름 도구")==null&&find(workspace,"개념 정리 도구")==null,"obsolete dot menus removed");
            workspace.showSummary();set(workspace,"busy",true);summary.doClick();
            equal(get(workspace,"learningVisible"),false,"summary closes the learning pane");
            equal(get(workspace,"busy"),true,"close does not cancel generation");set(workspace,"busy",false);
            workspace.showConceptSummary();equal(get(workspace,"learningVisible"),true,"top navigation reopens concepts");
            summary.doClick();equal(get(workspace,"learningVisible"),true,"queued summary close cannot close another tab");
            concept.doClick();equal(get(workspace,"learningVisible"),false,"concept close");
            workspace.showLearningTab("퀴즈로 학습하기");set(workspace,"quizGenerating",true);quiz.doClick();
            equal(get(workspace,"learningVisible"),false,"quiz close");equal(get(workspace,"quizGenerating"),true,"quiz generation continues");
            set(workspace,"quizGenerating",false);workspace.showLearningTab("퀴즈로 학습하기");
            equal(get(workspace,"learningVisible"),true,"quiz reopens");
            JButton more=button(workspace,"PDF 도구"),expand=(JButton)get(workspace,"expandPdf");
            require(more.getParent()==expand.getParent(),"PDF tools move beside fullscreen");
            Container tools=more.getParent();require(tools.getComponent(0)==more&&tools.getComponent(1)==expand,"PDF tools sit immediately left of fullscreen");
            require(pdf.getParent()!=tools,"PDF close remains in the title row");
            Object pages=get(workspace,"sourceTabs");pdf.doClick();
            equal(get(workspace,"pdfVisible"),false,"PDF close");
            JToggleButton toggle=(JToggleButton)get(workspace,"pdfToggle");require(!toggle.isSelected(),"header PDF toggle reflects close");
            toggle.doClick();equal(get(workspace,"pdfVisible"),true,"header PDF toggle reopens");require(get(workspace,"sourceTabs")==pages,"existing PDF viewport is reused");
            workspace.showTutor();set(workspace,"tutorBusy",true);button(workspace,"AI멘토 창 닫기").doClick();
            equal(get(workspace,"learningVisible"),false,"standalone mentor closes");equal(get(workspace,"tutorBusy"),true,"mentor reply is preserved");set(workspace,"tutorBusy",false);
            AtomicInteger closed=new AtomicInteger();JPanel tutor=workspace.moveTutorToSidePanel(()->{},closed::incrementAndGet);
            JButton collapse=button(tutor,"AI멘토 창 닫기");collapse.doClick();equal(closed.get(),1,"docked mentor uses the application's close action");
            Container identity=collapse.getParent();identity.setSize(300,42);identity.doLayout();
            require(collapse.getX()+collapse.getWidth()<=identity.getComponent(1).getX(),"mentor arrow precedes its icon");
        } finally {workspace.close();}
    }
    private static JButton button(Container root,String name) {
        JButton button=find(root,name);if(button==null)throw new AssertionError("Missing "+name);return button;
    }
    private static JButton find(Container root,String name) {
        for(Component child:root.getComponents()) {
            if(child instanceof JButton button&&name.equals(button.getAccessibleContext().getAccessibleName()))return button;
            if(child instanceof Container nested){JButton found=find(nested,name);if(found!=null)return found;}
        }
        return null;
    }
    private static Object get(Object owner,String name)throws Exception{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner);}
    private static void set(Object owner,String name,Object value)throws Exception{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);f.set(owner,value);}
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
    private static void equal(Object actual,Object expected,String message){if(!Objects.equals(actual,expected))throw new AssertionError(message+": "+actual+" != "+expected);}
}

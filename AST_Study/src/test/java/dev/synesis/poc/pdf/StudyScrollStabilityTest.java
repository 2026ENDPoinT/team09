package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.SmoothScrollPane;
import java.awt.*;
import java.awt.event.*;
import java.lang.reflect.*;
import java.nio.file.Files;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import javax.swing.*;

/** Real wheel input and layout updates without a window, API, microphone or user-data files. */
public final class StudyScrollStabilityTest {
    public static void main(String[] args)throws Exception{
        SwingUtilities.invokeAndWait(()->{try{summary();reservedSpace();concepts();}catch(Exception error){throw new RuntimeException(error);}});
        SwingUtilities.invokeAndWait(()->{});
        System.out.println("StudyScrollStabilityTest passed: immediate wheel, stable streaming footprint, resume without catch-up, drag hold, completion, atomic summary/concept anchors and no late correction");
        System.exit(0);
    }
    private static void reservedSpace()throws Exception{
        AtomicLong now=new AtomicLong(1_000_000L);SummaryStreamSpace space=new SummaryStreamSpace(now::get);
        space.configure(true,true,16);space.measured(100);space.settle();space.measured(180);
        JPanel content=new JPanel();content.setPreferredSize(new Dimension(400,5000));
        JScrollPane scroll=new SmoothScrollPane(content);scroll.setSize(500,300);scroll.doLayout();
        scroll.getViewport().setViewPosition(new Point(0,500));
        StudyScrollActivity activity=new StudyScrollActivity(scroll,space::pause);
        try{
            wheel(scroll,1);check(scroll.getViewport().getViewPosition().y==518,"wheel distance changed or became delayed");
            check(activity.active()&&space.paused(),"scroll did not suspend decorative geometry");
            int footprint=space.footprint();now.addAndGet(2_000_000_000L);
            check(!space.tick(now.get())&&space.footprint()==footprint,"reserve keeps moving under the scrolling reader");
            space.measured(195);check(space.footprint()==footprint,"arriving text did not consume existing spare space");
            idle(activity);check(!activity.active()&&!space.paused(),"quiet input did not resume animation");
            check(!space.tick(now.get())&&space.footprint()==footprint,"resume jumped to the end of the paused animation");
            now.addAndGet(SummaryStreamSpace.MOTION_NANOS/2);space.tick(now.get());
            check(space.footprint()>footprint&&space.height()<100,"resume did not pass through intermediate heights");
            scroll.getVerticalScrollBar().setValueIsAdjusting(true);idle(activity);
            check(activity.active()&&space.paused(),"long scrollbar drag was mistaken for idle");
            space.measured(800);check(space.footprint()>=800,"pause clipped incoming real text");
            space.finish();check(space.height()==0&&!space.moving(),"generation completion waits indefinitely for scrolling to stop");
            scroll.getVerticalScrollBar().setValueIsAdjusting(false);idle(activity);
        }finally{activity.close();}
    }
    @SuppressWarnings("unchecked")
    private static void summary()throws Exception{
        PdfWorkspace workspace=new PdfWorkspace(false,Files.createTempDirectory("synesis-scroll-fixture-"));
        try{
            JScrollPane scroll=(JScrollPane)get(workspace,"summaryScroll");JPanel flow=(JPanel)get(workspace,"summaryFlow");
            scroll.setSize(650,350);scroll.doLayout();
            Method render=method(PdfWorkspace.class,"renderSummaryContent",String.class,Map.class);
            String body="<p>읽던 문장과 다음 문장을 유지해요. 화면 갱신 검사예요.</p>".repeat(100);
            render.invoke(workspace,body,Map.of());layout(scroll,flow);
            Method restore=method(PdfWorkspace.class,"restoreSummaryScroll",int.class,boolean.class,long.class);
            long gesture=(long)get(workspace,"summaryScrollInteraction");
            restore.invoke(workspace,700,false,gesture);
            check(scroll.getViewport().getViewPosition().y==700,"summary anchor is deferred past the current update");
            render.invoke(workspace,body+body,Map.of());restore.invoke(workspace,700,true,gesture);
            int bottom=scroll.getViewport().getViewSize().height-scroll.getViewport().getHeight();
            check(scroll.getViewport().getViewPosition().y==bottom,"bottom follow uses an old content height");
            wheel(scroll,-1);int afterWheel=scroll.getViewport().getViewPosition().y;
            check(afterWheel==bottom-18,"wheel does not start at the newly anchored bottom");
            Map<Integer,SummaryStreamSpace> spaces=(Map<Integer,SummaryStreamSpace>)get(workspace,"liveSummarySpaces");
            SummaryStreamSpace added=(SummaryStreamSpace)method(PdfWorkspace.class,"newSummaryStreamSpace").invoke(workspace);
            spaces.put(1,added);check(added.paused(),"a new streaming unit ignores an ongoing gesture");
            SecondaryLoop loop=Toolkit.getDefaultToolkit().getSystemEventQueue().createSecondaryLoop();
            javax.swing.Timer drain=new javax.swing.Timer(1,e->loop.exit());drain.setRepeats(false);drain.start();loop.enter();
            check(scroll.getViewport().getViewPosition().y==afterWheel,"a queued old restoration overwrote wheel input");
        }finally{workspace.close();}
    }
    private static void concepts()throws Exception{
        JPanel list=new JPanel();list.setLayout(new BoxLayout(list,BoxLayout.Y_AXIS));
        JScrollPane scroll=new SmoothScrollPane(list);
        ConceptOverview owner=new ConceptOverview(list,scroll,new JSlider(12,24,16),new JComboBox<>(new String[]{"전체"}),new JButton());
        try{
            List<ConceptOverview.Card> cards=new ArrayList<>();
            for(int i=0;i<35;i++){
                ConceptOverview.Card card=new ConceptOverview.Card("card-"+i,owner,false,open->{},page->{});
                card.update("개념 "+i,List.of(1),"v1",()->new JLabel("설명"));cards.add(card);
            }
            owner.setSize(650,650);owner.showCards("fixture",cards,"");owner.doLayout();layout(scroll,list);
            owner.restore(new ConceptOverview.Bookmark("card-15",7,0));
            check(owner.capture().key().equals("card-15")&&owner.capture().offset()==7,"concept anchor is deferred or clamped to stale height");
            cards.getFirst().update("줄바꿈이 생길 만큼 긴 개념 이름 ".repeat(12),List.of(1),"v2",()->new JLabel("설명"));
            ConceptOverview.Bookmark bookmark=owner.capture();owner.showCards("fixture",cards,"");
            check(owner.capture().key().equals(bookmark.key())&&owner.capture().offset()==bookmark.offset(),"concept refresh lost the reading anchor");
            check(list.getWidth()==scroll.getViewport().getWidth(),"concept restore changed the wrapping width");
            JPanel visibleParent=new JPanel(){@Override public boolean isShowing(){return true;}};
            JPanel content=new JPanel();content.setPreferredSize(new Dimension(200,300));
            ConceptOverview.Reveal reveal=new ConceptOverview.Reveal(content,false,owner);visibleParent.add(reveal);list.add(visibleParent);
            wheel(scroll,1);reveal.setOpen(true);
            javax.swing.Timer timer=(javax.swing.Timer)get(reveal,"timer");
            check(!timer.isRunning(),"new disclosure starts moving during a scroll gesture");
            idle((StudyScrollActivity)get(owner,"scrollActivity"));check(timer.isRunning(),"disclosure did not resume after input became quiet");
            reveal.removeNotify();
        }finally{owner.dispose();}
    }
    private static void idle(StudyScrollActivity activity)throws Exception{
        javax.swing.Timer idle=(javax.swing.Timer)get(activity,"idle");idle.stop();
        for(ActionListener action:idle.getActionListeners())action.actionPerformed(new ActionEvent(idle,0,"quiet"));
    }
    private static void wheel(JScrollPane scroll,int rotation){scroll.dispatchEvent(new MouseWheelEvent(scroll,MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),0,50,50,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,3,rotation));}
    private static void layout(JScrollPane scroll,JPanel list){scroll.doLayout();scroll.getViewport().setViewSize(list.getPreferredSize());list.doLayout();scroll.doLayout();}
    private static Object get(Object o,String name)throws Exception{Field field=o.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(o);}
    private static Method method(Class<?> type,String name,Class<?>...parameters)throws Exception{Method method=type.getDeclaredMethod(name,parameters);method.setAccessible(true);return method;}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}

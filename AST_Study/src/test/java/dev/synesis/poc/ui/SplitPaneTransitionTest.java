package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.util.concurrent.atomic.AtomicInteger;

/** Hidden native-free split hierarchy: animation frames must not repaint/reflow rich live content. */
public final class SplitPaneTransitionTest {
    static int checks;
    static class Counted extends JPanel {
        int layouts,paints;
        @Override public void doLayout(){layouts++;super.doLayout();}
        @Override protected void paintComponent(Graphics g){paints++;super.paintComponent(g);}
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" paint-only split transition, cancellation, cleanup and completion checks");
    }
    static void run()throws Exception {
        Counted left=new Counted(),right=new Counted();left.setMinimumSize(new Dimension());right.setMinimumSize(new Dimension());
        left.setBackground(Color.BLUE);right.setBackground(Color.RED);
        JSplitPane split=new JSplitPane(JSplitPane.HORIZONTAL_SPLIT,left,right){@Override public boolean isShowing(){return true;}};
        JRootPane root=new JRootPane();root.setContentPane(split);root.setSize(640,400);layout(root);split.setDividerLocation(420);layout(root);
        AtomicInteger finished=new AtomicInteger();int children=root.getLayeredPane().getComponentCount();
        split.setDividerLocation(500); // Intentionally leave native layout pending.
        Timer timer=SplitPaneTransition.animate(split,280,10000,()->{},finished::incrementAndGet);
        check(timer!=null&&timer.isRunning()&&split.getDividerLocation()==280,"final divider layout is committed once");
        Field initial=timer.getClass().getDeclaredField("before");initial.setAccessible(true);
        check(new Color(((BufferedImage)initial.get(timer)).getRGB(450,100)).equals(Color.BLUE),"first frame reflects the requested starting bounds, without an intermediate side-panel flash");
        int paints=left.paints+right.paints,layouts=left.layouts+right.layouts;
        Field overlayField=timer.getClass().getDeclaredField("overlay");overlayField.setAccessible(true);JComponent overlay=(JComponent)overlayField.get(timer);
        BufferedImage image=new BufferedImage(640,400,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        try{for(int i=0;i<60;i++)overlay.printAll(g);}finally{g.dispose();}
        check(paints==left.paints+right.paints&&layouts==left.layouts+right.layouts,"60 cached animation frames never paint or lay out live documents");
        timer.stop();timer.stop();
        check(finished.get()==0&&root.getLayeredPane().getComponentCount()==children,"cancellation removes the overlay without duplicate actions");
        Field before=timer.getClass().getDeclaredField("before");before.setAccessible(true);
        Field after=timer.getClass().getDeclaredField("after");after.setAccessible(true);
        check(before.get(timer)==null&&after.get(timer)==null,"cancellation releases both full-screen snapshots");
        Timer completed=SplitPaneTransition.animate(split,380,1,()->{},finished::incrementAndGet);
        Field started=completed.getClass().getDeclaredField("started");started.setAccessible(true);started.setLong(completed,System.nanoTime()-10_000_000);
        for(ActionListener listener:completed.getActionListeners())listener.actionPerformed(new ActionEvent(completed,0,"test"));
        check(finished.get()==1&&!completed.isRunning()&&root.getLayeredPane().getComponentCount()==children,"completion runs once and restores live controls");
        Timer resized=SplitPaneTransition.animate(split,320,10000,()->{},finished::incrementAndGet);
        split.setSize(600,380);
        for(ComponentListener listener:split.getComponentListeners())listener.componentResized(new ComponentEvent(split,ComponentEvent.COMPONENT_RESIZED));
        check(finished.get()==2&&!resized.isRunning()&&root.getLayeredPane().getComponentCount()==children,"resizing finishes cleanly instead of leaving a blocking layer");
        JSplitPane nested=new JSplitPane(JSplitPane.HORIZONTAL_SPLIT,new JPanel(),new JPanel()){@Override public boolean isShowing(){return true;}};
        left.setLayout(new BorderLayout());left.add(nested);layout(root);
        Timer outer=SplitPaneTransition.animate(split,360,10000,()->{},finished::incrementAndGet);
        Timer inner=SplitPaneTransition.animate(nested,100,10000,()->{},()->{});
        check(!outer.isRunning()&&finished.get()==3,"overlapping outer/inner animations settle once instead of competing");
        inner.stop();check(root.getLayeredPane().getComponentCount()==children,"nested animation cleanup leaves no blocking overlay");
    }
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
}

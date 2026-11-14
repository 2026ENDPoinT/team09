package dev.synesis.poc.ui;

import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import javax.swing.*;
import javax.swing.plaf.basic.BasicSplitPaneUI;

/** Real content stays live; queued pointer events commit only their latest position. */
public final class SplitDividerLiveResizeTest {
    private static final class Content extends JPanel {
        int paints, resizes;
        @Override protected void paintComponent(Graphics graphics) {
            paints++;
            super.paintComponent(graphics);
        }
        @Override public void setBounds(int x,int y,int width,int height) {
            if(width!=getWidth() || height!=getHeight())resizes++;
            super.setBounds(x,y,width,height);
        }
    }

    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(()->{
            check(JSplitPane.HORIZONTAL_SPLIT);
            check(JSplitPane.VERTICAL_SPLIT);
        });
        System.out.println("SplitDividerLiveResizeTest passed: live content, coalescing, release, clamp, cleanup");
    }

    private static void check(int orientation) {
        Content left=new Content(),right=new Content();
        left.setMinimumSize(new Dimension(80,80));right.setMinimumSize(new Dimension(80,80));
        JSplitPane split=new JSplitPane(orientation,left,right);
        split.setContinuousLayout(true);split.setDividerSize(1);
        SplitDividerHitLayer ui=new SplitDividerHitLayer();
        JLayer<JSplitPane> layer=new JLayer<>(split,ui);
        layer.setSize(900,600);layer.doLayout();split.setDividerLocation(300);split.doLayout();
        Component divider=((BasicSplitPaneUI)split.getUI()).getDivider();
        int start=split.getDividerLocation();
        int x=orientation==JSplitPane.HORIZONTAL_SPLIT?start:10;
        int y=orientation==JSplitPane.HORIZONTAL_SPLIT?10:start;
        dispatch(ui,layer,split,MouseEvent.MOUSE_PRESSED,x,y);
        int paints=left.paints+right.paints,resizes=left.resizes+right.resizes;
        BufferedImage target=new BufferedImage(900,600,BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics=target.createGraphics();
        try {
            for(int i=0;i<80;i++) {
                dispatch(ui,layer,split,MouseEvent.MOUSE_DRAGGED,
                    x+(orientation==JSplitPane.HORIZONTAL_SPLIT?i:0),
                    y+(orientation==JSplitPane.VERTICAL_SPLIT?i:0));
            }
            require(split.getDividerLocation()==start,"pointer events were not coalesced");
            tick(ui);
            require(split.getDividerLocation()==start+79,"live frame did not apply latest pointer position");
            layer.paint(graphics);
            require(left.paints+right.paints>paints,"drag still shows frozen content");
            require(left.resizes+right.resizes>resizes,"real panels did not resize during drag");
            dispatch(ui,layer,split,MouseEvent.MOUSE_RELEASED,
                x+(orientation==JSplitPane.HORIZONTAL_SPLIT?79:0),
                y+(orientation==JSplitPane.VERTICAL_SPLIT?79:0));
            require(split.getDividerLocation()==start+79,"release did not commit final position");
            require(split.isEnabled(),"native dragging was not restored");
            require(!Boolean.TRUE.equals(split.getClientProperty("synesis.dividerDragging")),"drag state remains active");
            layer.paint(graphics);
            require(!timer(ui).isRunning(),"release left a resize timer running");
            x=orientation==JSplitPane.HORIZONTAL_SPLIT?split.getDividerLocation():10;
            y=orientation==JSplitPane.HORIZONTAL_SPLIT?10:split.getDividerLocation();
            dispatch(ui,layer,split,MouseEvent.MOUSE_PRESSED,x,y);
            dispatch(ui,layer,split,MouseEvent.MOUSE_RELEASED,
                orientation==JSplitPane.HORIZONTAL_SPLIT?10000:x,
                orientation==JSplitPane.VERTICAL_SPLIT?10000:y);
            require(split.getDividerLocation()<=split.getMaximumDividerLocation(),"minimum content size lost");
            x=orientation==JSplitPane.HORIZONTAL_SPLIT?split.getDividerLocation():10;
            y=orientation==JSplitPane.HORIZONTAL_SPLIT?10:split.getDividerLocation();
            dispatch(ui,layer,split,MouseEvent.MOUSE_PRESSED,x,y);
            layer.setUI(null);
            require(split.isEnabled(),"uninstall left native dragging disabled");
            require(!timer(ui).isRunning(),"uninstall left a timer running");
        } finally {graphics.dispose();target.flush();}
    }

    private static void dispatch(SplitDividerHitLayer ui,JLayer<JSplitPane> layer,JSplitPane split,int id,int x,int y) {
        Component divider=((BasicSplitPaneUI)split.getUI()).getDivider();
        MouseEvent event=new MouseEvent(split,id,System.currentTimeMillis(),
            InputEvent.BUTTON1_DOWN_MASK,x,y,1,false,MouseEvent.BUTTON1);
        ui.eventDispatched(event,layer);
        // Consuming events alone does not stop BasicSplitPaneDivider's listener.
        if(id==MouseEvent.MOUSE_DRAGGED)
            for(MouseMotionListener listener:divider.getMouseMotionListeners())listener.mouseDragged(event);
        else for(MouseListener listener:divider.getMouseListeners()) {
            if(id==MouseEvent.MOUSE_PRESSED)listener.mousePressed(event);
            else listener.mouseReleased(event);
        }
    }

    private static Timer timer(SplitDividerHitLayer ui) {
        try {
            var field=SplitDividerHitLayer.class.getDeclaredField("dragTimer");field.setAccessible(true);
            return (Timer)field.get(ui);
        } catch(ReflectiveOperationException error) {throw new AssertionError(error);}
    }
    private static void tick(SplitDividerHitLayer ui) {
        Timer timer=timer(ui);
        for(ActionListener listener:timer.getActionListeners())listener.actionPerformed(new ActionEvent(timer,0,"tick"));
    }

    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
}

package dev.synesis.poc.ui;

import java.awt.event.MouseWheelEvent;
import javax.swing.JScrollBar;
import javax.swing.JScrollPane;

/** One app-wide wheel/trackpad scale, using the PDF reader's established six-pixel unit. */
public final class ScrollPolicy {
    public static final int PIXELS_PER_UNIT=6;
    private ScrollPolicy() {}

    public static double distance(MouseWheelEvent event){
        return event.getPreciseWheelRotation()*Math.max(1,event.getScrollAmount())*PIXELS_PER_UNIT;
    }
    public static double rotationForPixels(MouseWheelEvent event,double pixels){
        return pixels/(Math.max(1,event.getScrollAmount())*(double)PIXELS_PER_UNIT);
    }

    public static JScrollBar bar(JScrollPane pane,MouseWheelEvent event){
        JScrollBar vertical=pane.getVerticalScrollBar(),horizontal=pane.getHorizontalScrollBar();
        return event.isShiftDown()&&horizontal.isVisible()?horizontal:vertical.isVisible()?vertical:horizontal;
    }
}

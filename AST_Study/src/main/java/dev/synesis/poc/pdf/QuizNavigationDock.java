package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.MouseWheelEvent;
import java.awt.image.BufferedImage;
import java.util.function.IntFunction;
import javax.swing.*;
import javax.swing.border.EmptyBorder;

/** A non-overlapping viewport sibling: keep fixed controls out of the scrolling pixel region. */
final class QuizNavigationDock extends JLayeredPane {
    static final int HEIGHT=78;
    private static final int SHADOW_HEIGHT=16;
    // A single 64-byte alpha strip shared by every quiz. No blur, frame timer or per-size image cache.
    private static final BufferedImage SHADOW=shadow();
    private final JComponent content;
    private final JScrollPane scroll;
    private final IntFunction<Rectangle> column;
    final JPanel surface=new JPanel(new BorderLayout()) {
        @Override protected void paintComponent(Graphics graphics){
            graphics.drawImage(SHADOW,0,0,getWidth(),SHADOW_HEIGHT,null);
            // Only the thin shadow blends with the document; the controls use a fast opaque fill.
            graphics.setColor(Color.WHITE);graphics.fillRect(0,SHADOW_HEIGHT,getWidth(),getHeight()-SHADOW_HEIGHT);
        }
    };

    QuizNavigationDock(JComponent content,JScrollPane scroll,JComponent navigation,IntFunction<Rectangle> column){
        this.content=content;this.scroll=scroll;this.column=column;
        setOpaque(false);setLayout(null);
        surface.setName("quiz-fixed-navigation");surface.setOpaque(false);
        surface.setBorder(new EmptyBorder(SHADOW_HEIGHT+10,0,14,0));surface.add(navigation);
        surface.addMouseWheelListener(event->{
            Point point=SwingUtilities.convertPoint(surface,event.getPoint(),scroll);
            MouseWheelEvent forwarded=new MouseWheelEvent(scroll,event.getID(),event.getWhen(),event.getModifiersEx(),
                point.x,point.y,event.getXOnScreen(),event.getYOnScreen(),event.getClickCount(),event.isPopupTrigger(),
                event.getScrollType(),event.getScrollAmount(),event.getWheelRotation(),event.getPreciseWheelRotation());
            scroll.dispatchEvent(forwarded);if(forwarded.isConsumed())event.consume();
        });
        add(content,JLayeredPane.DEFAULT_LAYER);add(surface,JLayeredPane.PALETTE_LAYER);surface.setVisible(false);
    }
    void setActive(boolean active){if(surface.isVisible()!=active){surface.setVisible(active);revalidate();repaint();}}
    @Override public boolean isOptimizedDrawingEnabled(){return true;}
    @Override public Dimension getPreferredSize(){return content.getPreferredSize();}
    @Override public Dimension getMinimumSize(){return new Dimension(0,0);}
    @Override public void doLayout(){
        int height=surface.isVisible()?Math.min(getHeight(),Math.max(HEIGHT,surface.getPreferredSize().height)):0;
        content.setBounds(0,0,getWidth(),Math.max(0,getHeight()-height));content.doLayout();scroll.doLayout();
        if(height==0)return;
        JViewport viewport=scroll.getViewport();Rectangle bounds=column.apply(viewport.getWidth());
        Point origin=SwingUtilities.convertPoint(viewport,0,0,this);
        surface.setBounds(origin.x+bounds.x,getHeight()-height,bounds.width,height);
        surface.doLayout();
    }
    private static BufferedImage shadow(){
        BufferedImage strip=new BufferedImage(1,SHADOW_HEIGHT,BufferedImage.TYPE_INT_ARGB_PRE);
        for(int y=0;y<SHADOW_HEIGHT;y++){
            double amount=(y+1d)/SHADOW_HEIGHT;int alpha=(int)Math.round(15*amount*amount);
            strip.setRGB(0,y,alpha<<24);
        }
        return strip;
    }
}

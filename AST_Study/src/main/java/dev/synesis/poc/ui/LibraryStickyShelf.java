package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.util.function.BooleanSupplier;

/** One scrolling flow with a toolbar pinned to the viewport after its natural position.
 * Components keep their parent and identity, preserving text focus and card animations. */
public final class LibraryStickyShelf extends JPanel implements Scrollable {
    private final JComponent advertisement, toolbar, content;
    private final BooleanSupplier trackWidth;
    public LibraryStickyShelf(JComponent advertisement,JComponent toolbar,JComponent content,BooleanSupplier trackWidth){
        super(null);this.advertisement=advertisement;this.toolbar=toolbar;this.content=content;this.trackWidth=trackWidth;
        setBackground(LibraryDesign.CANVAS);
        add(toolbar);add(advertisement);add(content);
    }
    @Override public Dimension getPreferredSize(){
        Dimension a=advertisement.getPreferredSize(),t=toolbar.getPreferredSize(),c=content.getPreferredSize();
        return new Dimension(Math.max(a.width,Math.max(t.width,c.width)),a.height+t.height+c.height);
    }
    @Override public void doLayout(){
        int adHeight=advertisement.getPreferredSize().height,toolHeight=toolbar.getPreferredSize().height;
        int scrollY=getParent() instanceof JViewport viewport?viewport.getViewPosition().y:0;
        advertisement.setBounds(0,0,getWidth(),adHeight);
        toolbar.setBounds(0,Math.min(Math.max(adHeight,scrollY),Math.max(adHeight,getHeight()-toolHeight)),getWidth(),toolHeight);
        content.setBounds(0,adHeight+toolHeight,getWidth(),Math.max(0,getHeight()-adHeight-toolHeight));
    }
    public boolean toolbarPinned(){return getParent() instanceof JViewport viewport
        &&viewport.getViewPosition().y>=advertisement.getPreferredSize().height;}
    public void viewportChanged(){
        // Scrolling changes only the pinned toolbar's Y, never the ad/content
        // geometry. Avoid measuring and relaying out the entire shelf per event.
        int scrollY=getParent() instanceof JViewport viewport?viewport.getViewPosition().y:0;
        int adHeight=advertisement.getHeight(),toolHeight=toolbar.getHeight();
        int y=Math.min(Math.max(adHeight,scrollY),Math.max(adHeight,getHeight()-toolHeight));
        if(y==toolbar.getY())return;
        Rectangle before=toolbar.getBounds();toolbar.setLocation(toolbar.getX(),y);
        Rectangle dirty=before.union(toolbar.getBounds());repaint(dirty.x,dirty.y,dirty.width,dirty.height);
    }
    public Dimension getPreferredScrollableViewportSize(){return new Dimension(1000,700);}
    public int getScrollableUnitIncrement(Rectangle visible,int orientation,int direction){return 24;}
    public int getScrollableBlockIncrement(Rectangle visible,int orientation,int direction){return Math.max(24,visible.height-24);}
    public boolean getScrollableTracksViewportWidth(){return trackWidth.getAsBoolean();}
    public boolean getScrollableTracksViewportHeight(){return false;}
}

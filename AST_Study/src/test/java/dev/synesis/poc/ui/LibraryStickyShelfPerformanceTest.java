package dev.synesis.poc.ui;
import javax.swing.*;
import java.awt.*;
/** Scroll position changes must not measure or resize the ad/content tree. */
public final class LibraryStickyShelfPerformanceTest {
 static final class Probe extends JPanel {
  int measures,resizes;
  Probe(int height){setPreferredSize(new Dimension(800,height));}
  @Override public Dimension getPreferredSize(){measures++;return super.getPreferredSize();}
  @Override public void setBounds(int x,int y,int w,int h){if(getWidth()!=w||getHeight()!=h)resizes++;super.setBounds(x,y,w,h);}
 }
 public static void main(String[] args)throws Exception{
  SwingUtilities.invokeAndWait(()->{
   Probe ad=new Probe(176),toolbar=new Probe(48),content=new Probe(2200);
   LibraryStickyShelf shelf=new LibraryStickyShelf(ad,toolbar,content,()->true);
   JViewport viewport=new JViewport();viewport.setView(shelf);viewport.setSize(800,500);shelf.setSize(800,2424);shelf.doLayout();
   ad.measures=toolbar.measures=content.measures=0;ad.resizes=toolbar.resizes=content.resizes=0;
   Rectangle originalAd=ad.getBounds(),originalContent=content.getBounds();
   for(int y=0;y<600;y+=3){viewport.setViewPosition(new Point(0,y));shelf.viewportChanged();if(toolbar.getY()!=Math.max(176,y))throw new AssertionError("pinned toolbar position");}
   if(ad.measures+toolbar.measures+content.measures!=0)throw new AssertionError("scroll measured content");
   if(ad.resizes+toolbar.resizes+content.resizes!=0)throw new AssertionError("scroll resized content");
   if(!originalAd.equals(ad.getBounds())||!originalContent.equals(content.getBounds()))throw new AssertionError("scroll moved static content");
   viewport.setViewPosition(new Point());shelf.viewportChanged();if(toolbar.getY()!=176)throw new AssertionError("unpin");
   System.out.println("LibraryStickyShelfPerformanceTest OK · 200 scroll steps, zero content measurements/resizes, pin/unpin retained");
  });
 }
}

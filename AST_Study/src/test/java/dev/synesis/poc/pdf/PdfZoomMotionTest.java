package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.concurrent.atomic.AtomicInteger;
import javax.swing.SwingUtilities;

/** Offline motion lifecycle and bounded temporary raster regression. No app window/provider calls. */
public final class PdfZoomMotionTest {
    public static void main(String[] args)throws Exception {
        PdfZoomMotion[] holder=new PdfZoomMotion[1];AtomicInteger completed=new AtomicInteger(),abandoned=new AtomicInteger();
        BufferedImage source=new BufferedImage(2000,1500,BufferedImage.TYPE_INT_RGB);
        BufferedImage preview=PdfZoomMotion.preview(source);
        check(4L*preview.getWidth()*preview.getHeight()<=1L<<20,"preview exceeds one MiB");
        SwingUtilities.invokeAndWait(()->{
            PdfZoomMotion motion=holder[0]=new PdfZoomMotion(()->{});
            for(int i=0;i<20;i++)motion.dissolve(i,PdfZoomMotion.preview(source));
            check(motion.retainedBytes()<=4L<<20,"temporary dissolve budget exceeded");
            motion.zoom(1.05,200,200,abandoned::incrementAndGet);
            motion.zoom(1.15,200,200,completed::incrementAndGet);
            check(motion.zooming(),"zoom not active");
            check(motion.retainedBytes()==0,"retarget retained old dissolves");
        });
        Thread.sleep(350);
        SwingUtilities.invokeAndWait(()->{
            check(completed.get()==1&&abandoned.get()==0,"retarget published obsolete completion");
            PdfZoomMotion motion=holder[0];
            check(!motion.zooming(),"zoom did not finish");
            motion.dissolve(1,preview);
            BufferedImage canvas=new BufferedImage(20,20,BufferedImage.TYPE_INT_RGB);
            Graphics2D g=canvas.createGraphics();Composite composite=g.getComposite();
            motion.paint(g,1,source,new Rectangle(0,0,20,20));
            check(g.getComposite().equals(composite),"fade leaked graphics alpha");g.dispose();
        });
        Thread.sleep(250);
        SwingUtilities.invokeAndWait(()->{
            check(holder[0].retainedBytes()==0,"completed fade retained bitmap");
            holder[0].zoom(2,0,0,abandoned::incrementAndGet);holder[0].clear();
            check(!holder[0].zooming()&&holder[0].retainedBytes()==0,"dispose retained motion");
        });
        source.flush();System.out.println("PdfZoomMotionTest passed");System.exit(0);
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
